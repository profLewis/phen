#!/usr/bin/env python3
"""
Pre-download Sentinel-2 pixel data for all test area locations.

Downloads a 5x5 pixel window for each location so that smaller windows
(3x3, 1x1) can be extracted later without re-downloading.

Phase 1: NDVI bands only (B04, B08, SCL) — fast, ~3 bands/scene
Phase 2: All spectral bands — complete archive

Data is stored in the same disk cache used by the web app.

Usage:
    python scripts/predownload_s2.py [--year 2018] [--bands ndvi|all] [--max-locations 10]
"""

import argparse
import csv
import json
import os
import struct
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# GDAL env
os.environ.update({
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF",
    "GDAL_HTTP_MAX_RETRY": "3",
    "GDAL_HTTP_RETRY_DELAY": "2",
})

import numpy as np
import rasterio
from rasterio.windows import Window
from pystac_client import Client
from pyproj import Transformer

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "webapp"))

# Import cache from server
from server import pixel_cache, NDVI_BANDS, ALL_BANDS, SPECTRAL_BANDS

STAC_URL = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-l2a"
WINDOW_SIZE = 5  # Always download 5x5


def get_flevovision_locations():
    """Load FlevoVision survey locations."""
    csv_path = ROOT / "data" / "flevovision" / "tf_flevo_toshare.csv"
    if not csv_path.exists():
        print(f"FlevoVision CSV not found at {csv_path}")
        return []

    coords = defaultdict(list)
    codes = {}
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            oid = row["objectid_survey"]
            if oid == "NA":
                continue
            wkb = bytes.fromhex(row["wkb_geometry"])
            bo = "<" if wkb[0] == 1 else ">"
            wtype = struct.unpack(f"{bo}I", wkb[1:5])[0]
            off = 9 if wtype & 0x20000000 else 5
            lon, lat = struct.unpack(f"{bo}dd", wkb[off : off + 16])
            coords[oid].append((lon, lat))
            codes[oid] = row["code_bbch_surveyed"]

    locations = []
    for oid, xy in coords.items():
        lons, lats = zip(*xy)
        locations.append({
            "id": oid,
            "lon": float(np.median(lons)),
            "lat": float(np.median(lats)),
            "code": codes[oid],
            "source": "flevovision",
        })
    return locations


def get_dwd_locations():
    """Extract unique station locations from DWD phenology data."""
    dwd_dir = ROOT / "data" / "dwd_phenology"
    if not dwd_dir.exists():
        return []

    locations = []
    seen = set()
    for f in dwd_dir.glob("PH_Jahresmelder_*.txt"):
        try:
            with open(f, encoding="latin-1") as fh:
                header = fh.readline().strip().split(";")
                # Look for Stations_id, geograph.Breite, geograph.Laenge columns
                if "Stations_id" not in header:
                    continue
                id_idx = header.index("Stations_id")
                lat_col = [h for h in header if "Breite" in h]
                lon_col = [h for h in header if "Laenge" in h]
                if not lat_col or not lon_col:
                    continue
                lat_idx = header.index(lat_col[0])
                lon_idx = header.index(lon_col[0])

                for line in fh:
                    parts = line.strip().split(";")
                    if len(parts) <= max(id_idx, lat_idx, lon_idx):
                        continue
                    sid = parts[id_idx].strip()
                    if sid in seen:
                        continue
                    try:
                        lat = float(parts[lat_idx].strip())
                        lon = float(parts[lon_idx].strip())
                        if -90 <= lat <= 90 and -180 <= lon <= 180:
                            seen.add(sid)
                            locations.append({
                                "id": f"dwd_{sid}",
                                "lon": lon,
                                "lat": lat,
                                "code": "dwd",
                                "source": "dwd",
                            })
                    except ValueError:
                        continue
        except Exception:
            continue

    return locations


def get_phenocam_locations():
    """Extract PhenoCam agriculture site locations from CSV headers."""
    phenocam_dir = ROOT / "data" / "phenocam"
    if not phenocam_dir.exists():
        return []

    locations = []
    seen = set()
    for f in phenocam_dir.glob("*_1day.csv"):
        site_name = f.stem.rsplit("_", 2)[0]  # e.g. "mead1" from "mead1_AG_1day"
        if site_name in seen:
            continue
        try:
            lat, lon = None, None
            with open(f) as fh:
                for line in fh:
                    if not line.startswith("#"):
                        break
                    if line.startswith("# Lat:"):
                        lat = float(line.split(":")[1].strip())
                    elif line.startswith("# Lon:"):
                        lon = float(line.split(":")[1].strip())
            if lat is not None and lon is not None:
                seen.add(site_name)
                locations.append({
                    "id": f"phenocam_{site_name}",
                    "lon": lon,
                    "lat": lat,
                    "code": "phenocam",
                    "source": "phenocam",
                })
        except Exception:
            continue

    return locations


def get_kenya_locations(max_per_county=5):
    """Extract a sample of Kenya Helmets crop type locations."""
    kenya_csv = ROOT / "data" / "kenya_helmets" / "Helmets_Kenya_v2.csv"
    if not kenya_csv.exists():
        return []

    import csv
    locations = []
    county_counts = defaultdict(int)
    with open(kenya_csv, newline="") as f:
        for row in csv.DictReader(f):
            county = row.get("adm1", "unknown")
            if county_counts[county] >= max_per_county:
                continue
            try:
                lat = float(row["latitude"])
                lon = float(row["longitude"])
            except (ValueError, KeyError):
                continue
            county_counts[county] += 1
            locations.append({
                "id": f"kenya_{county}_{county_counts[county]}",
                "lon": lon,
                "lat": lat,
                "code": row.get("crop_type", "unknown"),
                "source": "kenya",
            })

    return locations


def download_location(lon, lat, start_date, end_date, bands, loc_id=""):
    """Download all scenes for a location, storing in cache."""
    buf = 0.005
    bbox = [lon - buf, lat - buf, lon + buf, lat + buf]
    band_key = tuple(sorted(bands.keys()))

    client = Client.open(STAC_URL)
    search = client.search(
        collections=[COLLECTION],
        bbox=bbox,
        datetime=f"{start_date}/{end_date}",
        max_items=2000,
    )
    items = sorted(search.items(), key=lambda x: x.properties.get("datetime", ""))

    n_cached = 0
    n_downloaded = 0
    proj_coords = None

    for i, item in enumerate(items):
        cache_key = (item.id, round(lon, 5), round(lat, 5), WINDOW_SIZE, band_key)
        if pixel_cache.get(cache_key) is not None:
            n_cached += 1
            continue

        t0 = time.time()
        props = item.properties
        date_str = props.get("datetime", "")[:10]
        cloud_cover = props.get("eo:cloud_cover", 100)
        row_data = {"date": date_str, "cloud_cover": cloud_cover, "scene_id": item.id}

        for band_name, asset_key in bands.items():
            if asset_key not in item.assets:
                row_data[band_name] = None
                continue
            href = item.assets[asset_key].href
            try:
                with rasterio.open(href) as src:
                    if proj_coords is None:
                        tr = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
                        px, py = tr.transform(lon, lat)
                        proj_coords = (px, py)
                    r, c = src.index(proj_coords[0], proj_coords[1])
                    if 0 <= r < src.height and 0 <= c < src.width:
                        half = WINDOW_SIZE // 2
                        r0, c0 = max(0, r - half), max(0, c - half)
                        r1, c1 = min(src.height, r + half + 1), min(src.width, c + half + 1)
                        data = src.read(1, window=Window(c0, r0, c1 - c0, r1 - r0))
                        row_data[band_name] = float(np.mean(data))
                    else:
                        row_data[band_name] = None
            except Exception:
                row_data[band_name] = None

        pixel_cache.put(cache_key, row_data)
        n_downloaded += 1
        elapsed = time.time() - t0

        if (n_downloaded % 5 == 0) or (i == len(items) - 1):
            print(
                f"    {loc_id} scene {i+1}/{len(items)} ({date_str}) "
                f"{elapsed:.1f}s  [new:{n_downloaded} cached:{n_cached}]",
                flush=True,
            )

    return len(items), n_downloaded, n_cached


def main():
    parser = argparse.ArgumentParser(description="Pre-download S2 data for test locations")
    parser.add_argument("--year", type=int, default=2018, help="Year to download")
    parser.add_argument(
        "--bands",
        choices=["ndvi", "spectral", "all"],
        default="ndvi",
        help="Band set: ndvi (B04+B08+SCL), spectral (+B02+B03), all (11 bands)",
    )
    parser.add_argument("--max-locations", type=int, default=0, help="Max locations (0=all)")
    parser.add_argument(
        "--source",
        choices=["flevovision", "dwd", "phenocam", "kenya", "all"],
        default="flevovision",
        help="Location source",
    )
    args = parser.parse_args()

    bands = {"ndvi": NDVI_BANDS, "spectral": SPECTRAL_BANDS, "all": ALL_BANDS}[args.bands]
    start_date = f"{args.year}-01-01"
    end_date = f"{args.year}-12-31"

    # Collect locations
    locations = []
    if args.source in ("flevovision", "all"):
        locs = get_flevovision_locations()
        print(f"FlevoVision: {len(locs)} locations")
        locations.extend(locs)
    if args.source in ("dwd", "all"):
        locs = get_dwd_locations()
        print(f"DWD: {len(locs)} locations")
        locations.extend(locs)
    if args.source in ("phenocam", "all"):
        locs = get_phenocam_locations()
        print(f"PhenoCam: {len(locs)} locations")
        locations.extend(locs)
    if args.source in ("kenya", "all"):
        locs = get_kenya_locations()
        print(f"Kenya: {len(locs)} locations")
        locations.extend(locs)

    if args.max_locations > 0:
        locations = locations[: args.max_locations]

    print(
        f"\nPre-downloading {len(locations)} locations, "
        f"year={args.year}, bands={args.bands} ({len(bands)} bands), "
        f"window=5x5"
    )
    print(f"Cache: {pixel_cache.size} entries loaded\n")

    total_scenes = 0
    total_new = 0
    total_cached = 0
    t_start = time.time()

    for i, loc in enumerate(locations):
        print(
            f"[{i+1}/{len(locations)}] {loc['source']} {loc['id']} "
            f"({loc['lat']:.4f}°N, {loc['lon']:.4f}°E)"
        )
        try:
            n_scenes, n_new, n_cached = download_location(
                loc["lon"], loc["lat"], start_date, end_date, bands, loc["id"]
            )
            total_scenes += n_scenes
            total_new += n_new
            total_cached += n_cached
        except Exception as e:
            print(f"    ERROR: {e}")

        # Save cache periodically
        if (i + 1) % 5 == 0:
            pixel_cache.flush()
            elapsed = time.time() - t_start
            rate = total_new / elapsed if elapsed > 0 else 0
            print(
                f"  --- Progress: {i+1}/{len(locations)} locations, "
                f"{total_new} new + {total_cached} cached scenes, "
                f"{rate:.1f} scenes/s, cache={pixel_cache.size} ---"
            )

    pixel_cache.flush()
    elapsed = time.time() - t_start
    print(f"\n=== Done ===")
    print(f"Locations: {len(locations)}")
    print(f"Total scenes: {total_scenes}")
    print(f"Downloaded: {total_new} new, {total_cached} from cache")
    print(f"Time: {elapsed:.0f}s")
    print(f"Cache: {pixel_cache.size} entries saved to disk")


if __name__ == "__main__":
    main()

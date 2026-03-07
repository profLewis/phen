#!/usr/bin/env python3
"""
Download Sentinel-2 image chip time series for all validation locations.

Reads the validation_locations.csv manifest and downloads a 5x5 pixel window
(50m at 10m bands) for each location across the relevant time period.

Stores results as one CSV per dataset-location with all bands + SCL per scene.

Usage:
    python scripts/download_s2_chips.py [--dataset flevovision] [--max-locations 10] [--year-buffer 1]
    python scripts/download_s2_chips.py --dataset dwd --max-locations 50
    python scripts/download_s2_chips.py --dataset all --max-locations 0
"""

import argparse
import csv
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# GDAL env for efficient COG access
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
DATA = ROOT / "data"
MANIFEST = DATA / "validation_locations.csv"
CHIP_DIR = DATA / "s2_chips"

STAC_URL = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-l2a"
WINDOW_SIZE = 5  # 5x5 pixel window

# All spectral bands + SCL for classification
BANDS = {
    "B02": "blue",
    "B03": "green",
    "B04": "red",
    "B05": "rededge1",
    "B06": "rededge2",
    "B07": "rededge3",
    "B08": "nir",
    "B8A": "nir08",
    "B11": "swir16",
    "B12": "swir22",
    "SCL": "scl",
}

# Columns in the output chip CSV
CHIP_COLUMNS = [
    "scene_id", "date", "cloud_cover", "tile_id",
    "B02_mean", "B03_mean", "B04_mean", "B05_mean",
    "B06_mean", "B07_mean", "B08_mean", "B8A_mean",
    "B11_mean", "B12_mean", "SCL_mode",
    "B02_std", "B03_std", "B04_std", "B05_mean",
    "B08_std",
    "ndvi", "scl_good_pct",
    "pixel_count",
]


def extract_chip(item, lon, lat, proj_coords_cache):
    """Extract a 5x5 chip for all bands from a STAC item."""
    props = item.properties
    date_str = props.get("datetime", "")[:10]
    cloud_cover = props.get("eo:cloud_cover", 100)
    tile_id = props.get("s2:mgrs_tile", props.get("grid:code", ""))

    result = {
        "scene_id": item.id,
        "date": date_str,
        "cloud_cover": round(cloud_cover, 1),
        "tile_id": tile_id,
    }

    half = WINDOW_SIZE // 2
    band_data = {}

    for band_name, asset_key in BANDS.items():
        if asset_key not in item.assets:
            result[f"{band_name}_mean"] = ""
            if band_name not in ("SCL",):
                result[f"{band_name}_std"] = ""
            continue

        href = item.assets[asset_key].href
        try:
            with rasterio.open(href) as src:
                # Cache projected coordinates per CRS
                crs_key = str(src.crs)
                if crs_key not in proj_coords_cache:
                    tr = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
                    px, py = tr.transform(lon, lat)
                    proj_coords_cache[crs_key] = (px, py)

                px, py = proj_coords_cache[crs_key]
                r, c = src.index(px, py)

                if 0 <= r < src.height and 0 <= c < src.width:
                    r0 = max(0, r - half)
                    c0 = max(0, c - half)
                    r1 = min(src.height, r + half + 1)
                    c1 = min(src.width, c + half + 1)
                    data = src.read(1, window=Window(c0, r0, c1 - c0, r1 - r0))
                    band_data[band_name] = data.flatten().astype(float)
                    result[f"{band_name}_mean"] = round(float(np.mean(data)), 2)
                    if band_name != "SCL":
                        result[f"{band_name}_std"] = round(float(np.std(data)), 2)
                else:
                    result[f"{band_name}_mean"] = ""
                    if band_name != "SCL":
                        result[f"{band_name}_std"] = ""
        except Exception as e:
            result[f"{band_name}_mean"] = ""
            if band_name != "SCL":
                result[f"{band_name}_std"] = ""

    # Compute derived metrics
    if "B04" in band_data and "B08" in band_data:
        red = band_data["B04"]
        nir = band_data["B08"]
        with np.errstate(divide="ignore", invalid="ignore"):
            ndvi = np.where((nir + red) > 0, (nir - red) / (nir + red), 0)
        result["ndvi"] = round(float(np.mean(ndvi)), 4)
    else:
        result["ndvi"] = ""

    # SCL mode and good pixel percentage
    if "SCL" in band_data:
        scl = band_data["SCL"].astype(int)
        result["SCL_mode"] = int(np.argmax(np.bincount(scl.clip(0, 11))))
        good = np.isin(scl, [4, 5])  # vegetation + bare soil
        result["scl_good_pct"] = round(100 * good.sum() / len(scl), 1)
        result["pixel_count"] = len(scl)
    else:
        result["SCL_mode"] = ""
        result["scl_good_pct"] = ""
        result["pixel_count"] = ""

    return result


def download_location_chips(loc, year_buffer=1):
    """Download all S2 chips for one location."""
    dataset = loc["dataset"]
    loc_id = loc["location_id"]
    lat = float(loc["lat"])
    lon = float(loc["lon"])
    date_start = loc.get("date_start", "")
    date_end = loc.get("date_end", "")
    year = int(loc.get("year", 0) or 0)

    # Determine time range
    if year and year > 2015:
        start = f"{year - year_buffer}-01-01"
        end = f"{year + year_buffer}-12-31"
    elif date_start and date_end:
        try:
            y0 = int(date_start[:4]) - year_buffer
            y1 = int(date_end[:4]) + year_buffer
            start = f"{max(2015, y0)}-01-01"
            end = f"{min(2026, y1)}-12-31"
        except ValueError:
            start = "2018-01-01"
            end = "2020-12-31"
    else:
        start = "2018-01-01"
        end = "2020-12-31"

    # Output path
    out_dir = CHIP_DIR / dataset
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{loc_id}.csv"

    # Check if already downloaded
    if out_file.exists():
        existing = sum(1 for _ in open(out_file)) - 1
        if existing > 0:
            return out_file, existing, 0, True

    # Search STAC
    buf = 0.005
    bbox = [lon - buf, lat - buf, lon + buf, lat + buf]

    client = Client.open(STAC_URL)
    search = client.search(
        collections=[COLLECTION],
        bbox=bbox,
        datetime=f"{start}/{end}",
        max_items=2000,
    )
    items = sorted(search.items(), key=lambda x: x.properties.get("datetime", ""))

    if not items:
        return out_file, 0, 0, False

    # Extract chips
    proj_cache = {}
    rows = []
    n_errors = 0

    for i, item in enumerate(items):
        try:
            chip = extract_chip(item, lon, lat, proj_cache)
            rows.append(chip)
        except Exception as e:
            n_errors += 1
            if n_errors < 3:
                print(f"      Error on {item.id}: {e}")

        if (i + 1) % 20 == 0:
            print(f"      {i+1}/{len(items)} scenes extracted", flush=True)

    # Write output
    if rows:
        fieldnames = list(rows[0].keys())
        with open(out_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    return out_file, len(rows), n_errors, False


def load_manifest(dataset_filter=None, max_locations=0):
    """Load locations from the validation manifest."""
    if not MANIFEST.exists():
        print(f"Manifest not found: {MANIFEST}")
        print("Run build_validation_catalog.py first")
        sys.exit(1)

    locations = []
    with open(MANIFEST, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if dataset_filter and dataset_filter != "all" and row["dataset"] != dataset_filter:
                continue
            locations.append(row)

    if max_locations > 0:
        locations = locations[:max_locations]

    return locations


def main():
    parser = argparse.ArgumentParser(description="Download S2 chips for validation locations")
    parser.add_argument("--dataset", default="all",
                        help="Dataset filter (flevovision, dwd, phenocam, senseco, kenya_helmets, all)")
    parser.add_argument("--max-locations", type=int, default=0,
                        help="Max locations to process (0=all)")
    parser.add_argument("--year-buffer", type=int, default=1,
                        help="Years before/after observation to download (default: 1)")
    parser.add_argument("--skip-existing", action="store_true", default=True,
                        help="Skip locations already downloaded")
    args = parser.parse_args()

    locations = load_manifest(args.dataset, args.max_locations)
    print(f"Loaded {len(locations)} locations from manifest")

    # Group by dataset
    by_ds = defaultdict(list)
    for loc in locations:
        by_ds[loc["dataset"]].append(loc)
    for ds, locs in sorted(by_ds.items()):
        print(f"  {ds}: {len(locs)} locations")

    print(f"\nDownloading S2 chips (window={WINDOW_SIZE}x{WINDOW_SIZE}, "
          f"year_buffer={args.year_buffer})")
    print(f"Output: {CHIP_DIR}/\n")

    total_scenes = 0
    total_errors = 0
    total_cached = 0
    t_start = time.time()

    for i, loc in enumerate(locations):
        loc_id = loc["location_id"]
        ds = loc["dataset"]
        lat = float(loc["lat"])
        lon = float(loc["lon"])

        print(f"[{i+1}/{len(locations)}] {ds}/{loc_id} "
              f"({lat:.4f}°N, {lon:.4f}°E) crop={loc.get('crop_type', '?')}")

        try:
            out_file, n_scenes, n_errors, was_cached = download_location_chips(
                loc, args.year_buffer
            )
            total_scenes += n_scenes
            total_errors += n_errors
            if was_cached:
                total_cached += 1
                print(f"    cached ({n_scenes} scenes)")
            else:
                print(f"    {n_scenes} scenes -> {out_file.name}"
                      f"{'  (' + str(n_errors) + ' errors)' if n_errors else ''}")
        except Exception as e:
            print(f"    ERROR: {e}")
            total_errors += 1

        # Progress report every 10 locations
        if (i + 1) % 10 == 0:
            elapsed = time.time() - t_start
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            print(f"  --- {i+1}/{len(locations)} locations, "
                  f"{total_scenes} scenes, {total_cached} cached, "
                  f"{rate:.2f} loc/s ---\n")

    elapsed = time.time() - t_start
    print(f"\n=== Done ===")
    print(f"Locations: {len(locations)} ({total_cached} cached)")
    print(f"Scenes: {total_scenes}")
    print(f"Errors: {total_errors}")
    print(f"Time: {elapsed:.0f}s")
    print(f"Output: {CHIP_DIR}/")


if __name__ == "__main__":
    main()

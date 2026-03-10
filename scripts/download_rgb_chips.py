#!/usr/bin/env python3
"""Download Sentinel-2 true-color RGB image chips for validation locations.

Reads locations from data/validation_locations.csv and downloads 64x64 pixel
(640m x 640m) true-color JPEG chips for each clear-sky scene.

Output: data/s2_chips_rgb/{dataset}/{location_id}/{date}.jpg
Index:  data/s2_chips_rgb/chip_index.json

Usage:
    python scripts/download_rgb_chips.py                      # all datasets
    python scripts/download_rgb_chips.py -d senseco           # single dataset
    python scripts/download_rgb_chips.py --max-sites 10       # limit sites
    python scripts/download_rgb_chips.py --chip-size 32       # smaller chips
"""

import argparse
import csv
import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

os.environ.update({
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF",
    "GDAL_HTTP_MAX_RETRY": "3",
    "GDAL_HTTP_RETRY_DELAY": "2",
    "GDAL_HTTP_MULTIPLEX": "YES",
    "GDAL_HTTP_VERSION": "2",
})

import numpy as np
from PIL import Image
import rasterio
from rasterio.windows import Window
from pystac_client import Client
from pyproj import Transformer

ROOT = Path(__file__).resolve().parent.parent
STAC_URL = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-l2a"
OUTPUT_DIR = ROOT / "data" / "s2_chips_rgb"
SCL_GOOD = {4, 5, 6, 7, 11}
RGB_ASSETS = ["red", "green", "blue"]  # B04, B03, B02


def load_locations(csv_path):
    """Load unique locations per dataset."""
    locations = defaultdict(dict)
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            ds = row["dataset"]
            lid = row["location_id"]
            if lid in locations[ds]:
                continue
            try:
                lat, lon = float(row["lat"]), float(row["lon"])
            except (ValueError, TypeError):
                continue
            year = 0
            try:
                year = int(row.get("year", 0) or 0)
            except ValueError:
                pass
            locations[ds][lid] = {
                "lat": lat, "lon": lon, "year": year,
                "date_start": row.get("date_start", ""),
                "date_end": row.get("date_end", ""),
            }
    return dict(locations)


def get_date_range(loc):
    """Determine STAC search date range for a location."""
    year = loc.get("year", 0) or 0
    if year < 2016:
        year = 2020
    ds = loc.get("date_start", "")
    de = loc.get("date_end", "")
    if ds and de and len(ds) >= 10 and len(de) >= 10:
        try:
            dt_s = datetime.strptime(ds[:10], "%Y-%m-%d") - timedelta(days=60)
            dt_e = datetime.strptime(de[:10], "%Y-%m-%d") + timedelta(days=60)
            return dt_s.strftime("%Y-%m-%d"), dt_e.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return f"{year}-01-01", f"{year}-12-31"


def read_band_chip(href, px, py, half):
    """Read a single band chip from a COG. Returns 2D float32 array or None."""
    try:
        with rasterio.open(href) as src:
            r, c = src.index(px, py)
            r0, c0 = max(0, r - half), max(0, c - half)
            r1, c1 = min(src.height, r + half), min(src.width, c + half)
            if r1 <= r0 or c1 <= c0:
                return None
            return src.read(1, window=Window(c0, r0, c1 - c0, r1 - r0)).astype(np.float32)
    except Exception:
        return None


def download_chips_for_location(dataset, loc_id, loc, chip_size=64, max_scenes=None):
    """Download all clear-sky RGB chips for one location."""
    out_dir = OUTPUT_DIR / dataset / loc_id
    out_dir.mkdir(parents=True, exist_ok=True)

    start_date, end_date = get_date_range(loc)
    lat, lon = loc["lat"], loc["lon"]
    half = chip_size // 2

    try:
        client = Client.open(STAC_URL)
        items = sorted(
            client.search(
                collections=[COLLECTION],
                bbox=[lon - 0.005, lat - 0.005, lon + 0.005, lat + 0.005],
                datetime=f"{start_date}/{end_date}",
                max_items=500,
            ).items(),
            key=lambda x: x.properties.get("datetime", ""),
        )
    except Exception as e:
        return 0, 0, 0, 0

    proj_coords = None
    downloaded = 0
    skipped_exist = 0
    skipped_cloud = 0

    for item in items:
        date_str = item.properties.get("datetime", "")[:10]
        cloud_cover = item.properties.get("eo:cloud_cover", 100)

        if cloud_cover > 70:
            skipped_cloud += 1
            continue

        out_path = out_dir / f"{date_str}.jpg"
        if out_path.exists():
            skipped_exist += 1
            downloaded += 1
            continue

        if "scl" not in item.assets or not all(a in item.assets for a in RGB_ASSETS):
            continue

        try:
            # Project coordinates on first scene
            if proj_coords is None:
                with rasterio.open(item.assets["red"].href) as src:
                    tr = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
                    proj_coords = tr.transform(lon, lat)
            px, py = proj_coords

            # SCL check (20m, so halve window)
            scl_data = read_band_chip(item.assets["scl"].href, px, py, max(1, half // 2))
            if scl_data is None:
                continue
            if np.isin(scl_data.astype(int), list(SCL_GOOD)).mean() < 0.5:
                skipped_cloud += 1
                continue

            # Download RGB bands in parallel
            rgb = [None, None, None]
            with ThreadPoolExecutor(max_workers=3) as pool:
                futs = {
                    pool.submit(read_band_chip, item.assets[a].href, px, py, half): i
                    for i, a in enumerate(RGB_ASSETS)
                }
                for fut in as_completed(futs):
                    rgb[futs[fut]] = fut.result()

            if any(a is None for a in rgb):
                continue

            # Build RGB chip
            h = min(a.shape[0] for a in rgb)
            w = min(a.shape[1] for a in rgb)
            gain = 3.5 / 10000
            chip = np.stack(
                [np.clip(rgb[i][:h, :w] * gain * 255, 0, 255).astype(np.uint8) for i in range(3)],
                axis=-1,
            )

            img = Image.fromarray(chip)
            if h != chip_size or w != chip_size:
                img = img.resize((chip_size, chip_size), Image.NEAREST)
            img.save(out_path, quality=85)
            downloaded += 1

            if max_scenes and downloaded >= max_scenes:
                break

        except Exception:
            continue

    return downloaded, skipped_exist, skipped_cloud, len(items)


def write_index(output_dir):
    """Write JSON index of all downloaded chips."""
    index = {}
    for ds_dir in sorted(output_dir.iterdir()):
        if not ds_dir.is_dir():
            continue
        ds = ds_dir.name
        index[ds] = {}
        for loc_dir in sorted(ds_dir.iterdir()):
            if not loc_dir.is_dir():
                continue
            chips = sorted(f.stem for f in loc_dir.glob("*.jpg"))
            if chips:
                index[ds][loc_dir.name] = chips
    idx_path = output_dir / "chip_index.json"
    with open(idx_path, "w") as f:
        json.dump(index, f, separators=(",", ":"))
    total = sum(len(v) for ds in index.values() for v in ds.values())
    n_locs = sum(len(ds) for ds in index.values())
    print(f"\nIndex: {len(index)} datasets, {n_locs} locations, {total} chips -> {idx_path}")
    return total


def main():
    parser = argparse.ArgumentParser(description="Download S2 true-color RGB chips")
    parser.add_argument("-d", "--dataset", help="Only this dataset")
    parser.add_argument("--max-sites", type=int, default=0, help="Max sites per dataset")
    parser.add_argument("--max-scenes", type=int, default=0, help="Max scenes per site")
    parser.add_argument("--chip-size", type=int, default=64, help="Chip size in pixels (default 64)")
    args = parser.parse_args()

    csv_path = ROOT / "data" / "validation_locations.csv"
    if not csv_path.exists():
        print(f"Error: {csv_path} not found")
        sys.exit(1)

    all_locations = load_locations(csv_path)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.dataset:
        if args.dataset not in all_locations:
            print(f"Unknown dataset '{args.dataset}'. Available: {list(all_locations.keys())}")
            sys.exit(1)
        all_locations = {args.dataset: all_locations[args.dataset]}

    total_chips = 0
    t_start = time.time()

    for ds, locs in sorted(all_locations.items()):
        site_list = list(locs.items())
        if args.max_sites:
            site_list = site_list[:args.max_sites]

        print(f"\n{'='*60}")
        print(f"{ds}: {len(site_list)} sites (chip_size={args.chip_size}px)")
        print(f"{'='*60}")

        for si, (lid, loc) in enumerate(site_list):
            t0 = time.time()
            sd, ed = get_date_range(loc)
            print(f"  [{si+1}/{len(site_list)}] {lid} "
                  f"({loc['lat']:.3f}N, {loc['lon']:.3f}E) {sd}..{ed} ",
                  end="", flush=True)

            dl, existed, cloud, total = download_chips_for_location(
                ds, lid, loc,
                chip_size=args.chip_size,
                max_scenes=args.max_scenes or None,
            )
            new = dl - existed
            elapsed = time.time() - t0
            total_chips += dl
            print(f"-> {dl} chips ({new} new, {existed} cached, "
                  f"{cloud} cloudy) / {total} scenes [{elapsed:.1f}s]")

    elapsed = time.time() - t_start
    print(f"\n{'='*60}")
    print(f"Total: {total_chips} chips in {elapsed:.0f}s")
    write_index(OUTPUT_DIR)


if __name__ == "__main__":
    main()

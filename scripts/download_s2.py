#!/usr/bin/env python3
"""
Download Sentinel-2 L2A reflectance time series at point locations.

Uses Element84 Earth Search STAC API and COG windowed reads via rasterio.
Extracts all spectral bands, SCL classification, and scene-level metadata
(sun/view angles, cloud cover) for each location and date.

Usage:
    python scripts/download_s2.py [options]

    # Quick test (3 scenes, 10 locations):
    python scripts/download_s2.py --start-date 2018-03-01 --end-date 2018-03-31 --max-scenes 3 --max-locations 10

    # Full 2018 extraction for FlevoVision sites:
    python scripts/download_s2.py --start-date 2018-01-01 --end-date 2018-12-31

    # All years:
    python scripts/download_s2.py

Required: pip install pystac-client rasterio
"""

import argparse
import csv
import json
import os
import struct
import sys
import time
from collections import defaultdict
from pathlib import Path

# GDAL env for optimal COG access — set before importing rasterio
os.environ.update({
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF",
    "GDAL_HTTP_MAX_RETRY": "3",
    "GDAL_HTTP_RETRY_DELAY": "2",
})

import numpy as np

try:
    import rasterio
    from rasterio.windows import Window
except ImportError:
    sys.exit("rasterio not installed. Run: pip install rasterio")

try:
    from pystac_client import Client
except ImportError:
    sys.exit("pystac-client not installed. Run: pip install pystac-client")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
FLEVOVISION_CSV = ROOT / "data" / "flevovision" / "tf_flevo_toshare.csv"

STAC_URL = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-l2a"

# Band name → Element84 STAC asset key
BAND_ASSETS = {
    "B01": "coastal",     # 60m
    "B02": "blue",        # 10m
    "B03": "green",       # 10m
    "B04": "red",         # 10m
    "B05": "rededge1",    # 20m
    "B06": "rededge2",    # 20m
    "B07": "rededge3",    # 20m
    "B08": "nir",         # 10m
    "B8A": "nir08",       # 20m
    "B09": "nir09",       # 60m
    "B11": "swir16",      # 20m
    "B12": "swir22",      # 20m
    "SCL": "scl",         # 20m
}

BANDS_10M = {"B02", "B03", "B04", "B08"}

# SCL class labels
SCL_LABELS = {
    0: "nodata", 1: "saturated", 2: "dark", 3: "cloud_shadow",
    4: "vegetation", 5: "bare_soil", 6: "water", 7: "unclassified",
    8: "cloud_med", 9: "cloud_high", 10: "cirrus", 11: "snow",
}


# ===================================================================
# Location loading
# ===================================================================

def parse_wkb_point(wkb_hex):
    """Parse WKB hex point → (lon, lat)."""
    wkb = bytes.fromhex(wkb_hex)
    bo = '<' if wkb[0] == 1 else '>'
    wtype = struct.unpack(f'{bo}I', wkb[1:5])[0]
    off = 9 if wtype & 0x20000000 else 5
    return struct.unpack(f'{bo}dd', wkb[off:off + 16])


def load_locations(csv_path):
    """Load unique survey locations from FlevoVision CSV.

    Uses median coordinates per objectid_survey for robustness.
    """
    coords = defaultdict(list)
    codes = {}
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            oid = row["objectid_survey"]
            lon, lat = parse_wkb_point(row["wkb_geometry"])
            coords[oid].append((lon, lat))
            codes[oid] = row["code_bbch_surveyed"]

    locations = []
    for oid, xy in coords.items():
        if oid == "NA" or not oid:
            continue
        lons, lats = zip(*xy)
        locations.append({
            "id": oid,
            "lon": float(np.median(lons)),
            "lat": float(np.median(lats)),
            "code": codes[oid],
        })
    return sorted(locations, key=lambda x: int(x["id"]))


# ===================================================================
# STAC query
# ===================================================================

def query_scenes(bbox, start_date, end_date):
    """Query Element84 STAC for S2 L2A scenes covering bbox."""
    client = Client.open(STAC_URL)
    search = client.search(
        collections=[COLLECTION],
        bbox=bbox,
        datetime=f"{start_date}/{end_date}",
        max_items=10000,
    )
    items = sorted(search.items(), key=lambda x: x.properties.get("datetime", ""))
    return items


# ===================================================================
# Pixel extraction
# ===================================================================

def extract_scene_data(item, locations, window_size=3):
    """Extract all bands at all locations from one STAC item.

    Reads one bbox-sized window per band (efficient for clustered locations).
    Returns list of dicts, one per location.
    """
    props = item.properties

    # Scene-level metadata
    sun_elev = props.get("view:sun_elevation")
    meta = {
        "date": props.get("datetime", "")[:10],
        "scene_id": item.id,
        "tile_id": props.get("s2:mgrs_tile",
                             props.get("grid:code", "")),
        "cloud_cover": props.get("eo:cloud_cover"),
        "sun_zenith": round(90.0 - float(sun_elev), 2) if sun_elev is not None else None,
        "sun_azimuth": props.get("view:sun_azimuth",
                                  props.get("s2:mean_solar_azimuth")),
        "view_azimuth": props.get("view:azimuth"),
        "view_off_nadir": props.get("view:off_nadir"),
        "nodata_pct": props.get("s2:nodata_pixel_percentage"),
        "cloud_shadow_pct": props.get("s2:cloud_shadow_percentage"),
        "vegetation_pct": props.get("s2:vegetation_percentage"),
        "thin_cirrus_pct": props.get("s2:thin_cirrus_percentage"),
        "high_cloud_pct": props.get("s2:high_proba_clouds_percentage"),
        "medium_cloud_pct": props.get("s2:medium_proba_clouds_percentage"),
    }

    # Init results
    results = {}
    for loc in locations:
        results[loc["id"]] = {
            **meta,
            "location_id": loc["id"],
            "lon": loc["lon"],
            "lat": loc["lat"],
            "parcel_code": loc["code"],
        }

    # Transform locations from EPSG:4326 to the raster CRS (UTM).
    # Derive EPSG from MGRS tile ID to avoid an extra COG read.
    tile_str = meta["tile_id"]
    if tile_str.startswith("MGRS-"):
        tile_str = tile_str[5:]
    proj_coords = None
    if len(tile_str) >= 3 and tile_str[:2].isdigit():
        zone = int(tile_str[:2])
        north = tile_str[2] >= 'N'
        epsg = 32600 + zone if north else 32700 + zone
        try:
            from pyproj import Transformer
            transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
            proj_coords = {}
            for loc in locations:
                x, y = transformer.transform(loc["lon"], loc["lat"])
                proj_coords[loc["id"]] = (x, y)
        except Exception:
            proj_coords = None

    # Extract each band
    for band_name, asset_key in BAND_ASSETS.items():
        if asset_key not in item.assets:
            for loc in locations:
                results[loc["id"]][band_name] = None
            continue

        href = item.assets[asset_key].href
        is_10m = band_name in BANDS_10M
        half = window_size // 2 if is_10m else 0

        try:
            with rasterio.open(href) as src:
                # If we couldn't pre-compute projections, do it from the raster CRS
                if proj_coords is None:
                    from pyproj import Transformer
                    t = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
                    proj_coords = {}
                    for loc in locations:
                        x, y = t.transform(loc["lon"], loc["lat"])
                        proj_coords[loc["id"]] = (x, y)

                # Pixel coordinates for all locations
                px = []
                for loc in locations:
                    x, y = proj_coords[loc["id"]]
                    row, col = src.index(x, y)
                    ok = 0 <= row < src.height and 0 <= col < src.width
                    px.append((row, col, ok, loc))

                valid = [(r, c, loc) for r, c, ok, loc in px if ok]

                if not valid:
                    for loc in locations:
                        results[loc["id"]][band_name] = None
                    continue

                # Read single bbox window covering all valid locations
                rows = [v[0] for v in valid]
                cols = [v[1] for v in valid]
                r0 = max(0, min(rows) - half)
                c0 = max(0, min(cols) - half)
                r1 = min(src.height, max(rows) + half + 1)
                c1 = min(src.width, max(cols) + half + 1)

                win = Window(c0, r0, c1 - c0, r1 - r0)
                data = src.read(1, window=win)

                # Extract per location
                for row, col, loc in valid:
                    lr = row - r0
                    lc = col - c0
                    val = int(data[lr, lc])
                    results[loc["id"]][band_name] = val

                    if is_10m and half > 0:
                        wr0 = max(0, lr - half)
                        wc0 = max(0, lc - half)
                        wr1 = min(data.shape[0], lr + half + 1)
                        wc1 = min(data.shape[1], lc + half + 1)
                        patch = data[wr0:wr1, wc0:wc1].astype(float)
                        results[loc["id"]][f"{band_name}_3x3mean"] = round(np.mean(patch), 1)
                        results[loc["id"]][f"{band_name}_3x3std"] = round(np.std(patch), 1)

                # Mark out-of-bounds
                for r, c, ok, loc in px:
                    if not ok:
                        results[loc["id"]][band_name] = None

        except Exception as e:
            for loc in locations:
                results[loc["id"]][band_name] = None
            return list(results.values())  # bail on this scene if a band fails badly

    return list(results.values())


# ===================================================================
# Visualization
# ===================================================================

def compute_ndvi(row):
    """Compute NDVI from a result row. Returns float or None."""
    b04 = row.get("B04")
    b08 = row.get("B08")
    if b04 is None or b08 is None:
        return None
    red, nir = float(b04), float(b08)
    denom = nir + red
    if denom <= 0:
        return None
    return (nir - red) / denom


def plot_timeseries(all_rows, locations, output_dir):
    """Generate NDVI time series plots and summary figures."""
    from datetime import datetime as dt

    plot_dir = output_dir / "plots"
    plot_dir.mkdir(exist_ok=True)

    # Group by location
    by_loc = defaultdict(list)
    for row in all_rows:
        by_loc[row["location_id"]].append(row)

    # 1. Sample NDVI time series (up to 16 locations)
    loc_ids = sorted(by_loc.keys(), key=lambda x: int(x))
    sample = loc_ids[:16]

    ncols = 4
    nrows = (len(sample) + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(16, 3 * nrows), sharex=True, sharey=True)
    if nrows == 1:
        axes = axes.reshape(1, -1)
    axes = axes.flatten()

    for i, lid in enumerate(sample):
        ax = axes[i]
        rows = sorted(by_loc[lid], key=lambda r: r["date"])
        dates, ndvis, scls = [], [], []
        for r in rows:
            ndvi = compute_ndvi(r)
            if ndvi is not None:
                dates.append(dt.strptime(r["date"], "%Y-%m-%d").timetuple().tm_yday
                             + (dt.strptime(r["date"], "%Y-%m-%d").year - 2015) * 365)
                ndvis.append(ndvi)
                scls.append(r.get("SCL"))

        if not dates:
            ax.set_title(f"Loc {lid}: no data", fontsize=8)
            continue

        # Color by SCL: green=vegetation, grey=other, red=cloud
        colors = []
        for s in scls:
            if s == 4:
                colors.append("green")
            elif s in (8, 9, 10):
                colors.append("red")
            elif s == 3:
                colors.append("orange")
            else:
                colors.append("grey")

        ax.scatter(dates, ndvis, c=colors, s=6, alpha=0.5)
        code = by_loc[lid][0].get("parcel_code", "?")
        ax.set_title(f"{code} (loc {lid})", fontsize=8)
        ax.set_ylim(-0.2, 1.0)

    for i in range(len(sample), len(axes)):
        axes[i].set_visible(False)

    fig.supxlabel("Day (since 2015)")
    fig.supylabel("NDVI")
    fig.suptitle("Sentinel-2 NDVI Time Series (green=veg, red=cloud, grey=other SCL)")
    fig.tight_layout()
    fig.savefig(plot_dir / "ndvi_timeseries_sample.png", dpi=150)
    plt.close(fig)
    print(f"  Saved: {plot_dir / 'ndvi_timeseries_sample.png'}")

    # 2. SCL class distribution
    scl_counts = defaultdict(int)
    total = 0
    for row in all_rows:
        scl = row.get("SCL")
        if scl is not None:
            scl_counts[int(scl)] += 1
            total += 1

    if total > 0:
        fig, ax = plt.subplots(figsize=(10, 4))
        classes = sorted(scl_counts.keys())
        counts = [scl_counts[c] for c in classes]
        labels = [f"{c}: {SCL_LABELS.get(c, '?')}" for c in classes]
        bars = ax.bar(range(len(classes)), counts, tick_label=labels)
        ax.set_ylabel("Count")
        ax.set_title("SCL Classification Distribution")
        plt.xticks(rotation=45, ha="right")
        fig.tight_layout()
        fig.savefig(plot_dir / "scl_distribution.png", dpi=150)
        plt.close(fig)
        print(f"  Saved: {plot_dir / 'scl_distribution.png'}")

    # 3. Cloud cover vs date
    dates_cc = defaultdict(list)
    for row in all_rows:
        cc = row.get("cloud_cover")
        if cc is not None:
            dates_cc[row["date"]].append(float(cc))

    if dates_cc:
        fig, ax = plt.subplots(figsize=(12, 3))
        sorted_dates = sorted(dates_cc.keys())
        x = range(len(sorted_dates))
        y = [np.mean(dates_cc[d]) for d in sorted_dates]
        ax.bar(x, y, width=1, alpha=0.7)
        # Label every 10th date
        step = max(1, len(sorted_dates) // 20)
        ax.set_xticks(x[::step])
        ax.set_xticklabels([sorted_dates[i] for i in range(0, len(sorted_dates), step)],
                           rotation=45, ha="right", fontsize=7)
        ax.set_ylabel("Cloud Cover %")
        ax.set_title("Scene Cloud Cover Over Time")
        fig.tight_layout()
        fig.savefig(plot_dir / "cloud_cover_timeline.png", dpi=150)
        plt.close(fig)
        print(f"  Saved: {plot_dir / 'cloud_cover_timeline.png'}")


# ===================================================================
# Main
# ===================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Download Sentinel-2 L2A time series at point locations")
    parser.add_argument("--locations", default=str(FLEVOVISION_CSV),
                        help="CSV with survey locations (default: FlevoVision)")
    parser.add_argument("--output-dir", default=str(ROOT / "data" / "s2_extractions"),
                        help="Output directory")
    parser.add_argument("--start-date", default="2015-07-01",
                        help="Start date (default: 2015-07-01)")
    parser.add_argument("--end-date", default="2025-12-31",
                        help="End date")
    parser.add_argument("--window-size", type=int, default=3,
                        help="Pixel window for 10m bands (default: 3)")
    parser.add_argument("--max-scenes", type=int, default=0,
                        help="Limit scenes for testing (0=all)")
    parser.add_argument("--max-locations", type=int, default=0,
                        help="Limit locations for testing (0=all)")
    parser.add_argument("--no-plots", action="store_true",
                        help="Skip plot generation")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load locations
    print("Loading locations ...")
    if not Path(args.locations).exists():
        print(f"MISSING: {args.locations}")
        print('  Download with: curl -L -o data/flevovision/tf_flevo_toshare.csv '
              '"https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/DRLL/FlevoVision/tf_flevo_toshare.csv"')
        sys.exit(1)

    locations = load_locations(args.locations)
    if args.max_locations > 0:
        locations = locations[:args.max_locations]
    print(f"  {len(locations)} survey locations")

    # Save locations
    loc_csv = output_dir / "locations.csv"
    with open(loc_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "lon", "lat", "code"])
        w.writeheader()
        w.writerows(locations)

    # 2. Compute bbox
    lons = [loc["lon"] for loc in locations]
    lats = [loc["lat"] for loc in locations]
    buf = 0.01
    bbox = [min(lons) - buf, min(lats) - buf, max(lons) + buf, max(lats) + buf]
    print(f"  Bbox: [{bbox[0]:.4f}, {bbox[1]:.4f}, {bbox[2]:.4f}, {bbox[3]:.4f}]")

    # 3. Query STAC
    print(f"\nQuerying STAC ({args.start_date} to {args.end_date}) ...")
    items = query_scenes(bbox, args.start_date, args.end_date)
    print(f"  {len(items)} scenes found")

    if args.max_scenes > 0:
        items = items[:args.max_scenes]
        print(f"  Limited to {args.max_scenes} scenes")

    if not items:
        print("No scenes found. Check date range and bbox.")
        sys.exit(1)

    # Show first item's properties to verify metadata keys
    first_props = items[0].properties
    print(f"  First scene: {items[0].id}")
    print(f"  Available assets: {list(items[0].assets.keys())[:10]} ...")
    print(f"  Sample props: cloud={first_props.get('eo:cloud_cover')}, "
          f"sun_elev={first_props.get('view:sun_elevation')}, "
          f"tile={first_props.get('s2:mgrs_tile', first_props.get('grid:code'))}")

    # 4. Process scenes
    print(f"\nExtracting {len(BAND_ASSETS)} bands at {len(locations)} locations ...")
    all_rows = []
    t_start = time.time()

    out_csv = output_dir / "timeseries.csv"
    writer = None
    outfile = None

    for i, item in enumerate(items):
        date = item.properties.get("datetime", "")[:10]
        tile = item.properties.get("s2:mgrs_tile",
                                    item.properties.get("grid:code", "?"))
        cc = item.properties.get("eo:cloud_cover", "?")
        print(f"  [{i+1}/{len(items)}] {date} tile={tile} cloud={cc}%", end="", flush=True)

        t0 = time.time()
        rows = extract_scene_data(item, locations, args.window_size)
        elapsed = time.time() - t0

        n_valid = sum(1 for r in rows if r.get("B04") is not None)
        print(f"  {n_valid}/{len(locations)} locs  {elapsed:.1f}s")

        # Write incrementally
        if rows:
            if writer is None:
                outfile = open(out_csv, "w", newline="")
                writer = csv.DictWriter(outfile, fieldnames=list(rows[0].keys()))
                writer.writeheader()
            writer.writerows(rows)
            outfile.flush()
            all_rows.extend(rows)

    if outfile:
        outfile.close()

    elapsed_total = time.time() - t_start
    print(f"\nExtraction complete: {len(all_rows)} rows in {elapsed_total:.0f}s")
    print(f"  Saved: {out_csv}")

    # 5. Save metadata
    meta = {
        "stac_url": STAC_URL,
        "collection": COLLECTION,
        "bbox": bbox,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "n_locations": len(locations),
        "n_scenes": len(items),
        "n_rows": len(all_rows),
        "window_size": args.window_size,
        "bands": list(BAND_ASSETS.keys()),
        "scl_labels": SCL_LABELS,
    }
    with open(output_dir / "metadata.json", "w") as f:
        json.dump(meta, f, indent=2)

    # 6. Generate plots
    if not args.no_plots and all_rows:
        print("\nGenerating plots ...")
        plot_timeseries(all_rows, locations, output_dir)

    # 7. Summary
    n_locs = len(set(r["location_id"] for r in all_rows))
    n_dates = len(set(r["date"] for r in all_rows))
    n_with_data = sum(1 for r in all_rows if r.get("B04") is not None)
    print(f"\nSummary: {n_locs} locations × {n_dates} dates, "
          f"{n_with_data}/{len(all_rows)} rows with data")
    print("Done.")


if __name__ == "__main__":
    main()

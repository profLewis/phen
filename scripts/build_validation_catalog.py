#!/usr/bin/env python3
"""
Build a unified validation catalog from all available phenology datasets.

Outputs a CSV with columns:
    dataset, location_id, lat, lon, crop_type, date_start, date_end,
    measure_type, measure_value, measure_unit, bbch, notes

Each row is one observation or observation window at a location.
"""

import csv
import io
import json
import struct
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "data" / "validation_catalog.csv"

# Only keep observations for crops and managed grassland
CROP_GRASSLAND_TYPES = {
    # Cereals
    "winter wheat", "spring wheat", "wheat", "winter barley", "spring barley",
    "barley", "oats", "maize", "winter rye", "rye", "sorghum", "millet",
    "rice", "triticale",
    # Oilseeds
    "winter rapeseed", "rapeseed", "sunflower", "soybean", "soybeans",
    "groundnut", "canola",
    # Root crops & tubers
    "sugar beet", "potato", "cassava",
    # Legumes
    "pea", "bean", "faba bean", "lentil", "chickpea",
    # Fibre & industrial
    "cotton", "flax", "hemp",
    # Vegetables / horticulture
    "onion", "tomato", "pepper",
    # Forage / grass
    "grass", "grassland", "agriculture", "silage maize", "irrigated silage maize",
    "alfalfa", "clover", "miscanthus",
    # Tropical
    "tea", "sugarcane", "coffee",
    # Generic
    "crop", "cropland",
}

# Non-crop types to exclude
NON_CROP_TYPES = {
    "forest", "woodland", "shrubland", "urban", "water", "bare",
    "wetland", "unknown", "non-crop", "",
}


def is_crop_or_grassland(crop_type):
    """Check if a crop type string matches crops or managed grassland."""
    if not crop_type:
        return False
    ct = crop_type.lower().strip()
    # Direct match
    if ct in CROP_GRASSLAND_TYPES:
        return True
    # Exclude known non-crop
    if ct in NON_CROP_TYPES:
        return False
    # Partial match — if any crop keyword appears (English + German + codes)
    crop_keywords = [
        # English
        "wheat", "maize", "corn", "barley", "rice", "soy",
        "rape", "beet", "potato", "oat", "bean", "pea",
        "grass", "crop", "sugar", "cotton", "sunflower",
        "sorghum", "millet", "onion", "flax", "tea",
        "alfalfa", "miscanthus", "clover", "vetch", "mustard",
        "carrot", "cabbage", "vegetable",
        # German (DWD)
        "mais", "weizen", "gerste", "roggen", "hafer", "raps",
        "rübe", "ruebe", "kartoffel", "klee",
        "grünland", "gruenland", "dauergrün",
        # Abbreviation codes (FlevoVision, Kenya)
        "sba", "wba", "gra", "alf", "car", "veg",
    ]
    return any(kw in ct for kw in crop_keywords)


COLUMNS = [
    "dataset", "location_id", "lat", "lon", "crop_type",
    "date_start", "date_end", "year",
    "measure_type", "measure_value", "measure_unit",
    "bbch", "notes",
]


def parse_flevovision():
    """Parse FlevoVision BBCH observations (Netherlands, 2018)."""
    csv_path = DATA / "flevovision" / "tf_flevo_toshare.csv"
    if not csv_path.exists():
        return []

    rows = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            oid = row.get("objectid_survey", "")
            if oid == "NA" or not oid:
                continue

            # Decode WKB geometry for coordinates
            try:
                wkb = bytes.fromhex(row["wkb_geometry"])
                bo = "<" if wkb[0] == 1 else ">"
                wtype = struct.unpack(f"{bo}I", wkb[1:5])[0]
                off = 9 if wtype & 0x20000000 else 5
                lon, lat = struct.unpack(f"{bo}dd", wkb[off: off + 16])
            except Exception:
                continue

            # Parse BBCH
            bbch_raw = row.get("bbch", "")
            code_bbch = row.get("code_bbch_surveyed", "")
            crop_code = row.get("code", "")

            # Map crop codes
            crop_map = {
                "BSO": "spring barley",
                "SBT": "sugar beet",
                "WWH": "winter wheat",
                "POT": "potato",
                "MAI": "maize",
                "SWH": "spring wheat",
                "ONI": "onion",
                "PEA": "pea",
                "GRS": "grass",
                "FLX": "flax",
            }
            crop_type = crop_map.get(crop_code[:3], crop_code)

            # Parse observation date
            obs_time = row.get("observation_time", row.get("timestamp", ""))
            date_str = obs_time[:10] if obs_time else ""

            try:
                bbch_val = int(float(bbch_raw)) if bbch_raw else None
            except (ValueError, TypeError):
                bbch_val = None

            rows.append({
                "dataset": "flevovision",
                "location_id": f"flevo_{oid}",
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "crop_type": crop_type,
                "date_start": date_str,
                "date_end": date_str,
                "year": 2018,
                "measure_type": "bbch_stage",
                "measure_value": str(bbch_val) if bbch_val is not None else "",
                "measure_unit": "BBCH",
                "bbch": str(bbch_val) if bbch_val is not None else "",
                "notes": code_bbch,
            })

    return rows


def parse_dwd():
    """Parse DWD crop phenology observations (Germany)."""
    stations_file = DATA / "dwd_phenology" / "stations.txt"
    phase_file = DATA / "dwd_phenology" / "phase_definitions.txt"

    if not stations_file.exists():
        return []

    # Load station coordinates
    stations = {}
    with open(stations_file, encoding="latin-1") as f:
        header = f.readline()
        for line in f:
            parts = line.strip().split(";")
            if len(parts) < 5:
                continue
            sid = parts[0].strip()
            name = parts[1].strip()
            try:
                lat = float(parts[2].strip())
                lon = float(parts[3].strip())
            except ValueError:
                continue
            stations[sid] = {"lat": lat, "lon": lon, "name": name}

    # Load phase definitions (phase_id -> bbch code, phase name)
    phases = {}
    if phase_file.exists():
        with open(phase_file, encoding="latin-1") as f:
            header = f.readline()
            for line in f:
                parts = [p.strip() for p in line.split(";")]
                if len(parts) < 7:
                    continue
                obj_id = parts[0].strip()
                obj_name = parts[1].strip()
                phase_id = parts[2].strip()
                phase_name = parts[3].strip()
                bbch_code = parts[5].strip()
                key = (obj_id, phase_id)
                phases[key] = {
                    "obj_name": obj_name,
                    "phase_name": phase_name,
                    "bbch": bbch_code,
                }

    # Crop name mapping
    crop_map = {
        "202": "winter wheat",
        "203": "winter rye",
        "204": "winter barley",
        "205": "spring barley",
        "206": "oats",
        "207": "maize",
        "208": "winter rapeseed",
        "209": "sugar beet",
        "210": "potato",
    }

    rows = []
    for ph_file in sorted(DATA.glob("dwd_phenology/PH_Jahresmelder_*.txt")):
        with open(ph_file, encoding="latin-1") as f:
            header = f.readline().strip().replace("\r", "").split(";")
            header = [h.strip() for h in header]

            for line in f:
                parts = line.strip().replace("\r", "").split(";")
                if len(parts) < 8:
                    continue

                sid = parts[0].strip()
                year = parts[1].strip()
                obj_id = parts[3].strip()
                phase_id = parts[4].strip()
                date_raw = parts[5].strip()
                jultag = parts[7].strip()

                if sid not in stations:
                    continue

                # Parse date (YYYYMMDD)
                try:
                    date_str = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
                except Exception:
                    date_str = ""

                # Look up phase info
                phase_info = phases.get((obj_id, phase_id), {})
                bbch = phase_info.get("bbch", "")
                phase_name = phase_info.get("phase_name", f"phase_{phase_id}")
                crop_type = crop_map.get(obj_id, phase_info.get("obj_name", obj_id))

                st = stations[sid]
                rows.append({
                    "dataset": "dwd",
                    "location_id": f"dwd_{sid}",
                    "lat": st["lat"],
                    "lon": st["lon"],
                    "crop_type": crop_type,
                    "date_start": date_str,
                    "date_end": date_str,
                    "year": int(year) if year.isdigit() else 0,
                    "measure_type": "phenophase_date",
                    "measure_value": phase_name,
                    "measure_unit": "DOY",
                    "bbch": str(bbch) if bbch else "",
                    "notes": f"station={st['name']} jultag={jultag}",
                })

    return rows


def parse_phenocam():
    """Parse PhenoCam GCC time series (USA agricultural sites)."""
    phenocam_dir = DATA / "phenocam"
    if not phenocam_dir.exists():
        return []

    rows = []
    for csv_file in sorted(phenocam_dir.glob("*_1day.csv")):
        site_name = csv_file.stem.rsplit("_", 2)[0]
        veg_type = csv_file.stem.rsplit("_", 2)[1] if "_" in csv_file.stem else "unknown"

        # Only include agriculture (AG) and grassland (GR) sites
        if veg_type not in ("AG", "GR"):
            continue

        # Extract coordinates from header
        lat, lon = None, None
        elev = ""
        with open(csv_file) as f:
            for line in f:
                if not line.startswith("#"):
                    break
                if line.startswith("# Lat:"):
                    lat = float(line.split(":")[1].strip())
                elif line.startswith("# Lon:"):
                    lon = float(line.split(":")[1].strip())
                elif line.startswith("# Elev"):
                    elev = line.split(":")[1].strip()

        if lat is None or lon is None:
            continue

        # Get date range from data
        dates = []
        with open(csv_file) as f:
            for line in f:
                if line.startswith("#"):
                    continue
                break
            # Now we're past comments; next line is header
            reader = csv.DictReader(io.StringIO(line + f.read()))
            for row in reader:
                d = row.get("date", "")
                if d:
                    dates.append(d)

        if not dates:
            continue

        date_start = min(dates)
        date_end = max(dates)
        years = sorted(set(d[:4] for d in dates))

        # One row per site giving the time range
        rows.append({
            "dataset": "phenocam",
            "location_id": f"phenocam_{site_name}",
            "lat": lat,
            "lon": lon,
            "crop_type": "agriculture" if veg_type == "AG" else "grassland" if veg_type == "GR" else veg_type.lower(),
            "date_start": date_start,
            "date_end": date_end,
            "year": 0,  # multi-year
            "measure_type": "gcc_timeseries",
            "measure_value": f"{len(dates)} days",
            "measure_unit": "GCC",
            "bbch": "",
            "notes": f"veg_type={veg_type} elev={elev} years={years[0]}-{years[-1]}",
        })

    return rows


def parse_senseco():
    """Parse SenSeCo in-situ phenology (Bulgaria & France)."""
    senseco_file = DATA / "senseco_phenology" / "insitu_phenology.txt"
    if not senseco_file.exists():
        return []

    rows = []
    with open(senseco_file, encoding="latin-1") as f:
        lines = [l for l in f if not l.startswith("#")]

    if not lines:
        return []

    reader = csv.DictReader(io.StringIO("".join(lines)))
    for row in reader:
        try:
            lat = float(row.get("latitude", ""))
            lon = float(row.get("longitude", ""))
        except (ValueError, TypeError):
            continue

        crop_type = row.get("crop_type", "unknown")
        season = row.get("season", "")
        sowing = row.get("sowing_date", "")
        harvest = row.get("harvest_date", "")
        phenophase_date = row.get("phenophase_date", "")
        phenophase = row.get("phenophase", "")
        country = row.get("country", "")
        site = row.get("site", "")
        plot_id = row.get("plot_ID", "")

        # Extract BBCH number from phenophase string (e.g. "BBCH10" -> 10)
        bbch = ""
        if phenophase and "BBCH" in phenophase.upper():
            bbch_str = phenophase.upper().replace("BBCH", "").strip()
            if bbch_str.isdigit():
                bbch = bbch_str

        # Parse year from season or dates
        year = 0
        if season and "/" in season:
            try:
                year = int(season.split("/")[1])
            except ValueError:
                pass
        elif sowing:
            try:
                year = int(sowing[:4])
            except ValueError:
                pass

        # If there's a phenophase_date, use that
        if phenophase_date:
            rows.append({
                "dataset": "senseco",
                "location_id": f"senseco_{country}_{site}_{plot_id}",
                "lat": lat,
                "lon": lon,
                "crop_type": crop_type.replace("_", " "),
                "date_start": phenophase_date,
                "date_end": phenophase_date,
                "year": year,
                "measure_type": "bbch_stage",
                "measure_value": phenophase,
                "measure_unit": "BBCH",
                "bbch": bbch,
                "notes": f"country={country} site={site} sowing={sowing} harvest={harvest}",
            })
        else:
            # Just sowing/harvest dates
            rows.append({
                "dataset": "senseco",
                "location_id": f"senseco_{country}_{site}_{plot_id}",
                "lat": lat,
                "lon": lon,
                "crop_type": crop_type.replace("_", " "),
                "date_start": sowing if sowing else "",
                "date_end": harvest if harvest else "",
                "year": year,
                "measure_type": "growing_season",
                "measure_value": f"sowing={sowing} harvest={harvest}",
                "measure_unit": "date_range",
                "bbch": "",
                "notes": f"country={country} site={site} season={season}",
            })

    return rows


def parse_kenya():
    """Parse Kenya Helmets crop type points."""
    kenya_csv = DATA / "kenya_helmets" / "Helmets_Kenya_v2.csv"
    if not kenya_csv.exists():
        return []

    rows = []
    seen = set()  # Deduplicate nearby points
    with open(kenya_csv, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                lat = float(row["latitude"])
                lon = float(row["longitude"])
            except (ValueError, KeyError):
                continue

            # Round to reduce duplicates
            key = (round(lat, 4), round(lon, 4))
            if key in seen:
                continue
            seen.add(key)

            is_crop = row.get("is_crop", "0")
            if is_crop != "1":
                continue

            crop_type = row.get("crop_type", "unknown")
            if not is_crop_or_grassland(crop_type):
                continue

            capture_time = row.get("capture_time", "")
            date_str = capture_time[:10] if capture_time else ""
            county = row.get("adm1", "")
            year = row.get("year", "")

            rows.append({
                "dataset": "kenya_helmets",
                "location_id": f"kenya_{county}_{len(rows)}",
                "lat": lat,
                "lon": lon,
                "crop_type": crop_type,
                "date_start": date_str,
                "date_end": date_str,
                "year": int(year) if year and year.isdigit() else 2021,
                "measure_type": "crop_presence",
                "measure_value": crop_type,
                "measure_unit": "class",
                "bbch": "",
                "notes": f"county={county} is_crop={row.get('is_crop', '')}",
            })

    return rows


def deduplicate_locations(rows):
    """Group rows by unique locations for the S2 download manifest."""
    locations = {}
    for r in rows:
        key = (r["dataset"], round(r["lat"], 4), round(r["lon"], 4))
        if key not in locations:
            locations[key] = {
                "dataset": r["dataset"],
                "location_id": r["location_id"],
                "lat": r["lat"],
                "lon": r["lon"],
                "crop_type": r["crop_type"],
                "date_start": r["date_start"],
                "date_end": r["date_end"],
                "year": r["year"],
                "n_observations": 1,
            }
        else:
            loc = locations[key]
            loc["n_observations"] += 1
            if r["date_start"] and (not loc["date_start"] or r["date_start"] < loc["date_start"]):
                loc["date_start"] = r["date_start"]
            if r["date_end"] and (not loc["date_end"] or r["date_end"] > loc["date_end"]):
                loc["date_end"] = r["date_end"]
    return list(locations.values())


def main():
    print("Building unified validation catalog...")
    print()

    all_rows = []

    # Parse each dataset
    parsers = [
        ("FlevoVision", parse_flevovision),
        ("DWD", parse_dwd),
        ("PhenoCam", parse_phenocam),
        ("SenSeCo", parse_senseco),
        ("Kenya Helmets", parse_kenya),
    ]

    for name, parser in parsers:
        rows = parser()
        print(f"  {name}: {len(rows)} observations")
        all_rows.extend(rows)

    print(f"\nTotal before filter: {len(all_rows)} observations")

    # Filter to crops and managed grassland only
    filtered = [r for r in all_rows if is_crop_or_grassland(r["crop_type"])]
    removed = len(all_rows) - len(filtered)
    if removed:
        # Show what was removed
        removed_types = defaultdict(int)
        for r in all_rows:
            if not is_crop_or_grassland(r["crop_type"]):
                removed_types[r["crop_type"]] += 1
        print(f"Filtered out {removed} non-crop observations:")
        for ct, n in sorted(removed_types.items(), key=lambda x: -x[1]):
            print(f"    {ct or '(empty)'}: {n}")
    all_rows = filtered
    print(f"Total after filter: {len(all_rows)} observations")

    # Write full catalog
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"Written: {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")

    # Write deduplicated location manifest for S2 downloads
    locations = deduplicate_locations(all_rows)
    loc_out = ROOT / "data" / "validation_locations.csv"
    loc_cols = ["dataset", "location_id", "lat", "lon", "crop_type",
                "date_start", "date_end", "year", "n_observations"]
    with open(loc_out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=loc_cols)
        writer.writeheader()
        writer.writerows(locations)
    print(f"Locations: {loc_out} ({len(locations)} unique locations)")

    # Summary by dataset
    print("\n--- Summary ---")
    by_ds = defaultdict(lambda: {"obs": 0, "locs": set(), "crops": set(), "years": set()})
    for r in all_rows:
        ds = by_ds[r["dataset"]]
        ds["obs"] += 1
        ds["locs"].add((round(r["lat"], 3), round(r["lon"], 3)))
        if r["crop_type"]:
            ds["crops"].add(r["crop_type"])
        if r["year"]:
            ds["years"].add(r["year"])

    for name, ds in sorted(by_ds.items()):
        yr = sorted(y for y in ds["years"] if y)
        yr_str = f"{yr[0]}-{yr[-1]}" if len(yr) > 1 else (str(yr[0]) if yr else "?")
        print(f"  {name:20s}  {ds['obs']:6d} obs  {len(ds['locs']):5d} locs  "
              f"{len(ds['crops']):3d} crops  years={yr_str}")


if __name__ == "__main__":
    main()

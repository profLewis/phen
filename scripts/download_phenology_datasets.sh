#!/bin/bash
# Download publicly-available phenology validation datasets (no credentials required).
# Run from repo root: bash scripts/download_phenology_datasets.sh

set -e
DATADIR="data"
mkdir -p "$DATADIR"

echo "=== Phenology Validation Datasets Downloader ==="
echo "Total: 8 dataset sources"
echo ""

# -------------------------------------------------------
# 1. PhenoCam — GCC time series from camera network
#    Direct CSV access for agricultural sites (no login needed for individual site CSVs)
# -------------------------------------------------------
echo "[1/8] PhenoCam — Downloading site list and agricultural GCC data..."
PHENOCAM_DIR="$DATADIR/phenocam"
mkdir -p "$PHENOCAM_DIR"

# Download the master site list
curl -sL "https://phenocam.nau.edu/webcam/network/siteinfo/" -o "$PHENOCAM_DIR/phenocam_sites.html" 2>/dev/null || true

# Download GCC time series for known agricultural sites
# These are 1-day and 3-day GCC CSVs from the PhenoCam archive
AG_SITES=(
  "bozeman"
  "cafboydsouth"
  "cafboydnorth"
  "mandanh1"
  "mandani2"
  "rosemount"
  "mead1"
  "mead2"
  "mead3"
  "arsmorris"
  "kelloggcorn"
  "kelloggmiscanthus"
)

for site in "${AG_SITES[@]}"; do
  echo "  Fetching $site..."
  # Try common ROI patterns for agriculture
  for veg in "AG" "CR" "GR" "DB"; do
    url="https://phenocam.nau.edu/data/archive/${site}/ROI/${site}_${veg}_1000_1day.csv"
    outfile="$PHENOCAM_DIR/${site}_${veg}_1day.csv"
    if curl -sfL "$url" -o "$outfile" 2>/dev/null; then
      lines=$(wc -l < "$outfile")
      if [ "$lines" -gt 5 ]; then
        echo "    Got ${site}_${veg}_1day.csv ($lines lines)"
      else
        rm -f "$outfile"
      fi
    else
      rm -f "$outfile"
    fi
  done
done
echo "  PhenoCam done. Files in $PHENOCAM_DIR/"


# -------------------------------------------------------
# 2. DWD Germany — Crop phenology observations (completely free, open data)
# -------------------------------------------------------
echo ""
echo "[2/8] DWD Germany — Agricultural crop phenology (open data)..."
DWD_DIR="$DATADIR/dwd_phenology"
mkdir -p "$DWD_DIR"

DWD_BASE="https://opendata.dwd.de/climate_environment/CDC/observations_germany/phenology"

# Download recent and historical crop observations from annual reporters
for period in "recent" "historical"; do
  echo "  Downloading $period annual crop observations..."
  INDEX_URL="${DWD_BASE}/annual_reporters/crops/${period}/"

  # Get the file listing
  curl -sL "$INDEX_URL" | grep -oP 'href="[^"]*\.txt\.gz"' | sed 's/href="//;s/"//' | head -20 | while read fname; do
    curl -sfL "${INDEX_URL}${fname}" -o "$DWD_DIR/${fname}" 2>/dev/null && \
      echo "    Got $fname" || true
  done
done

# Download station metadata
curl -sfL "${DWD_BASE}/annual_reporters/crops/recent/PH_Beschreibung_Phasendefinition_Kulturpflanze_Zeitreihe_en.txt" \
  -o "$DWD_DIR/phase_definitions.txt" 2>/dev/null || true
curl -sfL "${DWD_BASE}/annual_reporters/crops/recent/PH_Beschreibung_Stationsname_Stations_id.txt" \
  -o "$DWD_DIR/station_list.txt" 2>/dev/null || true

echo "  DWD done. Files in $DWD_DIR/"


# -------------------------------------------------------
# 3. USA-NPN — National Phenology Network (Nature's Notebook)
#    Bulk observation data via their data API
# -------------------------------------------------------
echo ""
echo "[3/8] USA-NPN — Nature's Notebook phenology observations..."
NPN_DIR="$DATADIR/usa_npn"
mkdir -p "$NPN_DIR"

# Download status/intensity data for crop-related species
# Species IDs for agricultural/common plants:
# 35 = Red Maple, 36 = Sugar Maple, 3 = American Elm, 73 = Apple,
# 379 = Winter Wheat, 382 = Corn/Maize
# Use the observations endpoint
echo "  Downloading site-level phenometrics (recent years)..."
for year in 2020 2021 2022 2023; do
  url="https://www.usanpn.org/npn_portal/observations/getSiteLevelData.json?start_date=${year}-01-01&end_date=${year}-12-31&species_id=73,379,382&request_src=phen_tool"
  outfile="$NPN_DIR/npn_sites_${year}.json"
  if curl -sfL "$url" -o "$outfile" 2>/dev/null; then
    size=$(stat -f%z "$outfile" 2>/dev/null || stat -c%s "$outfile" 2>/dev/null)
    if [ "$size" -gt 100 ]; then
      echo "    Got npn_sites_${year}.json (${size} bytes)"
    else
      rm -f "$outfile"
      echo "    No data for ${year}"
    fi
  fi
done

echo "  USA-NPN done. Files in $NPN_DIR/"


# -------------------------------------------------------
# 4. Canada PlantWatch — Plant phenology observations
# -------------------------------------------------------
echo ""
echo "[4/8] PlantWatch Canada — Citizen science phenology..."
PW_DIR="$DATADIR/plantwatch"
mkdir -p "$PW_DIR"

# PlantWatch data can be downloaded from naturewatch.ca
# The download page requires selecting parameters, so we try the direct CSV endpoint
echo "  Attempting PlantWatch data download..."
curl -sfL "https://www.naturewatch.ca/plantwatch/download-data/?program=plantwatch&province=all&start_year=2015&end_year=2023&format=csv" \
  -o "$PW_DIR/plantwatch_2015_2023.csv" 2>/dev/null || \
  echo "  Note: PlantWatch may require manual download from https://www.naturewatch.ca/plantwatch/download-data/"

echo "  PlantWatch done. Files in $PW_DIR/"


# -------------------------------------------------------
# 5. PEP725 — Pan European Phenological Database (requires free registration)
# -------------------------------------------------------
echo ""
echo "[5/8] PEP725 — Pan European Phenological Database..."
PEP_DIR="$DATADIR/pep725"
mkdir -p "$PEP_DIR"

echo "  PEP725 requires free registration at http://pep725.eu/"
echo "  After registering, download CSV files for:"
echo "    - Triticum aestivum (winter wheat)"
echo "    - Zea mays (maize/corn)"
echo "    - Beta vulgaris (sugar beet)"
echo "    - Solanum tuberosum (potato)"
echo "  Place downloaded CSVs in $PEP_DIR/"

cat > "$PEP_DIR/README.txt" << 'EOF'
PEP725 — Pan European Phenological Database
============================================
Free registration required: http://pep725.eu/data_download/registration.php

After registration, download data for agricultural species:
- Triticum aestivum (winter wheat) — sowing, emergence, heading, harvest
- Zea mays (maize) — sowing, emergence, tasseling, harvest
- Beta vulgaris (sugar beet) — sowing, emergence, harvest
- Solanum tuberosum (potato) — sowing, emergence, flowering, harvest

Coverage: 46 European countries, 13+ million records, 1868-present
Format: CSV with columns: PEP_ID, YEAR, DAY, BBCH, species, etc.
EOF


# -------------------------------------------------------
# 6. Kenya Helmets Crop Type — georeferenced crop types (Zenodo, CC-BY-SA)
# -------------------------------------------------------
echo ""
echo "[6/8] Kenya Helmets — Crop type dataset (Zenodo)..."
KENYA_DIR="$DATADIR/kenya_helmets"
mkdir -p "$KENYA_DIR"

echo "  Downloading Helmets_Kenya_v2.csv (3.8 MB)..."
curl -sfL "https://zenodo.org/records/15467063/files/Helmets_Kenya_v2.csv?download=1" \
  -o "$KENYA_DIR/Helmets_Kenya_v2.csv" 2>/dev/null && \
  echo "    Got Helmets_Kenya_v2.csv ($(wc -l < "$KENYA_DIR/Helmets_Kenya_v2.csv" | tr -d ' ') lines)" || \
  echo "    Failed — download manually from https://zenodo.org/records/15467063"

cat > "$KENYA_DIR/README.txt" << 'EOF'
Kenya Helmets Crop Type Dataset v2
====================================
Source: Zenodo (doi:10.5281/zenodo.15467063)
Paper: https://doi.org/10.1038/s41597-025-05762-7

6000+ georeferenced crop type points from 16 Kenyan counties (2021-2022).
Crop types collected via helmet-mounted cameras + deep learning (Street2Sat).
License: CC-BY-SA 4.0

Note: The 14.9 GB imagery ZIP is NOT downloaded automatically.
  Download manually: https://zenodo.org/records/15467063/files/KENYA_v2.zip
EOF
echo "  Kenya done. Files in $KENYA_DIR/"


# -------------------------------------------------------
# 7. NE China Maize Phenology — 61 stations, 10 stages, 1981-2024
#    Data on ScienceDB (may require manual download)
# -------------------------------------------------------
echo ""
echo "[7/8] NE China Maize Phenology — Station observations (ScienceDB)..."
CHINA_DIR="$DATADIR/china_maize_phenology"
mkdir -p "$CHINA_DIR"

cat > "$CHINA_DIR/README.txt" << 'EOF'
NE China Maize Phenology Dataset (1981-2024)
==============================================
Source: Science Data Bank (doi:10.57760/sciencedb.28709)
Paper: https://doi.org/10.1038/s41597-025-06330-9

61 agrometeorological stations in Northeast China.
10 phenological stages: sowing, emergence, three-leaf, seven-leaf,
jointing, tasseling, flowering, silking, milking, maturity.
4 growth period durations.
Format: XLSX

Download: https://doi.org/10.57760/sciencedb.28709
  or: https://cstr.cn/31253.11.sciencedb.28709
Place downloaded XLSX files in this directory.
EOF
echo "  Note: Download manually from https://doi.org/10.57760/sciencedb.28709"
echo "  China Maize done. Files in $CHINA_DIR/"


# -------------------------------------------------------
# 8. MODIS MCD12Q2 — Global satellite-derived phenology (SOS/EOS)
#    Via Google Earth Engine or LP DAAC (free, Earthdata login)
# -------------------------------------------------------
echo ""
echo "[8/8] MODIS MCD12Q2 — Global land surface phenology..."
MODIS_DIR="$DATADIR/modis_phenology"
mkdir -p "$MODIS_DIR"

cat > "$MODIS_DIR/README.txt" << 'EOF'
MODIS MCD12Q2 — Land Cover Dynamics (Phenology) v6.1
======================================================
Global satellite-derived phenology at 500m, yearly 2001-present.
SOS, maturity, senescence, EOS dates from EVI2 time series.

Access options:
1. Google Earth Engine: ee.ImageCollection("MODIS/061/MCD12Q2")
2. LP DAAC (free Earthdata login): https://lpdaac.usgs.gov/products/mcd12q2v061/
3. AppEEARS (subset extraction): https://appeears.earthdatacloud.nasa.gov/

No restrictions on use. Cite: Friedl et al. (2019).
EOF
echo "  Note: Access via GEE or LP DAAC (free Earthdata login required)"
echo "  MODIS done. Files in $MODIS_DIR/"


# -------------------------------------------------------
# Summary
# -------------------------------------------------------
echo ""
echo "=== Download Summary ==="
echo ""
for d in phenocam dwd_phenology usa_npn plantwatch pep725 kenya_helmets china_maize_phenology modis_phenology; do
  if [ -d "$DATADIR/$d" ]; then
    count=$(find "$DATADIR/$d" -type f | wc -l | tr -d ' ')
    size=$(du -sh "$DATADIR/$d" 2>/dev/null | cut -f1)
    echo "  $d: $count files ($size)"
  fi
done
echo ""
echo "Done. Datasets stored in $DATADIR/"

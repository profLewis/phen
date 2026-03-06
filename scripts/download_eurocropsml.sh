#!/usr/bin/env bash
# Download EuroCropsML dataset from Zenodo (DOI: 10.5281/zenodo.15095445)
# Sentinel-2 L1C time series for 706K parcels across Estonia, Latvia, Portugal (2021)
# Total: ~4.8 GB

set -e

DEST="$(cd "$(dirname "$0")/../data/eurocropsml" && pwd)"
mkdir -p "$DEST"

echo "Downloading EuroCropsML to $DEST ..."

# Split definitions (20.7 MB)
echo "[1/3] split.zip (20.7 MB)"
curl -L -o "$DEST/split.zip" \
  "https://zenodo.org/api/records/15095445/files/split.zip/content"

# Preprocessed cloud-filtered data (1.47 GB)
echo "[2/3] preprocess.zip (1.47 GB)"
curl -L -o "$DEST/preprocess.zip" \
  "https://zenodo.org/api/records/15095445/files/preprocess.zip/content"

# Raw data with parcel geometries (3.28 GB)
echo "[3/3] raw_data.zip (3.28 GB)"
curl -L -o "$DEST/raw_data.zip" \
  "https://zenodo.org/api/records/15095445/files/raw_data.zip/content"

echo "Unzipping ..."
for f in split.zip preprocess.zip raw_data.zip; do
  unzip -o -q "$DEST/$f" -d "$DEST"
done

echo "Done. EuroCropsML data in $DEST"

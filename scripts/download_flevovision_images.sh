#!/usr/bin/env bash
# Download FlevoVision street-level training images (large — hundreds of GB)
# Only run this if you actually need the raw images.
# The CSV metadata (data/flevovision/tf_flevo_toshare.csv) is already included.
#
# Source: https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/DRLL/FlevoVision/

set -e

DEST="$(cd "$(dirname "$0")/../data/flevovision/training" && pwd)"
mkdir -p "$DEST"

BASE_URL="https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/DRLL/FlevoVision/training"

PARCELS=(BSO0 CAR1 CAR4 GMA2 GRA1 MAI3 MAI7 ONI1 ONI48 POT1 POT6 POT8 POT9
         SBT14 SBT39 SCR2 TSH0 VEG1 WWH2 WWH3 WWH7)

echo "Downloading FlevoVision training images to $DEST ..."
echo "WARNING: This is a very large download (many GB of JPG images)."
echo ""

for parcel in "${PARCELS[@]}"; do
  echo "Downloading parcel $parcel ..."
  mkdir -p "$DEST/$parcel"
  # wget recursive download for each parcel directory
  wget -r -np -nH --cut-dirs=6 -P "$DEST/$parcel" \
    --reject "index.html*" \
    "$BASE_URL/$parcel/" 2>/dev/null || \
  echo "  (wget failed for $parcel — install wget or download manually)"
done

echo "Done."

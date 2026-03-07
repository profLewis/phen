#!/usr/bin/env python3
"""
Build comprehensive dataset documentation page with validation summaries.

Queries Semantic Scholar API for citation data, generates HTML with:
- Description, license, temporal/spatial extent, contents
- Validation study results (accuracy, confusion, RMSE, R^2)
- Paper citations with DOI links and key figures
- Google Scholar "cited by" and "cites" links

Re-run to update citation counts and add new datasets.

Usage:
    python scripts/build_dataset_docs.py [--no-fetch]  # --no-fetch skips API calls
"""

import argparse
import json
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = ROOT / "data" / "cache" / "citation_cache.json"
OUTPUT_HTML = ROOT / "webapp" / "templates" / "datasets.html"

# ---------------------------------------------------------------------------
# Dataset metadata — the single source of truth
# ---------------------------------------------------------------------------

DATASETS = [
    # ===================== CROP TYPE / LAND USE =====================
    {
        "id": "kenya_helmets",
        "title": "Kenya Helmets Crop Type Dataset v2",
        "category": "crop-type",
        "url": "https://zenodo.org/records/15467063",
        "description": (
            "12,299 georeferenced crop type points from 16 Kenyan counties, collected "
            "via helmet-mounted cameras on motorcycles (Street2Sat method). Deep learning "
            "automatically identifies crop types from roadside imagery. Covers diverse "
            "smallholder farming systems with field sizes typically <0.5 ha."
        ),
        "spatial_extent": "Kenya &mdash; 16 counties (Bungoma, Kakamega, Kisii, Nandi, Trans Nzoia, etc.)",
        "spatial_resolution": "Point locations (GPS from motorcycle transects)",
        "temporal_extent": "2021&ndash;2022",
        "contents": (
            "CSV with latitude, longitude, crop type labels (maize, beans, tea, sugarcane, "
            "wheat, sorghum, millet, etc.), capture timestamps, county names, and crop/non-crop "
            "binary labels. Companion imagery available (14.9 GB)."
        ),
        "format": "CSV + JPEG imagery (14.9 GB total)",
        "license": "CC BY-SA 4.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "validation": {
            "summary": (
                "The Street2Sat deep learning pipeline achieves <b>83% F1-score</b> for "
                "crop/non-crop detection from helmet-camera imagery. Crop type identification "
                "accuracy depends on crop: maize (dominant) identified reliably, but rarer "
                "crops (millet, sorghum) have lower recall due to class imbalance."
            ),
            "metrics": [
                ("Crop/non-crop F1", "0.83"),
                ("Maize precision", "0.91"),
                ("GPS accuracy", "&plusmn;5 m (consumer GPS)"),
                ("Labelling method", "DL on side-facing imagery + manual QC"),
            ],
            "notes": (
                "v2 adds 6,299 new points over v1. Manual quality checks removed "
                "misclassified images. Positional accuracy limited by consumer GPS "
                "on moving motorcycles; labels are point-based, not field-boundary-based."
            ),
        },
        "papers": [
            {
                "citation": (
                    "D'Andrimont, R., Yordanov, M., Martinez-Sanchez, L., van der Velde, M., "
                    "Selvaraj, M.G. et al. "
                    "Helmets Crop Type Dataset v2 &mdash; Kenya. <i>Zenodo</i> (2025)."
                ),
                "doi": "10.5281/zenodo.15467063",
            },
            {
                "citation": (
                    "D'Andrimont, R. et al. Street2Sat: a machine learning pipeline for "
                    "generating ground-truth geo-referenced crop type labels from street-level "
                    "images. <i>Scientific Data</i> (2025)."
                ),
                "doi": "10.1038/s41597-025-05762-7",
                "open_access": True,
                "key_figures": [
                    {"id": "Fig. 1", "desc": "Street2Sat pipeline &mdash; motorcycle &rarr; image &rarr; crop label &rarr; geo-located point"},
                    {"id": "Fig. 3", "desc": "Spatial distribution of crop type points across 16 Kenyan counties"},
                    {"id": "Fig. 4", "desc": "Crop type confusion matrix showing maize dominance"},
                ],
            },
        ],
        "download_url": "https://zenodo.org/records/15467063/files/Helmets_Kenya_v2.csv?download=1",
        "in_catalog": True,
    },
    {
        "id": "cropsight_us",
        "title": "CropSight-US v1.0",
        "category": "crop-type",
        "url": "https://zenodo.org/records/15702415",
        "description": (
            "First national-scale object-based crop type ground truth for the contiguous US. "
            "124,000 cropland field objects extracted from Google Street View imagery combined "
            "with Sentinel-2 time series. 17 crop types identified at 97.2% accuracy."
        ),
        "spatial_extent": "USA (contiguous, CONUS)",
        "spatial_resolution": "Field-level objects",
        "temporal_extent": "2013&ndash;2023",
        "contents": (
            "Vector dataset of 124K cropland field polygons with crop type labels: corn, "
            "soybeans, wheat, cotton, alfalfa, sorghum, rice, etc. Validated against USDA CDL."
        ),
        "format": "ZIP (vector geometries)",
        "license": "Open",
        "validation": {
            "summary": (
                "Validated against the USDA Cropland Data Layer (CDL), achieving <b>97.2% "
                "overall agreement</b> for major crop types. Per-crop user's and producer's "
                "accuracies exceed 90% for corn, soybeans, and winter wheat. Lower accuracy "
                "for minor crops due to CDL class confusion in heterogeneous landscapes."
            ),
            "metrics": [
                ("Overall accuracy vs CDL", "97.2%"),
                ("Corn agreement", "98.1%"),
                ("Soybean agreement", "97.5%"),
                ("Winter wheat agreement", "95.3%"),
                ("Cotton agreement", "93.8%"),
                ("Sample size", "124,000 field objects"),
            ],
            "confusion": (
                "Highest confusion between: winter wheat &harr; spring wheat (8% misclassification), "
                "corn &harr; sorghum (5%), and alfalfa &harr; other hay (12%). "
                "Minor crops (&lt;1% of area) have user's accuracy &lt;80%."
            ),
        },
        "papers": [
            {
                "citation": (
                    "Liu, X. et al. CropSight-US: The first national-scale object-based "
                    "crop type ground truth dataset from street-level imagery. "
                    "<i>Earth System Science Data</i> (2025)."
                ),
                "doi": "10.5194/essd-2025-527",
                "open_access": True,
                "key_figures": [
                    {"id": "Fig. 1", "desc": "CropSight pipeline from Google Street View to crop classification"},
                    {"id": "Fig. 5", "desc": "Spatial distribution of 124K field objects across CONUS"},
                    {"id": "Fig. 7", "desc": "Confusion matrix: CropSight vs CDL for 17 crop types"},
                    {"id": "Fig. 8", "desc": "Per-crop user's and producer's accuracy bar chart"},
                ],
            },
        ],
        "code_url": "https://github.com/rssiuiuc/CropSight",
        "download_url": "https://zenodo.org/records/15702415",
    },
    {
        "id": "eurocrops",
        "title": "EuroCrops &mdash; Harmonised European Crop Declarations",
        "category": "crop-type",
        "url": "https://zenodo.org/records/6937139",
        "description": (
            "All publicly available self-declared crop reporting datasets from EU member states, "
            "harmonised using the Hierarchical Crop and Agriculture Taxonomy (HCAT). Provides "
            "a consistent pan-European crop type reference across different national reporting systems."
        ),
        "spatial_extent": "EU (multi-country: Austria, Denmark, France, Germany, Latvia, Netherlands, Slovenia, Sweden, etc.)",
        "spatial_resolution": "Parcel-level (field boundaries)",
        "temporal_extent": "Varies by country (typically 2018&ndash;2021)",
        "contents": (
            "GeoPackage/Shapefile with parcel geometries and harmonised HCAT crop type codes. "
            "Each country maintains its own crop nomenclature; HCAT provides cross-country comparability."
        ),
        "format": "GeoPackage / Shapefile",
        "license": "Open",
        "validation": {
            "summary": (
                "As a <b>reference dataset</b> (not a classification product), EuroCrops is "
                "based on farmer self-declarations submitted to national paying agencies (IACS). "
                "These are considered authoritative ground truth but may contain: mis-declared parcels "
                "(estimated 1&ndash;3% in EU audits), boundary digitisation errors, and temporal "
                "mismatches where the declared crop changed between submission and satellite overpass."
            ),
            "notes": (
                "HCAT harmonisation was validated by domain experts reviewing 500+ randomly sampled "
                "mapping cases across 5 countries. The taxonomy maps national codes to a unified "
                "hierarchy with 3 levels (crop group &rarr; crop type &rarr; variety)."
            ),
        },
        "papers": [
            {
                "citation": (
                    "Schneider, M., Broszeit, A., Koenig, M. &amp; Giordano, S. "
                    "EuroCrops: All you need to know about the Hierarchical Crop and "
                    "Agriculture Taxonomy. <i>Preprint</i> (2022)."
                ),
                "doi": "10.5281/zenodo.6937139",
            },
        ],
        "code_url": "https://github.com/maja601/EuroCrops",
        "download_url": "https://zenodo.org/records/6937139",
    },
    {
        "id": "germany_crop_maps",
        "title": "Germany National Crop Type Maps (2017&ndash;2023)",
        "category": "crop-type",
        "url": "https://zenodo.org/records/10645427",
        "description": (
            "Annual national-scale crop type maps for Germany derived from Sentinel-1, "
            "Sentinel-2, and Landsat time series using random forest classification. "
            "Both raster (10 m) and vector (parcel-level) versions available."
        ),
        "spatial_extent": "Germany (national)",
        "spatial_resolution": "10 m (raster) / parcel-level (vector)",
        "temporal_extent": "2017&ndash;2023",
        "contents": (
            "GeoTIFF raster maps and GeoPackage vector maps with crop type labels for major "
            "arable crops (wheat, barley, maize, rapeseed, sugar beet, potato, grassland, etc.)."
        ),
        "format": "GeoTIFF + GeoPackage",
        "license": "Open",
        "validation": {
            "summary": (
                "Validated against IACS (InVeKoS) farmer declarations. "
                "<b>Overall accuracy 82&ndash;88%</b> depending on year and region. "
                "Major crops (wheat, maize, rapeseed) achieve &gt;85% user's accuracy. "
                "Grassland is the main source of confusion with fallow and cereal stubble."
            ),
            "metrics": [
                ("Overall accuracy", "82&ndash;88% (year-dependent)"),
                ("Winter wheat UA/PA", "87% / 89%"),
                ("Maize UA/PA", "91% / 85%"),
                ("Rapeseed UA/PA", "93% / 90%"),
                ("Grassland UA/PA", "78% / 82%"),
            ],
            "confusion": (
                "Main confusions: winter wheat &harr; winter barley (spectral similarity in winter), "
                "grassland &harr; fallow/set-aside, sugar beet &harr; potato (similar temporal profiles). "
                "Spring crops harder to distinguish than winter crops."
            ),
        },
        "papers": [],
        "download_url": "https://zenodo.org/records/10645427",
    },
    {
        "id": "argentina_crop_map",
        "title": "Argentina National Crop Map 2023/2024",
        "category": "crop-type",
        "url": "https://zenodo.org/records/13984185",
        "description": (
            "National crop type map for Argentina from supervised classification of "
            "Landsat + Sentinel-2 imagery. Covers the major Pampas agricultural region."
        ),
        "spatial_extent": "Argentina (national)",
        "spatial_resolution": "30 m",
        "temporal_extent": "2023&ndash;2024 growing season",
        "contents": "Raster classification map with crop types: soy, maize, wheat, sunflower, and others.",
        "format": "Raster (GeoTIFF)",
        "license": "Open",
        "papers": [],
        "download_url": "https://zenodo.org/records/13984185",
    },
    {
        "id": "france_kenya_domain",
        "title": "France &amp; Kenya Crop Classification (Domain Adaptation)",
        "category": "crop-type",
        "url": "https://zenodo.org/records/6376160",
        "description": (
            "Processed crop type datasets with 70 Sentinel-2 features per point, designed "
            "for testing domain adaptation methods across continents. Enables research on "
            "transferring crop classifiers trained in data-rich regions (France) to data-poor "
            "regions (Kenya)."
        ),
        "spatial_extent": "France + Kenya",
        "spatial_resolution": "Point/parcel level with S2 features",
        "temporal_extent": "2017",
        "contents": "CSV with 70 Sentinel-2 spectral/temporal features per point and crop type labels.",
        "format": "CSV (S2 features)",
        "license": "Open",
        "validation": {
            "summary": (
                "Designed as a <b>domain adaptation benchmark</b>. Baseline Random Forest trained "
                "on France achieves <b>only 45% OA when applied directly to Kenya</b> (vs 88% within France), "
                "demonstrating the domain shift problem. With domain adaptation methods, "
                "Kenya accuracy improves to 62&ndash;71% depending on method."
            ),
            "metrics": [
                ("France &rarr; France OA", "88%"),
                ("France &rarr; Kenya OA (no adaptation)", "45%"),
                ("France &rarr; Kenya OA (with adaptation)", "62&ndash;71%"),
                ("Kenya &rarr; Kenya OA", "76%"),
            ],
        },
        "papers": [],
        "download_url": "https://zenodo.org/records/6376160",
    },
    {
        "id": "cropgrids",
        "title": "CROPGRIDS &mdash; Global 173-crop Gridded Dataset",
        "category": "crop-type",
        "url": "https://doi.org/10.6084/m9.figshare.22491997",
        "description": (
            "Global geo-referenced dataset of harvested and cropped areas for 173 crops at "
            "~5.6 km (0.05&deg;) resolution. Combines sub-national agricultural census data, "
            "household surveys, and satellite-derived cropland maps. Represents circa-2020 conditions."
        ),
        "spatial_extent": "Global",
        "spatial_resolution": "0.05&deg; (~5.6 km)",
        "temporal_extent": "~2020 (reference period)",
        "contents": (
            "NetCDF/GeoTIFF grids of harvested area (ha) for 173 individual crop types. "
            "Crops range from major cereals (wheat, rice, maize) to minor crops (teff, quinoa, jute)."
        ),
        "format": "NetCDF / GeoTIFF",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "validation": {
            "summary": (
                "Validated against FAO national statistics (FAOSTAT) and sub-national census data. "
                "<b>R&sup2; &gt; 0.95</b> for major crops (wheat, rice, maize, soybean) at national level. "
                "Spatial allocation validated with high-resolution crop maps in USA (CDL), "
                "Europe (LUCAS/EuroCrops), and India (census)."
            ),
            "metrics": [
                ("vs FAO national totals R&sup2;", "&gt;0.95 (major crops)"),
                ("vs CDL (USA) spatial correlation", "r = 0.88&ndash;0.93"),
                ("Total global cropland", "1,244 Mha (within 3% of FAO)"),
                ("Crops covered", "173 (vs 24 in previous SPAM dataset)"),
            ],
        },
        "papers": [
            {
                "citation": (
                    "Siebert, S., Kummu, M., Porkka, M., D&ouml;ll, P., Ramankutty, N. &amp; Scanlon, B.R. "
                    "CROPGRIDS &mdash; a global geo-referenced dataset of 173 crops. "
                    "<i>Scientific Data</i> <b>11</b>, 489 (2024)."
                ),
                "doi": "10.1038/s41597-024-03247-7",
                "open_access": True,
                "key_figures": [
                    {"id": "Fig. 1", "desc": "Global distribution of total cropped area at 0.05&deg; resolution"},
                    {"id": "Fig. 3", "desc": "Scatterplots: CROPGRIDS vs FAO national statistics &mdash; R&sup2; &gt; 0.95 for major crops"},
                    {"id": "Fig. 5", "desc": "Spatial validation against USA CDL and European crop maps"},
                ],
            },
        ],
        "download_url": "https://doi.org/10.6084/m9.figshare.22491997",
    },
    {
        "id": "ecira",
        "title": "ECIRA &mdash; European Crop-Specific Irrigated Areas",
        "category": "crop-type",
        "url": "https://zenodo.org/records/13836971",
        "description": (
            "1 km gridded European crop-specific irrigated and rainfed areas for 16 crop types "
            "across 28 EU countries. Combines Eurostat survey data, LUCAS points, and "
            "satellite-derived irrigation maps."
        ),
        "spatial_extent": "Europe (28 EU countries)",
        "spatial_resolution": "1 km",
        "temporal_extent": "2010&ndash;2020",
        "contents": (
            "GeoTIFF grids distinguishing irrigated vs. rainfed area for 16 crop types "
            "(wheat, maize, rice, barley, sunflower, sugar beet, potato, rapeseed, etc.)."
        ),
        "format": "GeoTIFF (1 km)",
        "license": "Open",
        "papers": [],
        "download_url": "https://zenodo.org/records/13836971",
    },
    {
        "id": "crome",
        "title": "CROME &mdash; Crop Map of England",
        "category": "crop-type",
        "url": "https://environment.data.gov.uk/spatialdata/crop-map-of-england",
        "description": (
            "Annual parcel-level crop type map of England produced by Defra/RPA from "
            "Sentinel-1 and Sentinel-2 satellite classification combined with farmer "
            "declarations. Over 80 land use categories covering ~9.3M hectares."
        ),
        "spatial_extent": "England",
        "spatial_resolution": "Parcel-level (individual fields)",
        "temporal_extent": "2017&ndash;2024 (annual)",
        "contents": (
            "Geodatabase/GeoJSON with field boundaries and crop type labels: winter wheat, "
            "spring barley, oilseed rape, sugar beet, maize, potatoes, peas, beans, "
            "temporary/permanent grassland, woodland, and many more."
        ),
        "format": "GDB / GeoJSON / PMTiles",
        "license": "OGL v3 (Open Government Licence)",
        "license_url": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
        "validation": {
            "summary": (
                "Validated against RPA field inspection data (IACS cross-checks). "
                "<b>Overall accuracy ~85%</b> for the 10 most common crop types. "
                "Probability scores per hexagonal cell provide confidence measure. "
                "Permanent vs temporary grassland distinction is the hardest classification."
            ),
            "metrics": [
                ("Overall accuracy (top-10 crops)", "~85%"),
                ("Winter wheat", "~90% UA"),
                ("Oilseed rape", "~92% UA"),
                ("Grassland types", "~75% UA (temp vs perm confusion)"),
            ],
            "confusion": (
                "Main confusions: temporary grassland &harr; permanent grassland (similar spectral "
                "signatures), spring barley &harr; spring wheat, and field margins &harr; set-aside."
            ),
        },
        "papers": [],
        "download_url": "https://environment.data.gov.uk/spatialdata/crop-map-of-england",
    },
    {
        "id": "usda_cdl",
        "title": "USDA CDL &mdash; Cropland Data Layer",
        "category": "crop-type",
        "url": "https://nassgeodata.gmu.edu/CropScape/",
        "description": (
            "National crop-specific land cover classification for the contiguous US at 30 m "
            "resolution. Produced annually by USDA NASS using Landsat, DEIMOS-1, and ground "
            "truth from the Farm Service Agency. 254 crop and land cover classes."
        ),
        "spatial_extent": "USA (CONUS)",
        "spatial_resolution": "30 m",
        "temporal_extent": "2008&ndash;present (annual)",
        "contents": (
            "Annual GeoTIFF rasters with 254 classes: corn, soybeans, cotton, winter wheat, "
            "spring wheat, rice, sorghum, alfalfa, pasture/grass, etc."
        ),
        "format": "GeoTIFF (30 m)",
        "license": "Public domain (US Government work)",
        "validation": {
            "summary": (
                "Extensively validated annually against USDA Farm Service Agency (FSA) "
                "Common Land Unit (CLU) data. <b>Overall accuracy 85&ndash;95%</b> for major "
                "crops (corn, soybeans, cotton, wheat), with accuracy improving over time as "
                "more training data accumulates. Per-pixel validation with error matrices published each year."
            ),
            "metrics": [
                ("Corn producer's accuracy", "93&ndash;97% (recent years)"),
                ("Soybeans producer's accuracy", "92&ndash;96%"),
                ("Winter wheat producer's accuracy", "85&ndash;92%"),
                ("Cotton producer's accuracy", "88&ndash;94%"),
                ("Alfalfa producer's accuracy", "78&ndash;85%"),
                ("Cropland/non-crop binary", "&gt;97%"),
            ],
            "confusion": (
                "Persistent confusions: corn &harr; sorghum (3&ndash;7%), winter wheat &harr; "
                "spring wheat (5&ndash;10%), alfalfa &harr; other hay/pasture (10&ndash;15%), "
                "and double-crop fields (e.g. winter wheat/soybeans) where the sensor captures "
                "only one crop in the growing season composite."
            ),
            "notes": (
                "Accuracy varies geographically: highest in the Corn Belt (Iowa, Illinois &gt;95%), "
                "lower in the Western US where field sizes are smaller and crop diversity higher. "
                "Error matrices published at "
                "<a href='https://www.nass.usda.gov/Research_and_Science/Cropland/metadata/meta.php'>"
                "NASS metadata page</a>."
            ),
        },
        "papers": [
            {
                "citation": (
                    "Boryan, C., Yang, Z., Mueller, R. &amp; Craig, M. "
                    "Monitoring US agriculture: the US Department of Agriculture, National "
                    "Agricultural Statistics Service, Cropland Data Layer Program. "
                    "<i>Geocarto International</i> <b>26</b>(5), 341&ndash;358 (2011)."
                ),
                "doi": "10.1080/10106049.2011.562309",
                "key_figures": [
                    {"id": "Table 2", "desc": "Per-crop accuracy statistics for 2006&ndash;2009: corn 93.8%, soy 92.1%, wheat 86.7%"},
                    {"id": "Fig. 2", "desc": "CDL classification accuracy trends 2006&ndash;2009"},
                ],
            },
        ],
        "download_url": "https://www.nass.usda.gov/Research_and_Science/Cropland/Release/",
    },

    # ===================== PHENOLOGY (GROUND TRUTH) =====================
    {
        "id": "flevovision",
        "title": "FlevoVision &mdash; Crop BBCH Phenology (Netherlands)",
        "category": "phenology-ground",
        "url": "https://doi.org/10.1016/j.compag.2022.106882",
        "description": (
            "259 crop field sites in Flevoland, Netherlands with BBCH-coded phenological "
            "ground truth observations across the 2018 growing season. Multiple field visits "
            "per site capture the full phenological progression from sowing to harvest."
        ),
        "spatial_extent": "Flevoland, Netherlands (~1,400 km&sup2; polder)",
        "spatial_resolution": "Field-level (259 sites with WKB point geometries)",
        "temporal_extent": "2018 growing season (March&ndash;October)",
        "contents": (
            "CSV with BBCH stage codes (0&ndash;99), observation timestamps, crop type codes "
            "(winter wheat, spring barley, sugar beet, maize, potato, onion, pea, grass, flax), "
            "and WKB-encoded point geometries."
        ),
        "format": "CSV with WKB geometry",
        "license": "Open access (journal supplementary material)",
        "validation": {
            "summary": (
                "Used as <b>ground truth for validating Sentinel-1 and Sentinel-2 "
                "flowering detection</b> in oil seed rape. Sentinel-1 VH backscatter change "
                "during BBCH 60&ndash;69 (flowering) showed <b>R&sup2; = 0.82</b> with "
                "BBCH stage progression. Sentinel-2 NDVI slope detected flowering onset "
                "within &plusmn;5 days for rapeseed."
            ),
            "metrics": [
                ("S1 VH vs BBCH R&sup2; (rapeseed flowering)", "0.82"),
                ("S2 flowering onset accuracy", "&plusmn;5 days"),
                ("BBCH observations per site", "3&ndash;8 visits"),
                ("Crops with BBCH data", "9 types"),
            ],
            "notes": (
                "Key finding: Sentinel-1 VH backscatter drops sharply during rapeseed flowering "
                "(BBCH 60&ndash;69) due to structural changes in the canopy. This signature is "
                "absent in other crops, enabling crop-specific phenology detection. "
                "The BBCH ground truth allowed precise timing of this relationship."
            ),
        },
        "papers": [
            {
                "citation": (
                    "D'Andrimont, R., Taymans, M., Lemoine, G., Ceglar, A., Yordanov, M. "
                    "&amp; van der Velde, M. Detecting flowering phenology in oil seed rape "
                    "parcels with Sentinel-1 and -2 time series. <i>Computers and Electronics "
                    "in Agriculture</i> <b>193</b>, 106882 (2022)."
                ),
                "doi": "10.1016/j.compag.2022.106882",
                "open_access": True,
                "key_figures": [
                    {"id": "Fig. 1", "desc": "Study area &mdash; Flevoland polder with 259 field survey sites"},
                    {"id": "Fig. 2", "desc": "BBCH stage distribution across crop types and survey dates"},
                    {"id": "Fig. 5", "desc": "Sentinel-1 VH time series showing backscatter drop during rapeseed flowering"},
                    {"id": "Fig. 6", "desc": "Scatter plot: S1 VH change vs BBCH flowering stage (R&sup2; = 0.82)"},
                ],
            },
        ],
        "in_catalog": True,
    },
    {
        "id": "dwd",
        "title": "DWD Germany &mdash; Crop Phenology Observations",
        "category": "phenology-ground",
        "url": "https://opendata.dwd.de/climate_environment/CDC/observations_germany/phenology/",
        "description": (
            "Germany's national phenological observation network, operated by Deutscher "
            "Wetterdienst (DWD). ~1,200 volunteer observers record phenophase dates for "
            "crops, fruit trees, and wild plants. 70+ years of continuous observations."
        ),
        "spatial_extent": "Germany (nationwide, ~1,200 stations)",
        "spatial_resolution": "Station-level (individual observer locations)",
        "temporal_extent": "1951&ndash;present (70+ years)",
        "contents": (
            "Semicolon-delimited text files (latin-1 encoding) with station ID, year, "
            "crop object ID, phenophase ID, observation date (YYYYMMDD), and Julian day. "
            "Crops: winter wheat, winter rye, winter barley, spring barley, oats, maize, "
            "winter rapeseed, sugar beet, potato."
        ),
        "format": "TXT (semicolon-delimited, latin-1 encoding)",
        "license": "DL-DE/BY-2.0 (Datenlizenz Deutschland &mdash; Namensnennung &mdash; Version 2.0)",
        "license_url": "https://www.govdata.de/dl-de/by-2-0",
        "attribution": "Ph&auml;nologische Beobachtungen, Deutscher Wetterdienst, Offenbach",
        "validation": {
            "summary": (
                "Widely used as <b>ground truth for validating satellite phenology</b> across Europe. "
                "Internal QC includes consistency checks between observers and stations. "
                "Comparison with MODIS-derived SOS shows <b>RMSE = 10&ndash;15 days</b>; "
                "with Sentinel-2 HR-VPP: <b>RMSE = 7&ndash;12 days</b>. "
                "Observer-to-observer variability for the same phenophase is ~3&ndash;5 days."
            ),
            "metrics": [
                ("Observer consistency", "&plusmn;3&ndash;5 days (inter-observer)"),
                ("vs MODIS MCD12Q2 SOS RMSE", "10&ndash;15 days"),
                ("vs Copernicus HR-VPP SOS RMSE", "7&ndash;12 days"),
                ("Temporal coverage", "70+ years continuous"),
                ("Station density", "~1 per 300 km&sup2;"),
            ],
            "notes": (
                "Long-term trends detected: winter wheat sowing shifted 5&ndash;8 days later, "
                "harvest 10&ndash;15 days earlier over 1951&ndash;2020, consistent with warming "
                "and new cultivars. DWD data is the primary validation source for Copernicus HR-VPP "
                "and MODIS phenology products over Central Europe."
            ),
        },
        "papers": [
            {
                "citation": (
                    "Kaspar, F. et al. Monitoring of climate change in Germany &mdash; data, "
                    "products and services of Germany's National Climate Data Centre. "
                    "<i>Advances in Science and Research</i> <b>11</b>, 99&ndash;106 (2014)."
                ),
                "doi": "10.5194/asr-11-99-2014",
                "open_access": True,
            },
        ],
        "download_url": "https://opendata.dwd.de/climate_environment/CDC/observations_germany/phenology/annual_reporters/crops/recent/",
        "in_catalog": True,
    },
    {
        "id": "pep725",
        "title": "PEP725 &mdash; Pan European Phenological Database",
        "category": "phenology-ground",
        "url": "http://pep725.eu/",
        "description": (
            "The largest European phenology database with 13M+ records from 46 countries. "
            "Covers 265 plant species including major crops (wheat, maize, potato, sugar beet). "
            "All observations use standardised BBCH coding."
        ),
        "spatial_extent": "Europe (46 countries, 19,000+ stations)",
        "spatial_resolution": "Station-level",
        "temporal_extent": "1868&ndash;present (150+ years)",
        "contents": (
            "CSV downloads (after registration) with station ID, species, BBCH phase, "
            "observation date, coordinates."
        ),
        "format": "CSV",
        "license": "Free (registration required at pep725.eu)",
        "validation": {
            "summary": (
                "Used as <b>primary validation dataset for European phenology studies</b>. "
                "Internal QC flags outliers using 3&sigma; and spatial consistency checks. "
                "Extensively used to validate MODIS, AVHRR, and Sentinel-2 phenology products. "
                "Typical satellite vs PEP725 RMSE: 8&ndash;18 days for SOS depending on crop and method."
            ),
            "metrics": [
                ("Records", "13M+ observations"),
                ("Species", "265 (incl. major crops)"),
                ("vs MODIS SOS RMSE (crops)", "10&ndash;18 days"),
                ("vs AVHRR SOS RMSE", "12&ndash;20 days"),
                ("Temporal trends (spring advance)", "2&ndash;5 days/decade"),
            ],
        },
        "papers": [
            {
                "citation": (
                    "Templ, B. et al. PEP725: a pan European phenological database for "
                    "bio-meteorological applications. <i>International Journal of Biometeorology</i> "
                    "(2018)."
                ),
                "doi": "10.1007/s00484-018-1512-8",
            },
        ],
        "download_url": "http://pep725.eu/data_download/registration.php",
    },
    {
        "id": "phenocam",
        "title": "PhenoCam v3.0 &mdash; Camera-derived Vegetation Phenology",
        "category": "phenology-ground",
        "url": "https://doi.org/10.3334/ORNLDAAC/2389",
        "description": (
            "Automated digital camera network capturing canopy images every 30 minutes at "
            "738 sites. Green Chromatic Coordinate (GCC) time series derived from RGB images "
            "track vegetation greenup, maturity, senescence, and dormancy. Agricultural and "
            "grassland sites provide continuous crop phenology monitoring."
        ),
        "spatial_extent": "North America + global (738 sites)",
        "spatial_resolution": "Camera field-of-view (regions of interest within images)",
        "temporal_extent": "2000&ndash;2023",
        "contents": (
            "CSV time series per site with daily and 3-day GCC summaries (mean, 50th/75th/90th "
            "percentiles), and derived phenological transition dates using multiple methods. "
            "Sites classified by vegetation type: AG (agriculture), GR (grassland), etc."
        ),
        "format": "CSV (GCC time series + transition dates)",
        "license": "Open (EOSDIS data use policy)",
        "validation": {
            "summary": (
                "Extensively validated as a <b>near-surface reference for satellite phenology</b>. "
                "GCC transition dates correlate with MODIS EVI2 phenology at <b>R&sup2; = 0.73&ndash;0.85</b> "
                "across biomes. For agricultural sites, GCC greenup matches field-observed emergence "
                "within <b>&plusmn;5&ndash;7 days</b>. Camera-to-camera reproducibility is &plusmn;2&ndash;3 days."
            ),
            "metrics": [
                ("GCC vs MODIS EVI2 SOS R&sup2;", "0.73&ndash;0.85"),
                ("GCC vs field emergence", "&plusmn;5&ndash;7 days"),
                ("Camera reproducibility", "&plusmn;2&ndash;3 days"),
                ("Temporal resolution", "30-minute images &rarr; daily GCC"),
                ("AG + GR sites", "~80 of 738 total"),
            ],
            "notes": (
                "PhenoCam GCC is now the standard near-surface reference for validating "
                "satellite phenology (MODIS MCD12Q2, Landsat/HLS, Sentinel-2 HR-VPP). "
                "For agricultural sites, multiple growing cycles within a year "
                "(e.g. double-cropping) are captured that single-overpass satellites miss."
            ),
        },
        "papers": [
            {
                "citation": (
                    "Seyednasrollah, B. et al. PhenoCam Dataset v3.0: Digital camera "
                    "imagery from the PhenoCam Network. <i>ORNL DAAC</i> (2023)."
                ),
                "doi": "10.3334/ORNLDAAC/2389",
            },
            {
                "citation": (
                    "Richardson, A.D. et al. Tracking vegetation phenology across diverse "
                    "North American biomes using PhenoCam imagery. <i>Scientific Data</i> <b>5</b>, "
                    "180028 (2018)."
                ),
                "doi": "10.1038/sdata.2018.28",
                "open_access": True,
                "key_figures": [
                    {"id": "Fig. 1", "desc": "PhenoCam network site locations across North America by vegetation type"},
                    {"id": "Fig. 2", "desc": "Example GCC time series with phenological transition dates and uncertainty"},
                    {"id": "Fig. 4", "desc": "Validation: camera-derived vs MODIS-derived SOS/EOS (R&sup2; = 0.73&ndash;0.85)"},
                ],
            },
        ],
        "download_url": "https://doi.org/10.3334/ORNLDAAC/2389",
        "in_catalog": True,
    },
    {
        "id": "usa_npn",
        "title": "USA-NPN &mdash; National Phenology Network",
        "category": "phenology-ground",
        "url": "https://www.usanpn.org/data/observational",
        "description": (
            "Citizen science phenology monitoring network across the USA. Volunteers record "
            "phenophase status (yes/no/uncertain) for 1,000+ plant species including crops."
        ),
        "spatial_extent": "USA (nationwide)",
        "spatial_resolution": "Point observations (volunteer sites)",
        "temporal_extent": "2009&ndash;present",
        "contents": (
            "JSON/CSV via API with species, phenophase, observation date, status intensity, "
            "site coordinates."
        ),
        "format": "JSON / CSV (REST API)",
        "license": "CC0 (public domain)",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "validation": {
            "summary": (
                "Used to validate the USGS Extended Spring Indices (SI-x) model. "
                "Citizen science observations correlate with MODIS phenology at "
                "<b>R&sup2; = 0.6&ndash;0.7</b> for leaf-out dates. Data quality ensured by "
                "training protocols and automated outlier flagging."
            ),
            "metrics": [
                ("vs MODIS SOS R&sup2;", "0.6&ndash;0.7 (leaf-out)"),
                ("Observer training", "Online certification required"),
                ("Active observers", "~15,000"),
            ],
        },
        "papers": [
            {
                "citation": (
                    "Schwartz, M.D. et al. Spring onset variations and trends in the "
                    "continental United States. <i>International Journal of Climatology</i> "
                    "<b>33</b>(13), 2917&ndash;2922 (2013)."
                ),
                "doi": "10.1002/joc.3625",
            },
        ],
        "download_url": "https://www.usanpn.org/data/observational",
    },
    {
        "id": "china_maize",
        "title": "NE China Maize Phenology (1981&ndash;2024)",
        "category": "phenology-ground",
        "url": "https://doi.org/10.57760/sciencedb.28709",
        "description": (
            "Long-term maize phenology observations from 61 agrometeorological stations "
            "across Northeast China (Heilongjiang, Jilin, Liaoning). Ten BBCH-mapped "
            "phenological stages tracked over 43 years with rigorous QC."
        ),
        "spatial_extent": "NE China &mdash; Heilongjiang, Jilin, Liaoning provinces (61 stations)",
        "spatial_resolution": "Station-level (agrometeorological observation stations)",
        "temporal_extent": "1981&ndash;2024 (43 years)",
        "contents": (
            "2 XLSX data tables: (1) phenophase DOY with linear trend parameters (intercept, "
            "slope, p-value, R&sup2;) per station per phase; (2) growth period durations. "
            "976 diagnostic JPEG plots showing DOY trends per station. Station coordinates CSV."
        ),
        "format": "XLSX + JPEG diagnostic plots + PDF paper",
        "license": "CC BY-NC-ND 4.0",
        "license_url": "https://creativecommons.org/licenses/by-nc-nd/4.0/",
        "validation": {
            "summary": (
                "QC protocol: 3&sigma; outlier removal per station per phase, temporal continuity "
                "checks, and cross-station spatial consistency. <b>Data completeness: 89%</b> "
                "(stations &times; years &times; phases). Linear trend fits have "
                "<b>median R&sup2; = 0.3&ndash;0.6</b> (phenology trends are noisy but significant). "
                "Cross-validated against MODIS-derived phenology and ChinaCropPhen1km."
            ),
            "metrics": [
                ("Data completeness", "89% (station &times; year &times; phase)"),
                ("QC method", "3&sigma; outlier removal + continuity check"),
                ("Trend R&sup2; (median)", "0.3&ndash;0.6"),
                ("vs MODIS SOS RMSE", "8&ndash;12 days"),
                ("Sowing trend (1981&ndash;2024)", "2&ndash;5 days earlier per decade"),
                ("Maturity trend", "3&ndash;7 days later per decade"),
            ],
            "notes": (
                "Key climate signal: growing season lengthened by 10&ndash;20 days over 43 years "
                "due to earlier sowing and later maturity, consistent with warming trends "
                "in NE China (+0.3&deg;C/decade). Southern stations show stronger trends than northern."
            ),
        },
        "papers": [
            {
                "citation": (
                    "Zhang, Q.-J., Wu, D.-L., Zhu, Y.-C., Liu, C. &amp; Yang, D.-S. "
                    "A long-term dataset of maize phenology observations from "
                    "agrometeorological stations in Northeast China (1981&ndash;2024). "
                    "<i>Scientific Data</i> <b>12</b>, 2037 (2025)."
                ),
                "doi": "10.1038/s41597-025-06330-9",
                "open_access": True,
                "key_figures": [
                    {"id": "Fig. 1", "desc": "Location of 61 agrometeorological stations across NE China's three provinces"},
                    {"id": "Fig. 2", "desc": "Data completeness matrix (station &times; year) &mdash; 89% complete"},
                    {"id": "Fig. 3", "desc": "Example DOY trend plots showing sowing shifted earlier, maturity later"},
                    {"id": "Fig. 5", "desc": "Spatial patterns of phenological trends: growing season lengthening"},
                ],
            },
        ],
        "download_url": "https://doi.org/10.57760/sciencedb.28709",
        "in_catalog": True,
    },
    {
        "id": "senseco",
        "title": "SenSeCo In-situ Crop Phenology (Bulgaria &amp; France)",
        "category": "phenology-ground",
        "url": "https://zenodo.org/records/8067432",
        "description": (
            "Field-level crop phenology measurements from the SenSeCo COST Action. "
            "17 production fields in Bulgaria and 2 research fields in France with BBCH-coded "
            "observations for winter rapeseed and winter wheat over 2&ndash;3 growing seasons."
        ),
        "spatial_extent": "Bulgaria (Dobrich region) + France (INRAE Grignon)",
        "spatial_resolution": "Field-level (georeferenced field boundaries)",
        "temporal_extent": "2018&ndash;2020 (2&ndash;3 growing seasons)",
        "contents": (
            "Text/CSV files with field ID, coordinates, crop type, sowing date, harvest date, "
            "BBCH phenophase observations, and field boundary geometries."
        ),
        "format": "TXT / CSV",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "validation": {
            "summary": (
                "Designed as <b>benchmark ground truth for Sentinel-2 phenology methods</b>. "
                "Companion S2 dataset (Zenodo 7825727) provides matched reflectance time series. "
                "Studies using this data report S2-derived SOS within <b>&plusmn;7&ndash;10 days</b> "
                "of field-observed BBCH stages for winter rapeseed, and "
                "<b>&plusmn;5&ndash;8 days</b> for winter wheat heading."
            ),
            "metrics": [
                ("S2 vs field SOS (rapeseed)", "&plusmn;7&ndash;10 days"),
                ("S2 vs field heading (wheat)", "&plusmn;5&ndash;8 days"),
                ("Fields", "19 (17 BG + 2 FR)"),
                ("Seasons", "2&ndash;3 per field"),
            ],
        },
        "papers": [
            {
                "citation": (
                    "SenSeCo COST Action CA17134 &mdash; Optical synergies for spatiotemporal "
                    "SENsing of Scalable ECOphysiological traits."
                ),
                "doi": "10.5281/zenodo.8067432",
            },
        ],
        "download_url": "https://zenodo.org/records/8067432",
        "in_catalog": True,
    },
    {
        "id": "india_agroecosystem",
        "title": "Indian Agroecosystem Phenology &amp; Fluxes",
        "category": "phenology-ground",
        "url": "https://zenodo.org/records/15291023",
        "description": (
            "CLM5 (Community Land Model) outputs and observational data for major Indian "
            "crop agroecosystems. Includes LAI, yield, dry matter, and carbon flux data "
            "for rice, wheat, and maize systems."
        ),
        "spatial_extent": "India (major agroecosystems)",
        "spatial_resolution": "Model grid + observation sites",
        "temporal_extent": "Model output + observations (multi-year)",
        "contents": "CSV/NetCDF with LAI, yield, dry matter, carbon fluxes (GPP, NEE, Reco).",
        "format": "CSV / NetCDF",
        "license": "Open",
        "papers": [],
        "download_url": "https://zenodo.org/records/15291023",
    },
    {
        "id": "china_winter_wheat",
        "title": "China Winter Wheat Phenology (1981&ndash;2021)",
        "category": "phenology-ground",
        "url": "https://doi.org/10.1038/s41597-025-05368-z",
        "description": (
            "Station-based phenology observations for winter wheat across the Huang-Huai-Hai "
            "Plain &mdash; China's most important wheat-producing region (~60% of national output). "
            "Nine phenological stages from sowing to maturity tracked over 40 years."
        ),
        "spatial_extent": "Huang-Huai-Hai Plain, China",
        "spatial_resolution": "Station-level (agrometeorological stations)",
        "temporal_extent": "1981&ndash;2021 (40 years)",
        "contents": (
            "XLSX/JPG with DOY observations for 9 stages: sowing, emergence, tillering, "
            "overwintering, green-up, jointing, heading, flowering, maturity."
        ),
        "format": "XLSX + JPG diagnostic plots",
        "license": "Open",
        "validation": {
            "summary": (
                "QC similar to the NE China Maize dataset: 3&sigma; outlier removal, "
                "inter-station consistency. <b>Data completeness &gt;85%</b>. "
                "Validated against ChinaCropPhen1km satellite product: "
                "<b>heading date RMSE = 6&ndash;9 days</b> across the HHH Plain."
            ),
            "metrics": [
                ("Data completeness", "&gt;85%"),
                ("vs ChinaCropPhen1km heading RMSE", "6&ndash;9 days"),
                ("Green-up trend", "3&ndash;6 days earlier per decade"),
                ("Heading trend", "2&ndash;4 days earlier per decade"),
            ],
        },
        "papers": [
            {
                "citation": (
                    "Zhang, X. et al. A long-term dataset of winter wheat phenology "
                    "observations in the Huang-Huai-Hai Plain (1981&ndash;2021). "
                    "<i>Scientific Data</i> (2025)."
                ),
                "doi": "10.1038/s41597-025-05368-z",
                "open_access": True,
                "key_figures": [
                    {"id": "Fig. 1", "desc": "Station locations across the Huang-Huai-Hai Plain (60% of China's wheat)"},
                    {"id": "Fig. 3", "desc": "Temporal trends: heading and maturity dates advancing 2&ndash;4 days/decade"},
                    {"id": "Fig. 4", "desc": "Spatial pattern of green-up date trends across the HHH Plain"},
                ],
            },
        ],
    },
    {
        "id": "sage_crop_calendars",
        "title": "SAGE Crop Calendars &mdash; Global Planting &amp; Harvest Dates",
        "category": "phenology-ground",
        "url": "https://sage.nelson.wisc.edu/data-and-models/datasets/crop-calendar-dataset/",
        "description": (
            "Global gridded planting and harvest dates for 19 major crops at 0.5&deg; resolution. "
            "Compiled from national agricultural statistics, FAO reports, and expert knowledge."
        ),
        "spatial_extent": "Global",
        "spatial_resolution": "0.5&deg; (~56 km)",
        "temporal_extent": "Climatological (representative period ~1990&ndash;2000)",
        "contents": (
            "NetCDF grids with planting date (DOY), harvest date (DOY), and growing days "
            "for 19 crops: wheat, maize, rice, barley, rye, millet, sorghum, soybean, "
            "sunflower, potato, cassava, sugar beet, sugarcane, rapeseed, groundnut, cotton, etc."
        ),
        "format": "NetCDF / ASCII grid",
        "license": "Open",
        "validation": {
            "summary": (
                "Validated against national agricultural statistics from ~150 countries and "
                "FAO crop calendar databases. <b>Mean absolute error ~15&ndash;20 days</b> for "
                "planting dates and ~20&ndash;25 days for harvest dates at 0.5&deg; resolution. "
                "This is the <b>most widely cited</b> global crop calendar dataset (880+ citations)."
            ),
            "metrics": [
                ("Planting date MAE", "~15&ndash;20 days"),
                ("Harvest date MAE", "~20&ndash;25 days"),
                ("Crops covered", "19"),
                ("Resolution", "0.5&deg; (~56 km)"),
            ],
            "notes": (
                "Represents climatological averages, not individual years. Accuracy is highest "
                "in data-rich regions (USA, Europe, China) and lowest in sub-Saharan Africa. "
                "Does not capture multi-cropping systems or year-to-year variability."
            ),
        },
        "papers": [
            {
                "citation": (
                    "Sacks, W.J., Deryng, D., Foley, J.A. &amp; Ramankutty, N. "
                    "Crop planting dates: an analysis of global patterns. "
                    "<i>Global Ecology and Biogeography</i> <b>19</b>(5), 607&ndash;620 (2010)."
                ),
                "doi": "10.1111/j.1466-8238.2010.00551.x",
                "key_figures": [
                    {"id": "Fig. 2", "desc": "Global planting date maps for wheat, maize, rice at 0.5&deg;"},
                    {"id": "Fig. 3", "desc": "Growing season length patterns &mdash; tropical bimodal vs temperate unimodal"},
                ],
            },
        ],
        "download_url": "https://sage.nelson.wisc.edu/data-and-models/datasets/crop-calendar-dataset/",
    },
    {
        "id": "geoglam_cm4ew",
        "title": "GEOGLAM CM4EW &mdash; Sub-national Crop Calendars",
        "category": "phenology-ground",
        "url": "https://cropmonitor.org/",
        "description": (
            "Sub-national crop calendars from the GEOGLAM Crop Monitor for Early Warning, "
            "covering 929 administrative regions worldwide. Six phenological phases per crop."
        ),
        "spatial_extent": "Global (929 sub-national regions)",
        "spatial_resolution": "Sub-national administrative units",
        "temporal_extent": "Current (regularly updated)",
        "contents": (
            "JSON/CSV with 6 phenological phases per crop per region: planting, vegetative, "
            "reproductive, harvest, end-of-season, out-of-season."
        ),
        "format": "JSON / CSV",
        "license": "Open",
        "papers": [],
        "download_url": "https://cropmonitor.org/",
    },
    {
        "id": "fao_crop_calendar",
        "title": "FAO Crop Calendar",
        "category": "phenology-ground",
        "url": "https://cropcalendar.apps.fao.org/",
        "description": (
            "FAO's global crop calendar for 400+ crops across 60+ countries. "
            "REST API for programmatic access in 6 languages."
        ),
        "spatial_extent": "Global (60+ countries)",
        "spatial_resolution": "Country / Agro-Ecological Zone",
        "temporal_extent": "Current reference",
        "contents": "JSON API with crop name, planting/harvest month ranges, AEZ classification.",
        "format": "JSON (REST API)",
        "license": "Open",
        "papers": [],
        "download_url": "https://cropcalendar.apps.fao.org/",
    },
    {
        "id": "icos",
        "title": "ICOS &mdash; European Ecosystem Phenology &amp; Fluxes",
        "category": "phenology-ground",
        "url": "https://www.icos-cp.eu/data-products",
        "description": (
            "Eddy covariance fluxes and digital camera phenology from 80+ stations across "
            "12 European countries. Includes cropland ecosystem stations."
        ),
        "spatial_extent": "Europe (80+ stations, 12 countries)",
        "spatial_resolution": "Station-level (eddy covariance footprint ~1 km&sup2;)",
        "temporal_extent": "2018&ndash;present",
        "contents": (
            "CSV/NetCDF with half-hourly flux measurements (CO&sub2;, H&sub2;O, energy), "
            "meteorological variables, and camera-derived vegetation indices."
        ),
        "format": "CSV / NetCDF",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "validation": {
            "summary": (
                "ICOS flux data undergoes <b>three-level quality control</b> (raw, near-real-time, "
                "final) with standardised processing. Camera-derived GCC phenology validated "
                "against co-located flux-derived GPP phenology: <b>SOS agreement &plusmn;5 days</b>."
            ),
            "metrics": [
                ("QC levels", "3 (raw, NRT, final quality)"),
                ("Camera vs GPP SOS", "&plusmn;5 days"),
                ("Cropland stations", "~15 of 80+"),
            ],
        },
        "papers": [],
        "download_url": "https://www.icos-cp.eu/data-products",
    },

    # ===================== PHENOLOGY (SATELLITE) =====================
    {
        "id": "modis_mcd12q2",
        "title": "MODIS MCD12Q2 v6.1 &mdash; Global Land Surface Phenology",
        "category": "phenology-satellite",
        "url": "https://lpdaac.usgs.gov/products/mcd12q2v061/",
        "description": (
            "Global yearly land surface phenology from MODIS EVI2 at 500 m. "
            "Derives SOS, maturity, senescence, and EOS using amplitude thresholds. "
            "Supports up to 2 growing cycles per year."
        ),
        "spatial_extent": "Global",
        "spatial_resolution": "500 m (sinusoidal grid)",
        "temporal_extent": "2001&ndash;present (annual)",
        "contents": (
            "HDF5/GeoTIFF layers: Greenup (SOS), MidGreenup, Peak, MidGreendown, "
            "Dormancy (EOS), EVI min/amplitude/area, QA, NumCycles. "
            "Available on GEE as <code>MODIS/061/MCD12Q2</code>."
        ),
        "format": "HDF5 / GeoTIFF (500 m, annual)",
        "license": "Open (NASA EOSDIS)",
        "validation": {
            "summary": (
                "Validated against <b>PhenoCam GCC</b> at 78 sites and <b>PEP725</b> station data. "
                "For cropland: SOS <b>RMSE = 12&ndash;18 days</b>, EOS <b>RMSE = 15&ndash;22 days</b>. "
                "For deciduous forest (best performance): SOS RMSE = 8&ndash;12 days. "
                "Known issues: mixed pixels at 500 m cause bias in fragmented agricultural landscapes; "
                "double-cropping detection works in ~70% of actual multi-crop pixels."
            ),
            "metrics": [
                ("vs PhenoCam SOS RMSE (cropland)", "12&ndash;18 days"),
                ("vs PhenoCam EOS RMSE (cropland)", "15&ndash;22 days"),
                ("vs PhenoCam SOS RMSE (forest)", "8&ndash;12 days"),
                ("vs PEP725 SOS RMSE", "10&ndash;18 days"),
                ("Double-crop detection rate", "~70%"),
                ("Spatial resolution", "500 m (mixed pixel effects)"),
            ],
            "confusion": (
                "Main error sources: (1) 500 m mixed pixels containing multiple land covers, "
                "(2) cloud contamination advancing apparent EOS, (3) irrigated cropland appearing "
                "green longer than MODIS captures, (4) snow/ice triggering false SOS in early spring."
            ),
        },
        "papers": [
            {
                "citation": (
                    "Friedl, M., Gray, J. &amp; Sulla-Menashe, D. "
                    "MCD12Q2 MODIS/Terra+Aqua Land Cover Dynamics Yearly L3 Global 500m "
                    "SIN Grid V061. <i>NASA EOSDIS LP DAAC</i> (2022)."
                ),
                "doi": "10.5067/MODIS/MCD12Q2.061",
            },
        ],
        "download_url": "https://lpdaac.usgs.gov/products/mcd12q2v061/",
    },
    {
        "id": "hp_lsp",
        "title": "HP-LSP &mdash; HLS + PhenoCam Land Surface Phenology",
        "category": "phenology-satellite",
        "url": "https://doi.org/10.3334/ORNLDAAC/2248",
        "description": (
            "High-resolution (30 m) land surface phenology from fused HLS data, "
            "calibrated against PhenoCam GCC. 3-day gap-free EVI2 and 4 transition dates."
        ),
        "spatial_extent": "North America (78 regions, each 10&times;10 km around PhenoCam sites)",
        "spatial_resolution": "30 m",
        "temporal_extent": "2019&ndash;2020",
        "contents": (
            "Cloud-Optimised GeoTIFF (COG) files with 3-day gap-free EVI2 composites and "
            "4 phenological transition dates per pixel."
        ),
        "format": "COG (30 m, 3-day composites)",
        "license": "Open (EOSDIS)",
        "validation": {
            "summary": (
                "Directly calibrated against PhenoCam GCC. Achieves <b>&le;5 day accuracy</b> "
                "for all 4 transition dates (greenup, maturity, senescence, dormancy) at 30 m. "
                "Significant improvement over MODIS 500 m phenology in fragmented landscapes. "
                "For cropland sites: <b>SOS R&sup2; = 0.88, RMSE = 4.2 days</b>."
            ),
            "metrics": [
                ("SOS R&sup2; vs PhenoCam", "0.85&ndash;0.92 (all biomes)"),
                ("SOS RMSE (cropland)", "4.2 days"),
                ("SOS RMSE (all biomes)", "&le;5 days"),
                ("EOS RMSE", "5.1 days"),
                ("Spatial resolution", "30 m (vs 500 m MODIS)"),
                ("Temporal compositing", "3-day gap-free"),
            ],
            "notes": (
                "Key advance: the 30 m resolution resolves individual fields, eliminating "
                "the mixed-pixel problem that degrades MODIS phenology in agricultural areas. "
                "The gap-free 3-day composites also reduce the temporal aliasing that occurs "
                "with 5&ndash;16 day satellite revisit times."
            ),
        },
        "papers": [
            {
                "citation": (
                    "Tran, K.H. et al. A practical method for estimating gap-free daily "
                    "satellite vegetation indices and land surface phenology using HLS data "
                    "and PhenoCam imagery. <i>Scientific Data</i> <b>10</b>, 660 (2023)."
                ),
                "doi": "10.1038/s41597-023-02605-1",
                "open_access": True,
                "key_figures": [
                    {"id": "Fig. 1", "desc": "HP-LSP processing pipeline from HLS to gap-free EVI2 to phenology metrics"},
                    {"id": "Fig. 3", "desc": "Validation scatter: camera vs satellite phenology &mdash; R&sup2; = 0.85&ndash;0.92"},
                    {"id": "Fig. 5", "desc": "Example 30 m phenology maps showing field-level SOS variability"},
                    {"id": "Fig. 7", "desc": "Improvement over MODIS: RMSE reduction from 12 to 5 days at crop sites"},
                ],
            },
        ],
        "download_url": "https://doi.org/10.3334/ORNLDAAC/2248",
    },
    {
        "id": "gdpd",
        "title": "GDPD &mdash; Global Dryland Phenology Dataset",
        "category": "phenology-satellite",
        "url": "https://doi.org/10.1038/s41597-025-05519-2",
        "description": (
            "Global dryland phenology from MODIS NBAR EVI2 with dynamic amplitude thresholds "
            "adapted for low-biomass vegetation. Covers 88.4% of global drylands."
        ),
        "spatial_extent": "Global drylands (88.4% coverage)",
        "spatial_resolution": "500 m",
        "temporal_extent": "2001&ndash;2019",
        "contents": "GeoTIFF grids of SOS, EOS, season length, and growing season EVI2 integral.",
        "format": "GeoTIFF (500 m, annual)",
        "license": "Open",
        "validation": {
            "summary": (
                "Validated against PhenoCam GCC (dryland sites) and flux tower GPP. "
                "<b>SOS: r = 0.88 vs PhenoCam, r = 0.96 vs flux GPP</b>. "
                "Outperforms standard MCD12Q2 in drylands where low EVI2 amplitude "
                "causes standard methods to fail."
            ),
            "metrics": [
                ("SOS vs PhenoCam r", "0.88"),
                ("SOS vs flux GPP r", "0.96"),
                ("EOS vs PhenoCam r", "0.82"),
                ("vs MCD12Q2 improvement", "20&ndash;30% more valid pixels in drylands"),
            ],
        },
        "papers": [
            {
                "citation": (
                    "Global Dryland Phenology Dataset from MODIS NBAR EVI2. "
                    "<i>Scientific Data</i> (2025)."
                ),
                "doi": "10.1038/s41597-025-05519-2",
                "open_access": True,
            },
        ],
    },
    {
        "id": "avhrr_phenology",
        "title": "Global AVHRR Phenology (1982&ndash;2018)",
        "category": "phenology-satellite",
        "url": "https://figshare.com/articles/dataset/Annual_dynamic_dataset_of_global_land_surface_phenology_from_AVHRR_data_using_multiple_phenology_retrieval_methods_for_the_period_1982_to_2018/20375394",
        "description": (
            "36-year global phenology from AVHRR NDVI using 4 retrieval methods. "
            "Enables long-term trend analysis. Validated against USA-NPN, PEP725, and flux towers."
        ),
        "spatial_extent": "Global",
        "spatial_resolution": "~8 km (0.05&deg; AVHRR)",
        "temporal_extent": "1982&ndash;2018 (36 years)",
        "contents": "GeoTIFF grids of SOS, maturity, senescence, EOS per year per method.",
        "format": "GeoTIFF",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "validation": {
            "summary": (
                "Validated against PEP725 and USA-NPN ground observations. "
                "<b>SOS RMSE = 15&ndash;25 days</b> depending on method and biome. "
                "The 4 retrieval methods provide an uncertainty envelope: method spread "
                "is typically 10&ndash;20 days for SOS, representing methodological uncertainty."
            ),
            "metrics": [
                ("SOS RMSE vs PEP725", "15&ndash;25 days"),
                ("Method spread (uncertainty)", "10&ndash;20 days"),
                ("Record length", "36 years (longest satellite phenology)"),
            ],
        },
        "papers": [],
    },
    {
        "id": "chinacropphen1km",
        "title": "ChinaCropPhen1km &mdash; China Crop Phenology at 1 km",
        "category": "phenology-satellite",
        "url": "https://doi.org/10.6084/m9.figshare.8313530",
        "description": (
            "Crop phenology for three staple crops in China (maize, rice, wheat) at 1 km, "
            "derived from MODIS NDVI/EVI calibrated with agrometeorological stations."
        ),
        "spatial_extent": "China (national)",
        "spatial_resolution": "1 km",
        "temporal_extent": "2000&ndash;2015",
        "contents": (
            "GeoTIFF grids of SOS, heading, and maturity dates (DOY) for maize, rice "
            "(single/double/triple cropping), and wheat."
        ),
        "format": "GeoTIFF (1 km, annual)",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "validation": {
            "summary": (
                "Validated against <b>1,176 station-year observations</b> from CMA agrometeorological "
                "stations. Satellite-derived vs station phenology: <b>R&sup2; = 0.70&ndash;0.85</b>, "
                "<b>RMSE = 8&ndash;14 days</b> depending on crop and phase. "
                "Best performance for wheat heading (R&sup2; = 0.85, RMSE = 8 days); "
                "weakest for rice SOS in double-cropping regions (R&sup2; = 0.70, RMSE = 14 days)."
            ),
            "metrics": [
                ("Wheat heading R&sup2; / RMSE", "0.85 / 8 days"),
                ("Maize SOS R&sup2; / RMSE", "0.78 / 10 days"),
                ("Rice SOS R&sup2; / RMSE", "0.70&ndash;0.82 / 10&ndash;14 days"),
                ("Validation sample", "1,176 station-years"),
                ("Station network", "CMA agrometeorological stations"),
            ],
            "notes": (
                "Multi-cropping regions (double/triple rice in South China) show "
                "lower accuracy because MODIS 1 km pixels often contain mixed cropping "
                "systems. The dataset provides separate layers for single, double, and triple "
                "rice cropping systems."
            ),
        },
        "papers": [
            {
                "citation": (
                    "Luo, Y., Zhang, Z., Chen, Y., Li, Z. &amp; Tao, F. "
                    "ChinaCropPhen1km: a high-resolution crop phenological dataset for "
                    "three staple crops in China during 2000&ndash;2015 based on LAI products. "
                    "<i>Earth System Science Data</i> <b>12</b>, 197&ndash;214 (2020)."
                ),
                "doi": "10.5194/essd-12-197-2020",
                "open_access": True,
                "key_figures": [
                    {"id": "Fig. 1", "desc": "Crop distribution maps used as spatial masks for phenology extraction"},
                    {"id": "Fig. 4", "desc": "Validation scatter plots: satellite vs station phenology &mdash; R&sup2; = 0.70&ndash;0.85"},
                    {"id": "Fig. 5", "desc": "Spatial patterns of maize SOS across China &mdash; latitudinal gradient"},
                    {"id": "Fig. 7", "desc": "Interannual variability of wheat heading date at 1 km resolution"},
                ],
            },
        ],
        "download_url": "https://doi.org/10.6084/m9.figshare.8313530",
    },
    {
        "id": "china_maize_30m",
        "title": "China Maize Phenology 30 m (1985&ndash;2020)",
        "category": "phenology-satellite",
        "url": "https://essd.copernicus.org/articles/14/2851/2022/",
        "description": (
            "National maize phenology at 30 m from all available Landsat imagery "
            "processed on Google Earth Engine. The finest-resolution crop phenology "
            "dataset for a major producing country."
        ),
        "spatial_extent": "China (national maize areas)",
        "spatial_resolution": "30 m (Landsat)",
        "temporal_extent": "1985&ndash;2020 (35 years)",
        "contents": "GeoTIFF grids of maize SOS, heading, and maturity dates at 30 m.",
        "format": "GeoTIFF (30 m)",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "validation": {
            "summary": (
                "Validated against CMA station observations and ChinaCropPhen1km. "
                "<b>SOS RMSE = 8&ndash;11 days</b> vs stations, with the 30 m resolution "
                "capturing field-level variability that 1 km products miss. "
                "The long time series (35 years) enables phenological trend detection."
            ),
            "metrics": [
                ("SOS RMSE vs stations", "8&ndash;11 days"),
                ("vs ChinaCropPhen1km agreement", "R&sup2; = 0.82"),
                ("Resolution advantage", "30 m vs 500 m/1 km"),
                ("Record length", "35 years (1985&ndash;2020)"),
            ],
        },
        "papers": [
            {
                "citation": (
                    "Niu, Q., Li, X., Huang, J. et al. "
                    "A 30 m annual maize phenology dataset from 1985 to 2020 in China. "
                    "<i>Earth System Science Data</i> <b>14</b>, 2851&ndash;2864 (2022)."
                ),
                "doi": "10.5194/essd-14-2851-2022",
                "open_access": True,
                "key_figures": [
                    {"id": "Fig. 3", "desc": "Landsat-derived vs station phenology validation scatter plots"},
                    {"id": "Fig. 5", "desc": "30 m maize SOS maps at province scale showing field-level detail"},
                ],
            },
        ],
        "download_url": "https://doi.org/10.6084/m9.figshare.16437054",
    },
    {
        "id": "copernicus_hrvpp",
        "title": "Copernicus HR-VPP &mdash; European Sentinel-2 Phenology",
        "category": "phenology-satellite",
        "url": "https://land.copernicus.eu/en/products/vegetation/high-resolution-vegetation-phenology-and-productivity",
        "description": (
            "Pan-European high-resolution phenology from Sentinel-2 at 10 m. "
            "13 phenological metrics and dekadal VI time series for EEA-39 countries."
        ),
        "spatial_extent": "Europe (EEA-39 countries)",
        "spatial_resolution": "10 m",
        "temporal_extent": "2017&ndash;present (annual metrics, dekadal VI)",
        "contents": (
            "COG/WMS layers: SOS date/value, EOS date/value, max date/value, season length, "
            "base value, amplitude, SPROD, TPROD, PPI."
        ),
        "format": "COG / WMS (10 m, dekadal)",
        "license": "Open (Copernicus data policy)",
        "validation": {
            "summary": (
                "Validated against <b>DWD phenological observations</b> (Germany), "
                "<b>PEP725</b>, and <b>ICOS flux stations</b>. "
                "For cropland: SOS <b>RMSE = 7&ndash;12 days</b> vs DWD, improving on MODIS. "
                "The 10 m resolution resolves individual crop fields, critical in Europe's "
                "fragmented agricultural landscape where average field size is ~10 ha."
            ),
            "metrics": [
                ("SOS RMSE vs DWD (crops)", "7&ndash;12 days"),
                ("SOS RMSE vs PEP725", "8&ndash;15 days"),
                ("EOS RMSE vs DWD", "10&ndash;18 days"),
                ("Resolution", "10 m (individual fields)"),
                ("Temporal sampling", "Dekadal (every 10 days)"),
            ],
            "notes": (
                "Key advantage over MODIS: the 10 m resolution eliminates mixed-pixel "
                "effects in fragmented European agriculture. However, cloud cover in "
                "northern Europe limits dekadal composites and can delay SOS detection."
            ),
        },
        "papers": [],
        "download_url": "https://land.copernicus.eu/en/products/vegetation/high-resolution-vegetation-phenology-and-productivity",
    },
    {
        "id": "eviirs",
        "title": "USGS eVIIRS &mdash; USA Vegetation Phenology",
        "category": "phenology-satellite",
        "url": "https://www.usgs.gov/special-topics/monitoring-vegetation-drought-stress/science/eviirs-phenology",
        "description": (
            "Land surface phenology metrics for CONUS and Alaska from VIIRS (375 m)."
        ),
        "spatial_extent": "USA (CONUS + Alaska)",
        "spatial_resolution": "375 m",
        "temporal_extent": "2021&ndash;present",
        "contents": "GeoTIFF grids with annual phenology metrics from VIIRS NDVI.",
        "format": "GeoTIFF (375 m, annual)",
        "license": "Public domain (US Government)",
        "papers": [],
        "download_url": "https://www.usgs.gov/special-topics/monitoring-vegetation-drought-stress/science/eviirs-phenology",
    },
    {
        "id": "fao_asis",
        "title": "FAO ASIS Crop/Pasture Phenology",
        "category": "phenology-satellite",
        "url": "https://data.apps.fao.org/catalog/dataset/crop-pasture-phenology",
        "description": (
            "Global crop and pasture growing season parameters from long-term NDVI averages. "
            "Part of the Agricultural Stress Index System (ASIS) for drought monitoring."
        ),
        "spatial_extent": "Global",
        "spatial_resolution": "~1 km (MODIS/AVHRR NDVI)",
        "temporal_extent": "Ongoing (climatological + annual updates)",
        "contents": "Raster maps of SOS/MOS/EOS dates and growing season progress (dekadal).",
        "format": "Raster (dekadal)",
        "license": "Open",
        "papers": [],
        "download_url": "https://data.apps.fao.org/catalog/dataset/crop-pasture-phenology",
    },

    # ===================== CROP YIELD =====================
    {
        "id": "cy_bench",
        "title": "CY-Bench &mdash; Subnational Crop Yield Benchmark",
        "category": "yield",
        "url": "https://zenodo.org/records/17279151",
        "description": (
            "Standardised benchmark for crop yield forecasting ML. Subnational wheat "
            "(29 countries) and maize (38 countries) yields with weather, RS, and soil predictors."
        ),
        "spatial_extent": "Global (29 countries wheat, 38 maize, subnational)",
        "spatial_resolution": "Subnational administrative units",
        "temporal_extent": "Multi-decadal (varies by country)",
        "contents": (
            "CSV with yield statistics + predictor variables: ERA5 weather, MODIS NDVI, "
            "soil moisture, ET. Train/test splits and baseline model code."
        ),
        "format": "CSV",
        "license": "Open",
        "validation": {
            "summary": (
                "Provides standardised <b>baseline model comparisons</b>. "
                "Linear regression baseline: wheat <b>RMSE = 0.8&ndash;1.2 t/ha</b> "
                "(nRMSE 15&ndash;25%); maize <b>RMSE = 1.0&ndash;2.0 t/ha</b>. "
                "Gradient boosting improves to nRMSE 12&ndash;18%. "
                "The benchmark enables fair comparison across methods."
            ),
            "metrics": [
                ("Wheat baseline RMSE", "0.8&ndash;1.2 t/ha (nRMSE 15&ndash;25%)"),
                ("Maize baseline RMSE", "1.0&ndash;2.0 t/ha"),
                ("Best ML model nRMSE", "12&ndash;18%"),
            ],
        },
        "papers": [
            {
                "citation": (
                    "Paudel, D. et al. CY-Bench: a subnational crop yield benchmark "
                    "dataset for machine learning. <i>Earth System Science Data</i> (2025)."
                ),
                "doi": "10.5194/essd-2025-83",
                "open_access": True,
                "key_figures": [
                    {"id": "Fig. 1", "desc": "Spatial coverage of yield data by country and crop"},
                    {"id": "Fig. 3", "desc": "Baseline model performance comparison across methods and countries"},
                ],
            },
        ],
        "code_url": "https://github.com/WUR-AI/AgML-CY-Bench",
        "download_url": "https://doi.org/10.5281/zenodo.11502142",
    },
    {
        "id": "global_historical_yields",
        "title": "Global Historical Crop Yields (1981&ndash;2016)",
        "category": "yield",
        "url": "https://doi.org/10.6084/m9.figshare.11903277",
        "description": (
            "Gridded global historical yields for 4 major crops at 0.5&deg;. "
            "Combines FAO statistics with satellite-based crop calendars and weather data."
        ),
        "spatial_extent": "Global",
        "spatial_resolution": "0.5&deg; (~56 km)",
        "temporal_extent": "1981&ndash;2016 (35 years)",
        "contents": "NetCDF grids of annual yields (t/ha) for maize, rice, wheat, soybean.",
        "format": "NetCDF",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "validation": {
            "summary": (
                "Validated against FAO national statistics and USDA county-level data. "
                "<b>R&sup2; = 0.90&ndash;0.96</b> at national level for all 4 crops. "
                "Sub-national validation (USA county data): <b>R&sup2; = 0.75&ndash;0.85</b>."
            ),
            "metrics": [
                ("vs FAO national R&sup2;", "0.90&ndash;0.96"),
                ("vs USDA county R&sup2;", "0.75&ndash;0.85"),
            ],
        },
        "papers": [
            {
                "citation": (
                    "Iizumi, T. &amp; Sakai, T. The global dataset of historical yields "
                    "for major crops 1981&ndash;2016. <i>Scientific Data</i> <b>7</b>, 97 (2020)."
                ),
                "doi": "10.1038/s41597-020-0433-7",
                "open_access": True,
                "key_figures": [
                    {"id": "Fig. 1", "desc": "Global wheat yield patterns at 0.5&deg; resolution"},
                    {"id": "Fig. 3", "desc": "Yield trend analysis 1981&ndash;2016 with R&sup2; validation"},
                ],
            },
        ],
        "download_url": "https://doi.org/10.6084/m9.figshare.11903277",
    },
    {
        "id": "climate_yield_projections",
        "title": "Climate Change Impacts on Crop Yields (Projected)",
        "category": "yield",
        "url": "https://doi.org/10.6084/m9.figshare.17427674",
        "description": (
            "Projected crop yield changes under emission scenarios from AgMIP/ISIMIP "
            "ensemble of global crop models."
        ),
        "spatial_extent": "Global (91 countries)",
        "spatial_resolution": "Country-level aggregations",
        "temporal_extent": "21st century projections (SSP1-2.6 to SSP5-8.5)",
        "contents": "CSV/NetCDF with projected yield changes (%) by country, crop, scenario, decade.",
        "format": "CSV / NetCDF",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "papers": [
            {
                "citation": (
                    "J&auml;germeyr, J. et al. Climate impacts on global agriculture emerge "
                    "earlier in new generation of climate and crop models. "
                    "<i>Nature Food</i> <b>2</b>, 873&ndash;885 (2021)."
                ),
                "doi": "10.1038/s43016-021-00400-y",
                "key_figures": [
                    {"id": "Fig. 1", "desc": "Global map of projected yield changes by 2050 under SSP3-7.0"},
                ],
            },
        ],
        "download_url": "https://doi.org/10.6084/m9.figshare.17427674",
    },
    {
        "id": "china_wheat_yield_30m",
        "title": "ChinaWheatYield30m (2016&ndash;2021)",
        "category": "yield",
        "url": "https://zenodo.org/records/7360753",
        "description": (
            "30 m annual winter wheat yield maps for major producing provinces in China."
        ),
        "spatial_extent": "China (major wheat provinces)",
        "spatial_resolution": "30 m",
        "temporal_extent": "2016&ndash;2021",
        "contents": "GeoTIFF grids of estimated wheat yield (t/ha) at 30 m.",
        "format": "GeoTIFF (30 m, annual)",
        "license": "Open",
        "papers": [],
        "download_url": "https://zenodo.org/records/7360753",
    },
    {
        "id": "uk_crop_yield",
        "title": "UK Crop Yield Dataset",
        "category": "yield",
        "url": "https://doi.org/10.1038/s41597-025-06528-x",
        "description": (
            "UK crop yield dataset integrating satellite (Sentinel, MODIS), weather, "
            "and soil type information for multiple arable crops."
        ),
        "spatial_extent": "UK",
        "spatial_resolution": "Grid/county level",
        "temporal_extent": "Multi-year",
        "contents": "CSV with yield, satellite VIs, weather variables, soil properties.",
        "format": "CSV",
        "license": "Open",
        "papers": [
            {
                "citation": (
                    "UK crop yield dataset incorporating satellite, weather, and soil data. "
                    "<i>Scientific Data</i> (2025)."
                ),
                "doi": "10.1038/s41597-025-06528-x",
                "open_access": True,
            },
        ],
        "download_url": "https://doi.org/10.1038/s41597-025-06528-x",
    },
    {
        "id": "acea",
        "title": "ACEA &mdash; AquaCrop-Earth@lternatives Global Crop Model",
        "category": "yield",
        "url": "https://zenodo.org/records/10510934",
        "description": (
            "Global gridded AquaCrop model output estimating yield and ET, distinguishing "
            "green water, blue water from capillary rise, and irrigation."
        ),
        "spatial_extent": "Global",
        "spatial_resolution": "~0.5&deg;",
        "temporal_extent": "Historical + projected",
        "contents": "NetCDF with simulated yield, ET components, water stress indicators.",
        "format": "NetCDF",
        "license": "Open",
        "papers": [],
        "download_url": "https://zenodo.org/records/10510934",
    },

    # ===================== BENCHMARKS / ML-READY =====================
    {
        "id": "eurocropsml",
        "title": "EuroCropsML &mdash; Few-Shot Crop Type Classification Benchmark",
        "category": "benchmark",
        "url": "https://zenodo.org/records/10629610",
        "description": (
            "ML benchmark for few-shot crop type classification. 706K parcels with full-year "
            "Sentinel-2 L1C time series, 176 HCAT crop classes. PyTorch-ready."
        ),
        "spatial_extent": "Latvia, Portugal, Estonia",
        "spatial_resolution": "Parcel-level (per-parcel median S2 reflectance)",
        "temporal_extent": "2021",
        "contents": (
            "Parquet/CSV with 706K parcels &times; 365 timesteps &times; 13 bands. "
            "Train/test splits for few-shot experiments."
        ),
        "format": "Parquet / CSV (PyTorch-ready)",
        "license": "Open",
        "validation": {
            "summary": (
                "Provides <b>standardised few-shot classification benchmarks</b>. "
                "Full-shot baseline (all training data): <b>OA = 78&ndash;85%</b> (country-dependent). "
                "10-shot (10 samples/class): <b>OA = 45&ndash;55%</b>. "
                "Cross-country transfer (train Latvia &rarr; test Estonia): <b>OA drops 15&ndash;25%</b>, "
                "highlighting the domain adaptation challenge."
            ),
            "metrics": [
                ("Full-shot OA", "78&ndash;85% (country-dependent)"),
                ("10-shot OA", "45&ndash;55%"),
                ("Cross-country transfer drop", "15&ndash;25% OA reduction"),
                ("Parcels", "706K"),
                ("Crop classes", "176 (HCAT)"),
            ],
            "confusion": (
                "Main confusions: cereals group (wheat &harr; barley &harr; rye, 15&ndash;20% "
                "inter-confusion), legumes group (beans &harr; peas, 10&ndash;15%), and "
                "grassland subtypes. Country-specific confusion patterns differ due to "
                "varying crop mix and climate."
            ),
        },
        "papers": [
            {
                "citation": (
                    "Schneider, M. et al. EuroCropsML: A Time Series Benchmark Dataset "
                    "for Few-Shot Crop Type Classification. "
                    "<i>Scientific Data</i> (2025)."
                ),
                "doi": "10.1038/s41597-025-04952-7",
                "open_access": True,
                "key_figures": [
                    {"id": "Fig. 1", "desc": "Parcel distribution across Latvia, Portugal, Estonia with class frequencies"},
                    {"id": "Fig. 3", "desc": "Example Sentinel-2 temporal profiles by crop type"},
                    {"id": "Fig. 5", "desc": "Few-shot learning curves: accuracy vs number of training samples"},
                    {"id": "Fig. 6", "desc": "Cross-country transfer confusion matrices"},
                ],
            },
        ],
        "download_url": "https://zenodo.org/records/10629610",
        "in_catalog": True,
    },
    {
        "id": "cropharvest",
        "title": "CropHarvest &mdash; Global Crop Type Classification Benchmark",
        "category": "benchmark",
        "url": "https://zenodo.org/records/5533193",
        "description": (
            "95K geo-diverse crop/non-crop samples from 21 source datasets worldwide. "
            "Includes S1, S2, SRTM, ERA5 features. Binary and multiclass tasks."
        ),
        "spatial_extent": "Global (from 21 source datasets across all continents)",
        "spatial_resolution": "Point samples with multi-sensor features",
        "temporal_extent": "Multi-year (varies by source)",
        "contents": (
            "95K datapoints (33K multiclass) with S1, S2, SRTM, ERA5 features. "
            "Python API and PyTorch DataLoader."
        ),
        "format": "Custom format (Python API)",
        "license": "CC BY-SA 4.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "validation": {
            "summary": (
                "Provides <b>benchmark results for crop/non-crop binary classification</b> "
                "and multiclass crop type identification. Binary: random forest baseline "
                "<b>F1 = 0.81</b>; LSTM <b>F1 = 0.86</b>. Multiclass (33K samples, 9 classes): "
                "random forest <b>OA = 63%</b>; best models reach ~72%. "
                "Performance varies dramatically by geography: Sub-Saharan Africa is hardest."
            ),
            "metrics": [
                ("Binary crop/non-crop F1 (RF)", "0.81"),
                ("Binary crop/non-crop F1 (LSTM)", "0.86"),
                ("Multiclass OA (RF)", "63%"),
                ("Multiclass OA (best)", "~72%"),
                ("Geographic transfer penalty", "10&ndash;30% F1 drop"),
            ],
            "confusion": (
                "Binary task: main errors are smallholder cropland in Africa classified as "
                "non-crop (field sizes &lt;0.5 ha), and grassland classified as crop in "
                "pastoral regions. Multiclass: maize &harr; sorghum and wheat &harr; barley "
                "are the most confused pairs."
            ),
        },
        "papers": [
            {
                "citation": (
                    "Tseng, G., Zvonkov, I., Nakalembe, C. &amp; Kerner, H. "
                    "CropHarvest: a global dataset for crop-type classification. "
                    "<i>NeurIPS Datasets and Benchmarks</i> (2021)."
                ),
                "doi": None,
                "url": "https://datasets-benchmarks-proceedings.neurips.cc/paper/2021/hash/54229abfcfa5649e7003b83dd4755294-Abstract-round2.html",
                "key_figures": [
                    {"id": "Fig. 1", "desc": "Global distribution of CropHarvest samples by source dataset"},
                    {"id": "Fig. 3", "desc": "Per-region F1 scores: 0.90+ in USA/EU, 0.55&ndash;0.70 in Africa"},
                    {"id": "Table 2", "desc": "Benchmark results: RF, LSTM, and transformer baselines"},
                ],
            },
        ],
        "code_url": "https://github.com/nasaharvest/cropharvest",
        "download_url": "https://zenodo.org/records/5533193",
    },
    {
        "id": "dacia5",
        "title": "DACIA5 &mdash; Sentinel-1/2 Crop ID Benchmark (Romania)",
        "category": "benchmark",
        "url": "https://www.tandfonline.com/doi/full/10.1080/20964471.2025.2512685",
        "description": (
            "6,454 image patches from Sentinel-2 multispectral and Sentinel-1 radar "
            "with in-situ verified crop type labels near Bra&#537;ov, Romania."
        ),
        "spatial_extent": "Romania (Bra&#537;ov region)",
        "spatial_resolution": "10 m (S2) / 20 m (S1)",
        "temporal_extent": "2020&ndash;2024",
        "contents": "GeoTIFF patches with crop type labels from field verification.",
        "format": "GeoTIFF patches (6,454 images)",
        "license": "Open",
        "validation": {
            "summary": (
                "Benchmark classification results using S2-only, S1-only, and S1+S2 fusion. "
                "<b>S2-only OA = 82%</b>, <b>S1+S2 fusion OA = 87%</b>. "
                "S1 radar adds most value for winter crops and during cloudy periods."
            ),
            "metrics": [
                ("S2-only OA", "82%"),
                ("S1-only OA", "71%"),
                ("S1+S2 fusion OA", "87%"),
            ],
        },
        "papers": [
            {
                "citation": (
                    "DACIA5: a Sentinel-1 and Sentinel-2 benchmark dataset for crop "
                    "identification. <i>Big Earth Data</i> (2025)."
                ),
                "doi": "10.1080/20964471.2025.2512685",
                "open_access": True,
            },
        ],
    },
    {
        "id": "africa_crop_noncrop",
        "title": "Hand-Labelled Crop/Non-Crop (Africa)",
        "category": "benchmark",
        "url": "https://zenodo.org/records/4680394",
        "description": (
            "Hand-labelled crop/non-crop reference data for four African countries."
        ),
        "spatial_extent": "Ethiopia, Sudan, Togo, Kenya",
        "spatial_resolution": "Point samples",
        "temporal_extent": "Various",
        "contents": "GeoJSON/CSV with binary crop/non-crop labels and coordinates.",
        "format": "GeoJSON / CSV",
        "license": "Open",
        "validation": {
            "summary": (
                "Used to train and validate binary cropland classifiers in data-sparse regions. "
                "Baseline random forest: <b>crop/non-crop F1 = 0.72&ndash;0.85</b> depending "
                "on country (highest in Kenya, lowest in Togo)."
            ),
            "metrics": [
                ("Binary F1 (Kenya)", "~0.85"),
                ("Binary F1 (Togo)", "~0.72"),
            ],
        },
        "papers": [],
        "download_url": "https://zenodo.org/records/4680394",
    },
    {
        "id": "senseco_s2",
        "title": "SenSeCo S2 Phenology Metrics (Bulgaria &amp; France)",
        "category": "benchmark",
        "url": "https://zenodo.org/records/7825727",
        "description": (
            "Sentinel-2 time series for SenSeCo in-situ phenology sites. "
            "Paired with ground truth (Zenodo 8067432) as a phenology benchmark."
        ),
        "spatial_extent": "Bulgaria + France (same sites as SenSeCo in-situ)",
        "spatial_resolution": "10&ndash;20 m (Sentinel-2 pixels)",
        "temporal_extent": "2018&ndash;2020",
        "contents": "GeoTIFF/CSV with Sentinel-2 reflectance and derived VIs for validation fields.",
        "format": "GeoTIFF / CSV",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "validation": {
            "summary": (
                "Enables direct <b>pixel-to-field comparison</b> between S2 reflectance-derived "
                "phenology and in-situ BBCH observations. Published results show "
                "<b>SOS RMSE = 7&ndash;10 days</b> for winter crops using double-logistic fits."
            ),
            "metrics": [
                ("SOS RMSE (double-logistic)", "7&ndash;10 days"),
                ("Matched S2 + ground truth fields", "19"),
            ],
        },
        "papers": [],
        "download_url": "https://zenodo.org/records/7825727",
    },
]

# Category display names and CSS classes
CATEGORIES = {
    "crop-type": {"name": "Crop Type / Land Use Classification", "css": "crop-type"},
    "phenology-ground": {"name": "Phenology (Ground Truth / In-situ)", "css": "phenology"},
    "phenology-satellite": {"name": "Phenology (Satellite-derived)", "css": "satellite"},
    "yield": {"name": "Crop Yield", "css": "yield"},
    "benchmark": {"name": "Benchmarks / ML-ready Datasets", "css": "benchmark"},
}

# ---------------------------------------------------------------------------
# Standardised validation statistics per dataset
#
# Fields:
#   n_val       - number of validation samples / points / station-years
#   n_classes   - number of classes (crop type datasets)
#   method      - validation method (independent, LOO, k-fold, etc.)
#   oa          - overall accuracy (%) or None
#   f1          - F1 score (0-1) or None
#   kappa       - Cohen's kappa or None
#   rmse        - RMSE in days (phenology) or None
#   r2          - R-squared or None
#   bias        - bias in days (phenology) or None
#   region      - geographic scope of validation
# ---------------------------------------------------------------------------

VALIDATION_STATS = {
    # ---- Crop Type ----
    "kenya_helmets":       {"n_val": "12,299 points",   "n_classes": 10,  "method": "DL pipeline + manual QC",                "oa": None,  "f1": 0.83, "kappa": None, "rmse": None, "r2": None, "bias": None, "region": "Kenya (16 counties)"},
    "cropsight_us":        {"n_val": "124,000 fields",  "n_classes": 17,  "method": "Independent comparison vs CDL",           "oa": 97.2,  "f1": None, "kappa": None, "rmse": None, "r2": None, "bias": None, "region": "USA (CONUS)"},
    "eurocrops":           {"n_val": "500+ samples",    "n_classes": None,"method": "Expert review of HCAT mappings",          "oa": None,  "f1": None, "kappa": None, "rmse": None, "r2": None, "bias": None, "region": "EU (5 countries)"},
    "germany_crop_maps":   {"n_val": "IACS parcels",    "n_classes": 12,  "method": "Independent holdout (IACS declarations)", "oa": 85,    "f1": None, "kappa": None, "rmse": None, "r2": None, "bias": None, "region": "Germany"},
    "france_kenya_domain": {"n_val": "~10,000 points",  "n_classes": 8,   "method": "Independent test split per region",       "oa": 88,    "f1": None, "kappa": None, "rmse": None, "r2": None, "bias": None, "region": "France + Kenya"},
    "cropgrids":           {"n_val": "~150 countries",   "n_classes": 173, "method": "Independent comparison vs FAO/census",    "oa": None,  "f1": None, "kappa": None, "rmse": None, "r2": 0.95, "bias": None, "region": "Global"},
    "crome":               {"n_val": "RPA inspections",  "n_classes": 80,  "method": "Independent comparison vs field inspection","oa": 85,  "f1": None, "kappa": None, "rmse": None, "r2": None, "bias": None, "region": "England"},
    "usda_cdl":            {"n_val": "FSA CLU pixels",   "n_classes": 254, "method": "Independent holdout (FSA ground truth)",  "oa": 92,    "f1": None, "kappa": 0.90, "rmse": None, "r2": None, "bias": None, "region": "USA (CONUS)"},
    # ---- Phenology Ground Truth ----
    "flevovision":         {"n_val": "259 sites &times; 3&ndash;8 visits","n_classes": 9, "method": "Direct field observation (BBCH)",  "oa": None, "f1": None, "kappa": None, "rmse": 5, "r2": 0.82, "bias": None, "region": "Netherlands (Flevoland)"},
    "dwd":                 {"n_val": "~1,200 stations &times; 70 yr",    "n_classes": 9, "method": "Volunteer observer network",       "oa": None, "f1": None, "kappa": None, "rmse": None, "r2": None, "bias": None, "region": "Germany"},
    "pep725":              {"n_val": "13M+ records",     "n_classes": None,"method": "Observer network + 3&sigma; QC",          "oa": None, "f1": None, "kappa": None, "rmse": None, "r2": None, "bias": None, "region": "Europe (46 countries)"},
    "phenocam":            {"n_val": "738 sites (~80 AG/GR)","n_classes": None,"method": "Automated camera (30-min interval)",  "oa": None, "f1": None, "kappa": None, "rmse": None, "r2": None, "bias": None, "region": "N. America + global"},
    "china_maize":         {"n_val": "61 stations &times; 43 yr &times; 10 phases","n_classes": None,"method": "Station observation + 3&sigma; QC","oa": None,"f1": None,"kappa": None,"rmse": None,"r2": None,"bias": None,"region": "NE China"},
    "senseco":             {"n_val": "19 fields &times; 2&ndash;3 seasons","n_classes": 2, "method": "Direct field observation (BBCH)","oa": None,"f1": None,"kappa": None,"rmse": None,"r2": None,"bias": None,"region": "Bulgaria + France"},
    "usa_npn":             {"n_val": "~15,000 observers","n_classes": None,"method": "Citizen science + training protocol",    "oa": None, "f1": None, "kappa": None, "rmse": None, "r2": 0.65, "bias": None, "region": "USA"},
    "china_winter_wheat":  {"n_val": "stations &times; 40 yr &times; 9 phases","n_classes": None,"method": "Station observation + 3&sigma; QC","oa": None,"f1": None,"kappa": None,"rmse": None,"r2": None,"bias": None,"region": "HHH Plain, China"},
    "sage_crop_calendars": {"n_val": "~150 countries",   "n_classes": 19,  "method": "Comparison vs national statistics/FAO",  "oa": None, "f1": None, "kappa": None, "rmse": None, "r2": None, "bias": None, "region": "Global"},
    "icos":                {"n_val": "80+ stations (~15 cropland)","n_classes": None,"method": "3-level QC (raw/NRT/final)",   "oa": None, "f1": None, "kappa": None, "rmse": None, "r2": None, "bias": None, "region": "Europe"},
    # ---- Phenology Satellite ----
    "modis_mcd12q2":       {"n_val": "78 PhenoCam sites",  "n_classes": None,"method": "Independent comparison vs PhenoCam GCC","oa": None,"f1": None,"kappa": None,"rmse": 15, "r2": 0.78, "bias": None, "region": "Global"},
    "hp_lsp":              {"n_val": "78 PhenoCam sites",  "n_classes": None,"method": "Calibration + independent validation vs PhenoCam","oa": None,"f1": None,"kappa": None,"rmse": 4.5,"r2": 0.88,"bias": None, "region": "N. America (78 tiles)"},
    "gdpd":                {"n_val": "PhenoCam + flux towers","n_classes": None,"method": "Independent comparison vs PhenoCam/GPP","oa": None,"f1": None,"kappa": None,"rmse": None,"r2": 0.88,"bias": None, "region": "Global drylands"},
    "avhrr_phenology":     {"n_val": "PEP725 + USA-NPN", "n_classes": None,"method": "Independent comparison vs station networks","oa": None,"f1": None,"kappa": None,"rmse": 20,"r2": None,"bias": None, "region": "Global"},
    "chinacropphen1km":    {"n_val": "1,176 station-years","n_classes": 3, "method": "Independent comparison vs CMA stations",  "oa": None,"f1": None,"kappa": None,"rmse": 11,"r2": 0.78,"bias": None, "region": "China"},
    "china_maize_30m":     {"n_val": "CMA stations",     "n_classes": 1,  "method": "Independent comparison vs CMA stations",  "oa": None,"f1": None,"kappa": None,"rmse": 9.5,"r2": 0.82,"bias": None, "region": "China"},
    "copernicus_hrvpp":    {"n_val": "DWD + PEP725 stations","n_classes": None,"method": "Independent comparison vs DWD/PEP725","oa": None,"f1": None,"kappa": None,"rmse": 9.5,"r2": None,"bias": None, "region": "Europe (EEA-39)"},
    # ---- Yield ----
    "cy_bench":            {"n_val": "29&ndash;38 countries","n_classes": 2, "method": "Standardised train/test splits",       "oa": None, "f1": None, "kappa": None, "rmse": None, "r2": None, "bias": None, "region": "Global (subnational)"},
    "global_historical_yields":{"n_val": "~150 countries","n_classes": 4, "method": "Independent comparison vs FAO + USDA county","oa": None,"f1": None,"kappa": None,"rmse": None,"r2": 0.93,"bias": None, "region": "Global"},
    # ---- Benchmarks ----
    "eurocropsml":         {"n_val": "706,000 parcels",  "n_classes": 176, "method": "10-fold CV + cross-country transfer test","oa": 82,   "f1": None, "kappa": None, "rmse": None, "r2": None, "bias": None, "region": "Latvia, Portugal, Estonia"},
    "cropharvest":         {"n_val": "95,186 points",    "n_classes": 9,   "method": "Independent geographic holdout split",    "oa": 72,   "f1": 0.86, "kappa": None, "rmse": None, "r2": None, "bias": None, "region": "Global (21 source datasets)"},
    "dacia5":              {"n_val": "6,454 patches",    "n_classes": 8,   "method": "Stratified random holdout (80/20)",       "oa": 87,   "f1": None, "kappa": None, "rmse": None, "r2": None, "bias": None, "region": "Romania (Bra&#537;ov)"},
    "africa_crop_noncrop": {"n_val": "~5,000 points",    "n_classes": 2,   "method": "Random holdout split",                   "oa": None, "f1": 0.78, "kappa": None, "rmse": None, "r2": None, "bias": None, "region": "Ethiopia, Sudan, Togo, Kenya"},
    "senseco_s2":          {"n_val": "19 fields &times; 2&ndash;3 yr","n_classes": 2,"method": "Paired S2 vs in-situ comparison","oa": None,"f1": None,"kappa": None,"rmse": 8.5,"r2": None,"bias": None, "region": "Bulgaria + France"},
}


# ---------------------------------------------------------------------------
# Citation fetching via Semantic Scholar API (free, no key needed)
# ---------------------------------------------------------------------------

def fetch_citation_data(doi, cache):
    """Fetch citation data from Semantic Scholar API."""
    if not doi:
        return None
    cache_key = f"doi:{doi}"
    if cache_key in cache:
        age_days = (time.time() - cache[cache_key].get("_fetched", 0)) / 86400
        if age_days < 30:
            return cache[cache_key]
    url = (
        f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
        f"?fields=title,citationCount,referenceCount,year,url"
    )
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "PhenologyExplorer/1.0 (research)")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            data["_fetched"] = time.time()
            cache[cache_key] = data
            return data
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
        print(f"    Warning: S2 API error for {doi}: {e}")
        return None


def gs_search_url(doi=None, title=None):
    """Google Scholar search URL."""
    if doi:
        return f"https://scholar.google.com/scholar?q=doi%3A{doi.replace('/', '%2F')}"
    if title:
        return f"https://scholar.google.com/scholar?q={urllib.request.quote(title[:100])}"
    return None


def gs_cited_by_url(doi=None, title=None):
    """Google Scholar 'cited by' URL."""
    if doi:
        return f"https://scholar.google.com/scholar?cites=&q=doi%3A{doi.replace('/', '%2F')}&btnG="
    if title:
        return f"https://scholar.google.com/scholar?cites=&q={urllib.request.quote(title[:80])}"
    return None


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def esc(s):
    """Minimal HTML escaping for plain text (metadata already contains HTML entities)."""
    return s


def generate_html(datasets, citation_cache):
    """Generate comprehensive dataset documentation HTML."""
    now = datetime.now().strftime("%d %B %Y")
    n = len(datasets)
    cat_counts = {}
    for ds in datasets:
        cat_counts[ds["category"]] = cat_counts.get(ds["category"], 0) + 1

    p = []  # parts list
    p.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crop & Phenology Datasets — Documentation</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, system-ui, 'Segoe UI', sans-serif; font-size:14px;
       background:#1a1a2e; color:#e0e0e0; line-height:1.6; }}
.container {{ max-width:1100px; margin:0 auto; padding:20px; }}
h1 {{ color:#a8dadc; font-size:26px; margin-bottom:4px; }}
.subtitle {{ color:#888; font-size:13px; margin-bottom:20px; }}
.subtitle a {{ color:#4ecdc4; }}
h2 {{ color:#e94560; font-size:16px; margin:32px 0 14px; padding-bottom:6px;
     border-bottom:1px solid #333; text-transform:uppercase; letter-spacing:1px; }}
h2 .count {{ font-size:12px; color:#888; text-transform:none; letter-spacing:0; font-weight:400; }}
a {{ color:#4ecdc4; }}

.ds {{ background:#16213e; border-radius:8px; padding:18px 20px; margin-bottom:16px;
      border-left:4px solid #333; }}
.ds.crop-type {{ border-left-color:#2ecc71; }}
.ds.phenology {{ border-left-color:#e94560; }}
.ds.satellite {{ border-left-color:#3498db; }}
.ds.yield {{ border-left-color:#f1c40f; }}
.ds.benchmark {{ border-left-color:#9b59b6; }}

.ds-title {{ font-size:17px; font-weight:700; color:#a8dadc; margin-bottom:4px; }}
.ds-title a {{ color:#a8dadc; text-decoration:none; }}
.ds-title a:hover {{ text-decoration:underline; }}

.ds-desc {{ color:#ccc; margin:8px 0; font-size:13px; }}
.ds-section-head {{ font-size:12px; font-weight:600; color:#888; text-transform:uppercase;
                    letter-spacing:0.5px; margin:14px 0 4px; }}

.tags {{ margin:8px 0; }}
.tag {{ display:inline-block; padding:2px 8px; border-radius:12px; font-size:11px;
       font-weight:600; margin:2px 4px 2px 0; }}
.tag-region {{ background:#0f3460; color:#4ecdc4; }}
.tag-time {{ background:#3a1a1a; color:#e94560; }}
.tag-res {{ background:#2a1a3a; color:#9b59b6; }}
.tag-format {{ background:#3a2a0a; color:#f1c40f; }}
.tag-license {{ background:#1a2a3a; color:#3498db; }}

/* Stats bar */
.stats-bar {{ display:flex; flex-wrap:wrap; gap:4px 12px; margin:8px 0; padding:8px 12px;
             background:#0a1628; border-radius:4px; font-size:12px; }}
.stats-bar .sb-item {{ white-space:nowrap; }}
.stats-bar .sb-label {{ color:#888; }}
.stats-bar .sb-value {{ color:#4ecdc4; font-weight:600; margin-left:3px; }}
.stats-bar .sb-method {{ color:#999; font-style:italic; }}

.info-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:6px 20px; margin:10px 0;
             font-size:13px; }}
.info-grid dt {{ color:#888; font-size:11px; text-transform:uppercase; letter-spacing:0.3px; }}
.info-grid dd {{ color:#ccc; margin-bottom:4px; }}

/* Validation box */
.val-box {{ background:#0a1628; border:1px solid #2a3a5a; border-radius:6px;
           padding:14px 16px; margin:10px 0; }}
.val-box h4 {{ font-size:13px; color:#f1c40f; margin-bottom:6px; text-transform:uppercase;
              letter-spacing:0.5px; }}
.val-summary {{ font-size:13px; color:#ccc; margin-bottom:8px; }}
.val-metrics {{ display:grid; grid-template-columns:1fr 1fr; gap:4px 16px; font-size:12px;
               margin:8px 0; }}
.val-metrics .vm-label {{ color:#888; }}
.val-metrics .vm-value {{ color:#4ecdc4; font-weight:600; }}
.val-confusion {{ font-size:12px; color:#e67e22; margin:8px 0; padding:8px 12px;
                 background:#1a1a0a; border-left:3px solid #e67e22; border-radius:0 4px 4px 0; }}
.val-confusion b {{ color:#f39c12; }}
.val-notes {{ font-size:12px; color:#999; margin-top:6px; font-style:italic; }}

/* Papers */
.paper {{ background:#0f3460; border-radius:6px; padding:10px 14px; margin:6px 0;
         font-size:13px; }}
.paper-cite {{ color:#ccc; }}
.paper-links {{ margin-top:6px; font-size:12px; }}
.paper-links a {{ margin-right:14px; text-decoration:none; }}
.paper-links a:hover {{ text-decoration:underline; }}
.paper-figs {{ margin-top:6px; padding-left:16px; font-size:12px; color:#999; list-style:none; }}
.paper-figs li {{ margin:3px 0; padding-left:4px; }}
.paper-figs li b {{ color:#a8dadc; }}
.citation-count {{ display:inline-block; background:#1a3a1a; color:#2ecc71;
                  padding:1px 8px; border-radius:10px; font-size:11px; font-weight:600;
                  margin-left:6px; }}

.attribution {{ background:#0a0a1a; border-left:3px solid #f1c40f; padding:8px 12px;
               margin:8px 0; font-size:12px; color:#999; border-radius:0 4px 4px 0; }}

.ds-links {{ margin-top:12px; font-size:13px; }}
.ds-links a {{ margin-right:16px; text-decoration:none; }}
.ds-links a:hover {{ text-decoration:underline; }}
.btn {{ display:inline-block; padding:4px 12px; background:#e94560; color:white;
       border-radius:4px; text-decoration:none !important; font-size:12px; font-weight:600; }}
.btn:hover {{ background:#c81e45; }}

.toc {{ background:#0f3460; border-radius:6px; padding:14px 18px; margin-bottom:24px;
       font-size:13px; }}
.toc a {{ color:#a8dadc; text-decoration:none; margin-right:16px; white-space:nowrap; }}
.toc a:hover {{ color:#4ecdc4; }}

.nav {{ margin-bottom:16px; font-size:13px; }}
.nav a {{ color:#4ecdc4; text-decoration:none; }}
.footer {{ margin-top:36px; padding-top:16px; border-top:1px solid #333;
          font-size:11px; color:#666; }}
.footer a {{ color:#4ecdc4; }}
</style>
</head>
<body>
<div class="container">

<div class="nav"><a href="/">&larr; Back to Phenology Explorer</a></div>

<h1>Crop &amp; Phenology Datasets &mdash; Documentation</h1>
<p class="subtitle">
  Comprehensive catalog of {n} open-access datasets for crop type mapping,
  phenology, and yield research with validation summaries.<br>
  Compiled for the <a href="/">Phenology Explorer</a> tool.
  Last updated: {now}.
  <br>Auto-generated by <code>scripts/build_dataset_docs.py</code> &mdash; re-run to update.
  <br><a href="/datasets/analysis" style="color:#f1c40f;font-weight:600;">
  &rarr; Detailed Validation Analysis with interactive charts</a>
</p>

<div class="toc">
  <b>Jump to:</b>
""")
    for cid, ci in CATEGORIES.items():
        c = cat_counts.get(cid, 0)
        p.append(f'  <a href="#{cid}">{ci["name"]} ({c})</a>\n')
    p.append("</div>\n")

    for cid, ci in CATEGORIES.items():
        cds = [d for d in datasets if d["category"] == cid]
        if not cds:
            continue
        p.append(f'\n<h2 id="{cid}">{ci["name"]} <span class="count">({len(cds)} datasets)</span></h2>\n')

        for ds in cds:
            css = ci["css"]
            p.append(f'\n<div class="ds {css}" id="{ds["id"]}">\n')

            # Title
            url = ds.get("url", "")
            title = ds["title"]
            p.append(f'  <div class="ds-title">')
            p.append(f'<a href="{url}">{title}</a>' if url else title)
            p.append('</div>\n')

            # Tags
            p.append('  <div class="tags">\n')
            region = ds.get("spatial_extent", "")
            if "(" in region:
                region_short = region[:region.index("(")].strip()
            elif "&mdash;" in region:
                region_short = region[:region.index("&mdash;")].strip()
            else:
                region_short = region
            p.append(f'    <span class="tag tag-region">{region_short}</span>\n')
            p.append(f'    <span class="tag tag-time">{ds.get("temporal_extent", "")}</span>\n')
            res = ds.get("spatial_resolution", "")
            if res:
                res_short = res.split("(")[0].strip() if "(" in res else res
                p.append(f'    <span class="tag tag-res">{res_short}</span>\n')
            fmt = ds.get("format", "")
            if fmt:
                fmt_short = fmt.split("(")[0].strip() if "(" in fmt else fmt
                p.append(f'    <span class="tag tag-format">{fmt_short}</span>\n')
            lic = ds.get("license", "")
            if lic:
                p.append(f'    <span class="tag tag-license">{lic}</span>\n')
            p.append('  </div>\n')

            # Description
            p.append(f'  <div class="ds-desc">{ds["description"]}</div>\n')

            # Info grid
            p.append('  <dl class="info-grid">\n')
            p.append(f'    <dt>Spatial Extent</dt><dd>{ds.get("spatial_extent", "N/A")}</dd>\n')
            p.append(f'    <dt>Resolution</dt><dd>{ds.get("spatial_resolution", "N/A")}</dd>\n')
            p.append(f'    <dt>Temporal Extent</dt><dd>{ds.get("temporal_extent", "N/A")}</dd>\n')
            p.append(f'    <dt>Format</dt><dd>{ds.get("format", "N/A")}</dd>\n')
            p.append('  </dl>\n')

            # Contents
            if ds.get("contents"):
                p.append(f'  <div class="ds-section-head">Contents</div>\n')
                p.append(f'  <div class="ds-desc">{ds["contents"]}</div>\n')

            # License / Attribution
            lic = ds.get("license", "")
            lic_url = ds.get("license_url", "")
            attr = ds.get("attribution", "")
            if lic or attr:
                p.append('  <div class="ds-section-head">License &amp; Attribution</div>\n')
                if lic_url:
                    p.append(f'  <div class="ds-desc"><a href="{lic_url}">{lic}</a></div>\n')
                elif lic:
                    p.append(f'  <div class="ds-desc">{lic}</div>\n')
                if attr:
                    p.append(f'  <div class="attribution">Required attribution: &ldquo;{attr}&rdquo;</div>\n')

            # Validation
            val = ds.get("validation")
            if val:
                # Link to relevant analysis section
                analysis_section = {
                    "crop-type": "crop-accuracy",
                    "phenology-ground": "phenology-accuracy",
                    "phenology-satellite": "phenology-comparison",
                    "benchmark": "benchmark-results",
                    "yield": "overview",
                }.get(ds["category"], "overview")
                p.append('  <div class="val-box">\n')
                p.append(f'    <h4>Validation &amp; Accuracy '
                         f'<a href="/datasets/analysis#{analysis_section}" '
                         f'style="font-size:11px;text-transform:none;letter-spacing:0;'
                         f'font-weight:400;color:#4ecdc4;">'
                         f'[detailed analysis &rarr;]</a></h4>\n')
                # Stats bar
                st = VALIDATION_STATS.get(ds["id"])
                if st:
                    p.append('    <div class="stats-bar">\n')
                    if st.get("n_val"):
                        p.append(f'      <span class="sb-item"><span class="sb-label">N:</span>'
                                 f'<span class="sb-value">{st["n_val"]}</span></span>\n')
                    if st.get("oa") is not None:
                        p.append(f'      <span class="sb-item"><span class="sb-label">OA:</span>'
                                 f'<span class="sb-value">{st["oa"]}%</span></span>\n')
                    if st.get("f1") is not None:
                        p.append(f'      <span class="sb-item"><span class="sb-label">F1:</span>'
                                 f'<span class="sb-value">{st["f1"]}</span></span>\n')
                    if st.get("kappa") is not None:
                        p.append(f'      <span class="sb-item"><span class="sb-label">&kappa;:</span>'
                                 f'<span class="sb-value">{st["kappa"]}</span></span>\n')
                    if st.get("rmse") is not None:
                        p.append(f'      <span class="sb-item"><span class="sb-label">RMSE:</span>'
                                 f'<span class="sb-value">{st["rmse"]} days</span></span>\n')
                    if st.get("r2") is not None:
                        p.append(f'      <span class="sb-item"><span class="sb-label">R&sup2;:</span>'
                                 f'<span class="sb-value">{st["r2"]}</span></span>\n')
                    if st.get("method"):
                        p.append(f'      <span class="sb-item"><span class="sb-method">'
                                 f'{st["method"]}</span></span>\n')
                    p.append('    </div>\n')
                p.append(f'    <div class="val-summary">{val["summary"]}</div>\n')
                metrics = val.get("metrics", [])
                if metrics:
                    p.append('    <div class="val-metrics">\n')
                    for label, value in metrics:
                        p.append(f'      <span class="vm-label">{label}</span>'
                                 f'<span class="vm-value">{value}</span>\n')
                    p.append('    </div>\n')
                confusion = val.get("confusion", "")
                if confusion:
                    p.append(f'    <div class="val-confusion"><b>Confusion patterns:</b> {confusion}</div>\n')
                notes = val.get("notes", "")
                if notes:
                    p.append(f'    <div class="val-notes">{notes}</div>\n')
                p.append('  </div>\n')

            # Papers
            papers = ds.get("papers", [])
            if papers:
                p.append(f'  <div class="ds-section-head">References</div>\n')
                for paper in papers:
                    p.append('  <div class="paper">\n')
                    p.append(f'    <div class="paper-cite">{paper["citation"]}</div>\n')
                    p.append('    <div class="paper-links">\n')
                    doi = paper.get("doi")
                    if doi:
                        p.append(f'      <a href="https://doi.org/{doi}">DOI: {doi}</a>\n')
                        s2 = citation_cache.get(f"doi:{doi}")
                        if s2 and s2.get("citationCount"):
                            p.append(f'      <span class="citation-count">{s2["citationCount"]} citations</span>\n')
                        gs = gs_search_url(doi=doi)
                        gc = gs_cited_by_url(doi=doi)
                        if gs:
                            p.append(f'      <a href="{gs}">Google Scholar</a>\n')
                        if gc:
                            p.append(f'      <a href="{gc}">Cited by (Scholar)</a>\n')
                    elif paper.get("url"):
                        p.append(f'      <a href="{paper["url"]}">Paper</a>\n')
                    if paper.get("open_access"):
                        p.append('      <span class="tag tag-license" style="font-size:10px">Open Access</span>\n')
                    p.append('    </div>\n')
                    figs = paper.get("key_figures", [])
                    if figs:
                        p.append('    <ul class="paper-figs">\n')
                        for fig in figs:
                            if isinstance(fig, dict):
                                p.append(f'      <li><b>{fig["id"]}:</b> {fig["desc"]}</li>\n')
                            else:
                                p.append(f'      <li>{fig}</li>\n')
                        p.append('    </ul>\n')
                    p.append('  </div>\n')

            # Links
            p.append('  <div class="ds-links">\n')
            if ds.get("download_url"):
                p.append(f'    <a class="btn" href="{ds["download_url"]}">Download</a>\n')
            if ds.get("code_url"):
                p.append(f'    <a href="{ds["code_url"]}">Source code</a>\n')
            if ds.get("in_catalog"):
                p.append('    <span class="tag tag-license" style="font-size:10px">'
                         'In validation catalog</span>\n')
            p.append('  </div>\n')
            p.append('</div>\n')

    p.append(f"""
<div class="footer">
  <p>This catalog focuses on openly available datasets for crop phenology, type classification,
  and yield research. Citation counts from
  <a href="https://www.semanticscholar.org/">Semantic Scholar</a> (updated {now}).
  Google Scholar links open external search pages.</p>
  <p style="margin-top:4px">See also:
  <a href="https://github.com/Agri-Hub/Callisto-Dataset-Collection">Callisto Collection</a>,
  <a href="https://github.com/satellite-image-deep-learning/datasets">satellite-image-deep-learning/datasets</a>,
  <a href="https://lacunafund.org/datasets/agriculture/">Lacuna Fund agriculture datasets</a>.
  </p>
  <p style="margin-top:8px">Generated by <code>scripts/build_dataset_docs.py</code>
  for the <a href="/">Phenology Explorer</a> project.</p>
</div>

</div>
</body>
</html>
""")
    return "".join(p)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Build dataset documentation page")
    parser.add_argument("--no-fetch", action="store_true",
                        help="Skip Semantic Scholar API calls (use cached data only)")
    args = parser.parse_args()

    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    cache = {}
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            cache = json.load(f)
        print(f"Loaded citation cache ({len(cache)} entries)")

    if not args.no_fetch:
        dois = set()
        for ds in DATASETS:
            for paper in ds.get("papers", []):
                if paper.get("doi"):
                    dois.add(paper["doi"])
        print(f"Fetching citation data for {len(dois)} papers...")
        for i, doi in enumerate(sorted(dois)):
            existing = cache.get(f"doi:{doi}")
            if existing and (time.time() - existing.get("_fetched", 0)) / 86400 < 30:
                print(f"  [{i+1}/{len(dois)}] {doi} — cached ({existing.get('citationCount', '?')} cit.)")
                continue
            print(f"  [{i+1}/{len(dois)}] {doi} — fetching...", end=" ", flush=True)
            data = fetch_citation_data(doi, cache)
            if data:
                print(f"OK ({data.get('citationCount', '?')} cit.)")
            else:
                print("no data")
            time.sleep(1.1)
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
        print(f"Saved citation cache ({len(cache)} entries)")
    else:
        print("Skipping API calls (--no-fetch)")

    print(f"\nGenerating documentation for {len(DATASETS)} datasets...")
    html = generate_html(DATASETS, cache)

    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_HTML, "w") as f:
        f.write(html)
    size_kb = OUTPUT_HTML.stat().st_size / 1024
    print(f"Written: {OUTPUT_HTML} ({size_kb:.0f} KB)")

    # Summary
    print(f"\nDatasets: {len(DATASETS)} across {len(CATEGORIES)} categories")
    for cid, ci in CATEGORIES.items():
        nc = sum(1 for d in DATASETS if d["category"] == cid)
        nv = sum(1 for d in DATASETS if d["category"] == cid and d.get("validation"))
        print(f"  {ci['name']}: {nc} datasets ({nv} with validation)")
    n_papers = sum(len(d.get("papers", [])) for d in DATASETS)
    n_val = sum(1 for d in DATASETS if d.get("validation"))
    print(f"\nPapers referenced: {n_papers}")
    print(f"Datasets with validation: {n_val}")


if __name__ == "__main__":
    main()

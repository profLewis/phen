# Dataset Attribution & Licenses

This repository includes or references the following datasets. Each dataset
retains its original license. Users must comply with the terms of each license
when using or redistributing the data.

---

## Included Datasets (in this repository)

### NE China Maize Phenology (1981–2024)
- **Citation**: Zhang, Q.-J., Wu, D.-L., Zhu, Y.-C., Liu, C. & Yang, D.-S.
  A long-term dataset of maize phenology observations from agrometeorological
  stations in Northeast China (1981–2024). *Scientific Data* **12**, 2037 (2025).
  https://doi.org/10.1038/s41597-025-06330-9
- **Data DOI**: https://doi.org/10.57760/sciencedb.28709
- **License**: CC BY-NC-ND 4.0 (Creative Commons Attribution-NonCommercial-NoDerivatives)
- **Source**: Science Data Bank (scidb.cn)
- **Files**: `data/china_maize_phenology/`
- **Contents**: 2 XLSX data tables + 976 diagnostic JPEG plots from 61 stations
  across Heilongjiang, Jilin, and Liaoning provinces

### FlevoVision Crop Phenology (Netherlands, 2018)
- **Citation**: D'Andrimont, R. et al. Detecting flowering phenology in oil seed
  rape parcels with Sentinel-1 and -2 time series. *Computers and Electronics
  in Agriculture* **193**, 106882 (2022).
  https://doi.org/10.1016/j.compag.2022.106882
- **License**: Open access
- **Files**: `data/flevovision/tf_flevo_toshare.csv`
- **Contents**: 259 crop sites with BBCH ground truth stages, Flevoland, NL

### SenSeCo In-situ Crop Phenology (Bulgaria & France, 2018–2020)
- **Citation**: SenSeCo COST Action CA17134 — Optical synergies for
  spatiotemporal SENsing of Scalable ECOphysiological traits
- **Data DOI**: https://doi.org/10.5281/zenodo.8067432
- **License**: CC BY 4.0
- **Files**: `data/senseco_phenology/`
- **Contents**: Field-level BBCH observations for winter rapeseed and wheat

---

## Downloaded at Runtime (not in repository)

### DWD Germany Crop Phenology Observations
- **Source**: Deutscher Wetterdienst (DWD), Open Data
- **URL**: https://opendata.dwd.de/climate_environment/CDC/observations_germany/phenology/
- **License**: DL-DE/BY-2.0 (Datenlizenz Deutschland – Namensnennung – Version 2.0)
- **Attribution**: "Phänologische Beobachtungen, Deutscher Wetterdienst, Offenbach"
- **Contents**: Phenophase dates for wheat, barley, maize, rapeseed, oats, sugar beet

### PhenoCam v3.0 — Camera-derived Vegetation Phenology
- **Citation**: Seyednasrollah, B. et al. PhenoCam Dataset v3.0: Digital camera
  imagery from the PhenoCam Network. *ORNL DAAC* (2023).
  https://doi.org/10.3334/ORNLDAAC/2389
- **License**: Open (EOSDIS data use policy)
- **Source**: PhenoCam Network / ORNL DAAC
- **Contents**: GCC (Green Chromatic Coordinate) time series from 738 sites

### Kenya Helmets Crop Type Dataset v2
- **Citation**: D'Andrimont, R. et al. Helmets Crop Type Dataset v2 — Kenya.
  *Zenodo* (2025). https://doi.org/10.5281/zenodo.15467063
- **Paper**: https://doi.org/10.1038/s41597-025-05762-7
- **License**: CC BY-SA 4.0
- **Contents**: 12,299 georeferenced crop type points from 16 Kenyan counties

### EuroCropsML
- **Citation**: Schneider, M. et al. EuroCropsML: A Time Series Benchmark
  Dataset for Few-Shot Crop Type Classification. *Scientific Data* (2025).
  https://doi.org/10.1038/s41597-025-04952-7
- **Data DOI**: https://doi.org/10.5281/zenodo.10629610
- **License**: Open
- **Contents**: 706K agricultural parcels with Sentinel-2 time series

---

## Satellite Data

### Sentinel-2 L2A
- **Source**: AWS Element84 Earth Search (https://earth-search.aws.element84.com/v1)
- **Collection**: sentinel-2-l2a
- **License**: Copernicus Sentinel Data Terms and Conditions
  (free, full, and open access)
- **Attribution**: "Contains modified Copernicus Sentinel data [year]"
- **Usage**: S2 data extracted as 5×5 pixel time series for validation locations

---

## Additional Referenced Datasets (in catalog, not downloaded)

See the full datasets catalog at `/datasets` in the web application, or
`webapp/templates/datasets.html` for the complete list of 35 referenced datasets
with their individual citations, DOIs, and license information.

Key datasets include:
- **PEP725** (Pan European Phenological Database) — registration required
- **USA-NPN** (National Phenology Network) — CC0
- **MODIS MCD12Q2** — NASA EOSDIS open data
- **SAGE Crop Calendars** — Sacks et al. (2010)
- **GEOGLAM CM4EW Calendars** — Crop Monitor for Early Warning
- **CROME** (Crop Map of England) — OGL v3
- **USDA CDL** — public domain
- **Copernicus HR-VPP** — Copernicus open data

---

## General Notes

- All Sentinel-2 derived products in this repository are subject to the
  Copernicus Sentinel Data Terms and Conditions.
- Datasets with CC BY or CC BY-SA licenses require attribution when used.
- The CC BY-NC-ND license on the China Maize dataset prohibits commercial
  use and derivative works.
- DWD data requires citation of "Deutscher Wetterdienst" as source.

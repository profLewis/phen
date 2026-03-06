# phen

Phenology modelling: codes and data for fitting and analysing vegetation phenology from remote sensing time series.

## Datasets

### FlevoVision (street-level imagery + BBCH phenology labels)

From [D'Andrimont et al. (2022)](https://doi.org/10.1016/j.compag.2022.106890) — "Monitoring crop phenology with street-level imagery using computer vision".

- ~8,300 labelled observations across 17 crop types with BBCH phenological stage codes
- ~400,000 geo-tagged street-level images from Flevoland, Netherlands (March–October 2018)
- Metadata CSV included at `data/flevovision/tf_flevo_toshare.csv`
- Images (large) can be downloaded with `scripts/download_flevovision_images.sh`
- Source: [JRC DRLL](https://data.jrc.ec.europa.eu/collection/id-00355)

### EuroCropsML (Sentinel-2 time series for crop parcels)

From [Zenodo 15095445](https://doi.org/10.5281/zenodo.15095445) — Sentinel-2 L1C time series for 706K agricultural parcels across Estonia, Latvia, and Portugal (2021).

- Annual multi-spectral time series per parcel (median pixel values)
- 176 crop classes, cloud-filtered
- Download (~4.8 GB) with `scripts/download_eurocropsml.sh`
- GitHub: [dida-do/eurocropsml](https://github.com/dida-do/eurocropsml)

## Structure

```
phen/
├── data/
│   ├── flevovision/      # FlevoVision metadata CSV (+ images if downloaded)
│   └── eurocropsml/      # EuroCropsML Sentinel-2 time series
├── notebooks/            # Analysis notebooks
└── scripts/              # Download and processing scripts
```

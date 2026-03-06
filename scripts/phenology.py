#!/usr/bin/env python3
"""
Phenology modelling from FlevoVision (BBCH ground truth) and EuroCropsML (Sentinel-2 time series).

Fits double-logistic and asymmetric-Gaussian phenological models to NDVI time series
derived from Sentinel-2 data (EuroCropsML), and validates against BBCH phenology stages
from the FlevoVision dataset.

Usage:
    python scripts/phenology.py [--skip-eurocropsml] [--max-parcels N] [--output-dir DIR]
"""

import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import curve_fit

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FLEVOVISION_CSV = DATA / "flevovision" / "tf_flevo_toshare.csv"
EUROCROPSML_DIR = DATA / "eurocropsml" / "preprocess"

# Sentinel-2 L1C band order (13 bands)
S2_BANDS = [
    "B01", "B02", "B03", "B04", "B05", "B06", "B07",
    "B08", "B8A", "B09", "B10", "B11", "B12",
]
B04_IDX = S2_BANDS.index("B04")  # Red
B08_IDX = S2_BANDS.index("B08")  # NIR


# ===================================================================
# Phenological model functions
# ===================================================================

def double_logistic(t, a1, a2, a3, a4, a5, a6):
    """Double logistic (Beck et al. 2006).

    Models a single growing season as the difference of two logistic curves:
        y(t) = a1 + a2 * (1/(1+exp(-a3*(t-a4))) - 1/(1+exp(-a5*(t-a6))))

    Parameters:
        a1 - winter baseline NDVI
        a2 - amplitude
        a3 - greenup rate
        a4 - greenup midpoint (DOY)
        a5 - senescence rate
        a6 - senescence midpoint (DOY)
    """
    return a1 + a2 * (
        1.0 / (1.0 + np.exp(-a3 * (t - a4)))
        - 1.0 / (1.0 + np.exp(-a5 * (t - a6)))
    )


def asymmetric_gaussian(t, a1, a2, a3, a4, a5, a6):
    """Asymmetric Gaussian (Jönsson & Eklundh 2002, TIMESAT).

    Parameters:
        a1 - baseline
        a2 - amplitude
        a3 - peak position (DOY)
        a4 - greenup width (left)
        a5 - senescence width (right)
        a6 - flatness parameter
    """
    left = np.exp(-(np.abs((t - a3) / a4)) ** a6)
    right = np.exp(-(np.abs((t - a3) / a5)) ** a6)
    shape = np.where(t <= a3, left, right)
    return a1 + a2 * shape


# ===================================================================
# Phenometric extraction
# ===================================================================

def extract_phenometrics(t_dense, y_fitted):
    """Extract SOS, POS, EOS from a fitted phenology curve.

    SOS/EOS defined as the points where the curve crosses 20% of amplitude
    above the baseline (on the rising/falling limbs respectively).
    """
    baseline = np.min(y_fitted)
    amplitude = np.max(y_fitted) - baseline
    if amplitude < 0.02:
        return {"SOS": None, "POS": None, "EOS": None, "amplitude": amplitude}

    threshold = baseline + 0.2 * amplitude
    pos_idx = np.argmax(y_fitted)
    pos = t_dense[pos_idx]

    # SOS: first crossing on rising limb
    rising = y_fitted[:pos_idx]
    sos_candidates = np.where(rising >= threshold)[0]
    sos = t_dense[sos_candidates[0]] if len(sos_candidates) > 0 else None

    # EOS: last crossing on falling limb
    falling = y_fitted[pos_idx:]
    eos_candidates = np.where(falling >= threshold)[0]
    eos = t_dense[pos_idx + eos_candidates[-1]] if len(eos_candidates) > 0 else None

    return {"SOS": sos, "POS": pos, "EOS": eos, "amplitude": amplitude}


# ===================================================================
# Data loading
# ===================================================================

def check_datasets():
    """Check that required datasets are present, print instructions if not."""
    ok = True
    if not FLEVOVISION_CSV.exists():
        print(f"MISSING: {FLEVOVISION_CSV}")
        print("  Run: curl -L -o data/flevovision/tf_flevo_toshare.csv "
              '"https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/DRLL/FlevoVision/tf_flevo_toshare.csv"')
        ok = False
    else:
        print(f"OK: FlevoVision CSV ({FLEVOVISION_CSV})")

    if not EUROCROPSML_DIR.exists() or not any(EUROCROPSML_DIR.glob("*.npz")):
        print(f"MISSING: EuroCropsML preprocessed data ({EUROCROPSML_DIR})")
        print("  Run: bash scripts/download_eurocropsml.sh")
        ok = False
    else:
        # Quick sample count (full glob of 700K files is slow)
        sample = list(EUROCROPSML_DIR.glob("*.npz"))[:10]
        print(f"OK: EuroCropsML ({EUROCROPSML_DIR}, {len(sample)}+ .npz files found)")

    return ok


def load_flevovision():
    """Load FlevoVision CSV → per-parcel BBCH time series.

    Returns dict: {(crop_code, parcel_id): [(date, bbch), ...]}
    """
    parcels = defaultdict(list)
    with open(FLEVOVISION_CSV, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row["code"]
            parcel_id = row["code_bbch_surveyed"]
            bbch_raw = row["bbch"]
            ts = row["timestamp"]
            if bbch_raw == "NA" or not bbch_raw:
                continue
            try:
                bbch = int(bbch_raw)
            except ValueError:
                continue
            dt = datetime.strptime(ts[:10], "%Y-%m-%d")
            doy = dt.timetuple().tm_yday
            parcels[(code, parcel_id)].append((doy, bbch, dt))
    # Sort by date
    for key in parcels:
        parcels[key].sort()
    return parcels


def load_eurocropsml_parcel(npz_path):
    """Load a single EuroCropsML .npz file → (doys, ndvi) arrays.

    File structure: 'data' (n_obs x 13 bands, DN int), 'dates' (datetime64[D]),
    'center' ([lon, lat]). Sentinel-2 L1C DN values, reflectance = DN / 10000.

    Returns (doys, ndvi) or (None, None) on failure.
    """
    try:
        npz = np.load(npz_path, allow_pickle=True)
    except Exception:
        return None, None

    if "data" not in npz or "dates" not in npz:
        return None, None

    refl = npz["data"].astype(float) / 10000.0  # DN → reflectance
    dates = npz["dates"]

    if refl.ndim != 2 or refl.shape[1] < 13:
        return None, None

    # NDVI from B04 (Red, idx 3) and B08 (NIR, idx 7)
    red = refl[:, B04_IDX]
    nir = refl[:, B08_IDX]
    denom = nir + red
    ndvi = np.where(denom > 0, (nir - red) / denom, np.nan)

    # Dates → DOY
    base = np.datetime64("2021-01-01")
    doys = (dates - base).astype(int) + 1  # Jan 1 = DOY 1

    # Remove NaN
    valid = ~np.isnan(ndvi)
    return doys[valid].astype(float), ndvi[valid]


# ===================================================================
# Fitting
# ===================================================================

def fit_phenology(doys, ndvi, model="double_logistic"):
    """Fit a phenological model to (doys, ndvi).

    Returns (params, t_dense, y_fitted, model_name) or None on failure.
    """
    if len(doys) < 6:
        return None

    t = doys.astype(float)
    y = ndvi.astype(float)

    if model == "double_logistic":
        func = double_logistic
        # Initial guess: baseline, amplitude, greenup rate, greenup DOY, senescence rate, senescence DOY
        p0 = [np.min(y), np.max(y) - np.min(y), 0.1, 120, 0.1, 270]
        bounds = (
            [0, 0, 0.001, 1, 0.001, 1],
            [1, 1, 1.0, 365, 1.0, 365],
        )
    elif model == "asymmetric_gaussian":
        func = asymmetric_gaussian
        peak_doy = t[np.argmax(y)]
        p0 = [np.min(y), np.max(y) - np.min(y), peak_doy, 40, 40, 2]
        bounds = (
            [0, 0, 1, 5, 5, 1],
            [1, 1, 365, 200, 200, 10],
        )
    else:
        raise ValueError(f"Unknown model: {model}")

    try:
        params, _ = curve_fit(func, t, y, p0=p0, bounds=bounds, maxfev=5000)
    except (RuntimeError, ValueError):
        return None

    t_dense = np.linspace(1, 365, 365)
    y_fitted = func(t_dense, *params)
    return params, t_dense, y_fitted, model


# ===================================================================
# Analysis & plotting
# ===================================================================

def analyse_flevovision(parcels, output_dir):
    """Analyse BBCH phenological progression from FlevoVision ground truth."""
    print("\n=== FlevoVision BBCH Phenology Analysis ===")

    # Aggregate by crop type
    crops = defaultdict(list)
    for (code, _parcel_id), observations in parcels.items():
        for doy, bbch, _dt in observations:
            crops[code].append((doy, bbch))

    print(f"Crops: {sorted(crops.keys())}")
    print(f"Total observations: {sum(len(v) for v in crops.values())}")

    # Plot BBCH progression per crop
    fig, axes = plt.subplots(4, 4, figsize=(16, 12), sharex=True, sharey=True)
    axes = axes.flatten()
    crop_list = sorted(crops.keys())

    for i, crop in enumerate(crop_list):
        if i >= len(axes):
            break
        ax = axes[i]
        obs = crops[crop]
        doys = [o[0] for o in obs]
        bbchs = [o[1] for o in obs]
        ax.scatter(doys, bbchs, s=4, alpha=0.3)
        ax.set_title(crop, fontsize=10)
        ax.set_xlim(60, 310)

    for i in range(len(crop_list), len(axes)):
        axes[i].set_visible(False)

    fig.supxlabel("Day of Year")
    fig.supylabel("BBCH Stage")
    fig.suptitle("FlevoVision: BBCH Phenological Progression by Crop (2018)")
    fig.tight_layout()
    out_path = output_dir / "flevovision_bbch_by_crop.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Saved: {out_path}")

    # Summary stats
    print("\nCrop  | Obs | BBCH range | DOY range")
    print("------|-----|------------|----------")
    for crop in crop_list:
        obs = crops[crop]
        doys = [o[0] for o in obs]
        bbchs = [o[1] for o in obs]
        print(f"{crop:5s} | {len(obs):3d} | {min(bbchs):2d}–{max(bbchs):2d}       | {min(doys):3d}–{max(doys):3d}")


def analyse_eurocropsml(max_parcels, output_dir):
    """Load EuroCropsML parcels, fit phenology models, extract metrics."""
    print("\n=== EuroCropsML Phenology Fitting ===")

    npz_files = sorted(EUROCROPSML_DIR.glob("*.npz"))
    if not npz_files:
        print("No .npz files found — skipping.")
        return

    if max_parcels > 0:
        npz_files = npz_files[:max_parcels]
    print(f"Processing {len(npz_files)} parcels ...")

    results = []
    n_ok = 0
    n_fail = 0

    for npz_path in npz_files:
        doys, ndvi = load_eurocropsml_parcel(npz_path)
        if doys is None or len(doys) < 6:
            n_fail += 1
            continue

        # Parse crop class from filename: <NUTS3>_<parcelID>_<EC_hcat_c>.npz
        stem = npz_path.stem
        parts = stem.rsplit("_", 1)
        crop_class = parts[-1] if len(parts) > 1 else "unknown"

        # Try both models
        best = None
        for model_name in ["double_logistic", "asymmetric_gaussian"]:
            result = fit_phenology(doys, ndvi, model=model_name)
            if result is not None:
                params, t_dense, y_fitted, mname = result
                residuals = ndvi - (
                    double_logistic(doys, *params) if mname == "double_logistic"
                    else asymmetric_gaussian(doys, *params)
                )
                rmse = np.sqrt(np.mean(residuals ** 2))
                if best is None or rmse < best["rmse"]:
                    best = {
                        "params": params, "t_dense": t_dense, "y_fitted": y_fitted,
                        "model": mname, "rmse": rmse, "doys": doys, "ndvi": ndvi,
                        "crop": crop_class, "name": stem,
                    }

        if best is not None:
            metrics = extract_phenometrics(best["t_dense"], best["y_fitted"])
            best["metrics"] = metrics
            results.append(best)
            n_ok += 1
        else:
            n_fail += 1

    print(f"Fitted: {n_ok}, Failed: {n_fail}")

    if not results:
        return

    # Print phenometrics summary
    print("\nParcel                               | Crop | Model            | RMSE  | SOS  | POS  | EOS  | Amp")
    print("-------------------------------------|------|------------------|-------|------|------|------|-----")
    for r in results[:30]:
        m = r["metrics"]
        sos = f"{m['SOS']:5.0f}" if m["SOS"] is not None else "  N/A"
        pos = f"{m['POS']:5.0f}" if m["POS"] is not None else "  N/A"
        eos = f"{m['EOS']:5.0f}" if m["EOS"] is not None else "  N/A"
        print(
            f"{r['name'][:36]:36s} | {r['crop'][:4]:4s} | {r['model']:16s} | "
            f"{r['rmse']:.3f} | {sos} | {pos} | {eos} | {m['amplitude']:.2f}"
        )

    # Plot a sample of fitted curves
    n_plot = min(12, len(results))
    fig, axes = plt.subplots(3, 4, figsize=(16, 10))
    axes = axes.flatten()
    for i in range(n_plot):
        ax = axes[i]
        r = results[i]
        ax.scatter(r["doys"], r["ndvi"], s=10, c="black", zorder=3, label="obs")
        ax.plot(r["t_dense"], r["y_fitted"], "r-", lw=1.5, label=r["model"])
        m = r["metrics"]
        for key, color, ls in [("SOS", "green", "--"), ("POS", "blue", ":"), ("EOS", "orange", "--")]:
            if m[key] is not None:
                ax.axvline(m[key], color=color, ls=ls, lw=0.8, label=key)
        ax.set_title(f"{r['crop']} RMSE={r['rmse']:.3f}", fontsize=9)
        ax.set_xlim(1, 365)
        ax.set_ylim(-0.1, 1.0)
        if i == 0:
            ax.legend(fontsize=6, loc="upper left")
    for i in range(n_plot, len(axes)):
        axes[i].set_visible(False)
    fig.supxlabel("Day of Year")
    fig.supylabel("NDVI")
    fig.suptitle("EuroCropsML: Phenology Model Fits (Sentinel-2 NDVI)")
    fig.tight_layout()
    out_path = output_dir / "eurocropsml_phenology_fits.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"\nSaved: {out_path}")

    # Histogram of phenometrics
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    for ax, key, label in zip(axes, ["SOS", "POS", "EOS"],
                               ["Start of Season", "Peak of Season", "End of Season"]):
        vals = [r["metrics"][key] for r in results if r["metrics"][key] is not None]
        if vals:
            ax.hist(vals, bins=30, edgecolor="black", alpha=0.7)
            ax.set_xlabel("Day of Year")
            ax.set_title(label)
    fig.suptitle("Distribution of Phenometrics")
    fig.tight_layout()
    out_path = output_dir / "phenometrics_distribution.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Saved: {out_path}")


# ===================================================================
# Main
# ===================================================================

def main():
    parser = argparse.ArgumentParser(description="Phenology modelling pipeline")
    parser.add_argument("--skip-eurocropsml", action="store_true",
                        help="Skip EuroCropsML processing (if not yet downloaded)")
    parser.add_argument("--max-parcels", type=int, default=200,
                        help="Max EuroCropsML parcels to process (default: 200)")
    parser.add_argument("--output-dir", type=str, default=str(ROOT / "output"),
                        help="Output directory for plots")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Phenology Modelling Pipeline")
    print("=" * 50)

    # 1. Check datasets
    print("\nChecking datasets ...")
    datasets_ok = check_datasets()
    if not datasets_ok:
        print("\nSome datasets are missing. See instructions above.")
        if not FLEVOVISION_CSV.exists():
            print("Cannot proceed without FlevoVision CSV. Exiting.")
            sys.exit(1)

    # 2. FlevoVision analysis
    print("\nLoading FlevoVision ...")
    parcels = load_flevovision()
    print(f"Loaded {len(parcels)} parcel time series")
    analyse_flevovision(parcels, output_dir)

    # 3. EuroCropsML phenology fitting
    if args.skip_eurocropsml:
        print("\nSkipping EuroCropsML (--skip-eurocropsml)")
    elif not EUROCROPSML_DIR.exists():
        print(f"\nEuroCropsML data not found at {EUROCROPSML_DIR} — skipping.")
        print("Run: bash scripts/download_eurocropsml.sh")
    else:
        analyse_eurocropsml(args.max_parcels, output_dir)

    print("\nDone.")


if __name__ == "__main__":
    main()

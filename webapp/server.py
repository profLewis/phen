#!/usr/bin/env python3
"""
Phenology web tool — Flask backend.

Lets users click on a Leaflet map to select pixels, extracts Sentinel-2 time
series via STAC/COG, applies smoothing (Savitzky-Golay or DCT/Garcia), fits
phenological models, and returns interactive plots.

Usage:
    python webapp/server.py [--port 5001]
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# GDAL env for COG access
os.environ.update({
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF",
    "GDAL_HTTP_MAX_RETRY": "3",
    "GDAL_HTTP_RETRY_DELAY": "2",
})

import numpy as np
from flask import Flask, jsonify, render_template, request
from scipy.fft import dct, idct
from scipy.ndimage import uniform_filter1d
from scipy.optimize import curve_fit
from scipy.signal import savgol_filter

import rasterio
from rasterio.windows import Window
from pystac_client import Client
from pyproj import Transformer

ROOT = Path(__file__).resolve().parent.parent
app = Flask(__name__, template_folder="templates", static_folder="static")

STAC_URL = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-l2a"

BAND_ASSETS = {
    "B02": "blue", "B03": "green", "B04": "red", "B08": "nir",
    "B05": "rededge1", "B06": "rededge2", "B07": "rededge3",
    "B8A": "nir08", "B11": "swir16", "B12": "swir22",
    "SCL": "scl",
}

SCL_GOOD = {4, 5}  # vegetation, bare soil


# ===================================================================
# Phenological models
# ===================================================================

def double_logistic(t, a1, a2, a3, a4, a5, a6):
    """Beck et al. (2006) double logistic."""
    return a1 + a2 * (
        1.0 / (1.0 + np.exp(-a3 * (t - a4)))
        - 1.0 / (1.0 + np.exp(-a5 * (t - a6)))
    )


def logistic_greenup(t, a, b, c, d):
    """Single logistic for green-up / senescence fitting."""
    return a + b / (1.0 + np.exp(-(t - c) / d))


# ===================================================================
# Smoothing filters
# ===================================================================

def smooth_savgol(doys, values, window=31, poly=3):
    """Savitzky-Golay filter on irregularly-spaced data.

    Interpolates to daily, applies SG, then samples back.
    """
    daily_doy = np.arange(1, 366)
    daily_vals = np.interp(daily_doy, doys, values)
    win = min(window, len(daily_vals))
    if win % 2 == 0:
        win -= 1
    win = max(win, poly + 2)
    smoothed = savgol_filter(daily_vals, win, poly)
    return daily_doy, smoothed


def smooth_dct_garcia(doys, values, s=None):
    """DCT-based smoothing (Garcia, 2010).

    Automatic smoothing of uniformly-sampled data using penalized
    least-squares and the discrete cosine transform.

    If s is None, uses GCV to find optimal smoothing parameter.
    """
    # Interpolate to daily
    daily_doy = np.arange(1, 366)
    y = np.interp(daily_doy, doys, values)
    n = len(y)

    # Weights (1 where we have actual data, lower elsewhere)
    w = np.zeros(n)
    for d in doys:
        idx = int(d) - 1
        if 0 <= idx < n:
            w[idx] = 1.0
    # Smooth the weights to give partial credit to nearby days
    w = uniform_filter1d(w.astype(float), size=5)
    w = np.clip(w, 0.1, 1.0)

    if s is None:
        # Auto-select smoothing parameter via simple search
        best_s, best_gcv = 1.0, np.inf
        for log_s in np.linspace(-2, 6, 50):
            s_try = 10 ** log_s
            z = _dct_smooth(y, w, s_try, n)
            residuals = w * (y - z)
            rss = np.sum(residuals ** 2)
            # Approximate degrees of freedom
            gamma = 1.0 / (1.0 + s_try * (2 * np.arange(n) * np.pi / n) ** 2)
            trace_h = np.sum(gamma)
            denom = (1.0 - trace_h / n) ** 2
            if denom > 0:
                gcv = rss / n / denom
                if gcv < best_gcv:
                    best_gcv = gcv
                    best_s = s_try
        s = best_s

    smoothed = _dct_smooth(y, w, s, n)
    return daily_doy, smoothed


def _dct_smooth(y, w, s, n):
    """Core DCT smoothing step."""
    z = y.copy()
    for _ in range(6):  # iteratively reweighted
        wy = w * y + (1 - w) * z
        dct_coeffs = dct(wy, type=2, norm="ortho")
        # Eigenvalues of the penalty matrix
        freq = np.arange(n)
        eig = (2 * (1 - np.cos(np.pi * freq / n))) ** 2
        dct_coeffs = dct_coeffs / (1 + s * eig)
        z = idct(dct_coeffs, type=2, norm="ortho")
    return z


# ===================================================================
# Phenometric extraction
# ===================================================================

def extract_phenometrics(t, y, method="amplitude_threshold", threshold=0.2):
    """Extract SOS, POS, EOS from smoothed time series.

    Methods:
        amplitude_threshold: threshold × amplitude above baseline
        first_derivative: max/min of first derivative
        second_derivative: inflection points
    """
    baseline = np.min(y)
    amplitude = np.max(y) - baseline
    pos_idx = np.argmax(y)
    pos = float(t[pos_idx])

    if amplitude < 0.02:
        return {"SOS": None, "POS": pos, "EOS": None,
                "amplitude": float(amplitude), "method": method}

    if method == "amplitude_threshold":
        thresh_val = baseline + threshold * amplitude
        # SOS: first crossing on rising limb
        rising = y[:pos_idx]
        sos_idx = np.where(rising >= thresh_val)[0]
        sos = float(t[sos_idx[0]]) if len(sos_idx) > 0 else None
        # EOS: last crossing on falling limb
        falling = y[pos_idx:]
        eos_idx = np.where(falling >= thresh_val)[0]
        eos = float(t[pos_idx + eos_idx[-1]]) if len(eos_idx) > 0 else None

    elif method == "first_derivative":
        dy = np.gradient(y, t)
        # SOS = max derivative before peak
        sos_idx = np.argmax(dy[:pos_idx]) if pos_idx > 0 else 0
        sos = float(t[sos_idx])
        # EOS = min derivative after peak
        eos_rel = np.argmin(dy[pos_idx:]) if pos_idx < len(dy) else 0
        eos = float(t[pos_idx + eos_rel])

    elif method == "second_derivative":
        dy = np.gradient(y, t)
        d2y = np.gradient(dy, t)
        # SOS = max of second derivative before peak
        sos_idx = np.argmax(d2y[:pos_idx]) if pos_idx > 0 else 0
        sos = float(t[sos_idx])
        # EOS = max of second derivative after peak (start of rapid decline)
        eos_rel = np.argmax(d2y[pos_idx:]) if pos_idx < len(d2y) else 0
        eos = float(t[pos_idx + eos_rel])

    else:
        sos, eos = None, None

    return {
        "SOS": sos, "POS": pos, "EOS": eos,
        "amplitude": float(amplitude), "method": method,
    }


# ===================================================================
# S2 pixel extraction
# ===================================================================

def extract_pixel_timeseries(lon, lat, start_date, end_date, window_size=1):
    """Extract Sentinel-2 time series for a single pixel."""
    buf = 0.005
    bbox = [lon - buf, lat - buf, lon + buf, lat + buf]

    client = Client.open(STAC_URL)
    search = client.search(
        collections=[COLLECTION],
        bbox=bbox,
        datetime=f"{start_date}/{end_date}",
        max_items=2000,
    )
    items = sorted(search.items(), key=lambda x: x.properties.get("datetime", ""))

    results = []
    proj_coords = None

    for item in items:
        props = item.properties
        date_str = props.get("datetime", "")[:10]
        cloud_cover = props.get("eo:cloud_cover", 100)

        row_data = {
            "date": date_str,
            "cloud_cover": cloud_cover,
            "scene_id": item.id,
        }

        for band_name, asset_key in BAND_ASSETS.items():
            if asset_key not in item.assets:
                row_data[band_name] = None
                continue

            href = item.assets[asset_key].href
            try:
                with rasterio.open(href) as src:
                    if proj_coords is None:
                        t = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
                        px, py = t.transform(lon, lat)
                        proj_coords = (px, py)
                    r, c = src.index(proj_coords[0], proj_coords[1])
                    if 0 <= r < src.height and 0 <= c < src.width:
                        half = window_size // 2
                        r0 = max(0, r - half)
                        c0 = max(0, c - half)
                        r1 = min(src.height, r + half + 1)
                        c1 = min(src.width, c + half + 1)
                        win = Window(c0, r0, c1 - c0, r1 - r0)
                        data = src.read(1, window=win)
                        row_data[band_name] = float(np.mean(data))
                    else:
                        row_data[band_name] = None
            except Exception:
                row_data[band_name] = None
                continue
            # Only read remaining bands from this scene if first band worked
            if row_data.get(band_name) is not None and proj_coords is not None:
                continue

        results.append(row_data)

    return results


# ===================================================================
# Routes
# ===================================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/extract", methods=["POST"])
def api_extract():
    """Extract S2 time series and compute phenology for a clicked pixel."""
    data = request.get_json()
    lon = float(data["lon"])
    lat = float(data["lat"])
    start_date = data.get("start_date", "2018-01-01")
    end_date = data.get("end_date", "2018-12-31")
    smooth_method = data.get("smooth_method", "savgol")
    sg_window = int(data.get("sg_window", 31))
    sg_poly = int(data.get("sg_poly", 3))
    dct_s = data.get("dct_s", None)
    if dct_s is not None:
        dct_s = float(dct_s)
    pheno_method = data.get("pheno_method", "amplitude_threshold")
    threshold = float(data.get("threshold", 0.2))
    window_size = int(data.get("window_size", 3))

    # 1. Extract raw pixel data
    try:
        raw = extract_pixel_timeseries(lon, lat, start_date, end_date, window_size)
    except Exception as e:
        return jsonify({"error": f"Extraction failed: {e}"}), 500

    if not raw:
        return jsonify({"error": "No scenes found for this location/date range"}), 404

    # 2. Compute NDVI and EVI2
    records = []
    for r in raw:
        b04 = r.get("B04")
        b08 = r.get("B08")
        scl = r.get("SCL")
        if b04 is None or b08 is None:
            continue
        red, nir = float(b04), float(b08)
        if (nir + red) > 0:
            ndvi = (nir - red) / (nir + red)
        else:
            ndvi = None
        if (nir + 2.4 * red + 10000) > 0:
            evi2 = 2.5 * (nir - red) / (nir + 2.4 * red + 10000)
        else:
            evi2 = None

        dt = datetime.strptime(r["date"], "%Y-%m-%d")
        doy = dt.timetuple().tm_yday
        scl_val = int(scl) if scl is not None else None
        is_clear = scl_val in SCL_GOOD if scl_val is not None else False

        records.append({
            "date": r["date"],
            "doy": doy,
            "ndvi": ndvi,
            "evi2": evi2,
            "scl": scl_val,
            "is_clear": is_clear,
            "cloud_cover": r.get("cloud_cover"),
            "B02": r.get("B02"), "B03": r.get("B03"),
            "B04": b04, "B08": b08,
        })

    if not records:
        return jsonify({"error": "No valid pixel data extracted"}), 404

    # 3. Filter clear observations for smoothing
    clear = [r for r in records if r["is_clear"] and r["ndvi"] is not None]
    all_obs = [r for r in records if r["ndvi"] is not None]

    if len(clear) < 6:
        # Fall back to all observations
        clear = all_obs

    if len(clear) < 4:
        return jsonify({
            "raw": records,
            "smoothed": None,
            "phenometrics": None,
            "error": "Too few clear observations for smoothing",
        })

    doys = np.array([r["doy"] for r in clear], dtype=float)
    ndvis = np.array([r["ndvi"] for r in clear], dtype=float)

    # Sort by DOY
    order = np.argsort(doys)
    doys = doys[order]
    ndvis = ndvis[order]

    # 4. Smooth
    if smooth_method == "savgol":
        t_smooth, y_smooth = smooth_savgol(doys, ndvis, sg_window, sg_poly)
    elif smooth_method == "dct":
        t_smooth, y_smooth = smooth_dct_garcia(doys, ndvis, dct_s)
    else:
        t_smooth, y_smooth = smooth_savgol(doys, ndvis)

    # 5. Extract phenometrics
    metrics = extract_phenometrics(t_smooth, y_smooth, pheno_method, threshold)

    # 6. Try double logistic fit
    fit_result = None
    try:
        p0 = [np.min(ndvis), np.max(ndvis) - np.min(ndvis), 0.1, 120, 0.1, 270]
        bounds = ([0, 0, 0.001, 1, 0.001, 1], [1, 1, 1.0, 365, 1.0, 365])
        params, _ = curve_fit(double_logistic, doys, ndvis, p0=p0,
                              bounds=bounds, maxfev=5000)
        y_fit = double_logistic(t_smooth, *params)
        fit_result = {
            "t": t_smooth.tolist(),
            "y": y_fit.tolist(),
            "params": params.tolist(),
        }
    except Exception:
        pass

    return jsonify({
        "lon": lon,
        "lat": lat,
        "n_scenes": len(raw),
        "n_clear": len(clear),
        "raw": records,
        "smoothed": {
            "t": t_smooth.tolist(),
            "y": y_smooth.tolist(),
            "method": smooth_method,
        },
        "double_logistic": fit_result,
        "phenometrics": metrics,
    })


@app.route("/api/flevovision_locations")
def flevovision_locations():
    """Return FlevoVision survey locations for the map."""
    import csv
    import struct

    csv_path = ROOT / "data" / "flevovision" / "tf_flevo_toshare.csv"
    if not csv_path.exists():
        return jsonify([])

    from collections import defaultdict
    coords = defaultdict(list)
    codes = {}
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            oid = row["objectid_survey"]
            if oid == "NA":
                continue
            wkb = bytes.fromhex(row["wkb_geometry"])
            bo = '<' if wkb[0] == 1 else '>'
            wtype = struct.unpack(f'{bo}I', wkb[1:5])[0]
            off = 9 if wtype & 0x20000000 else 5
            lon, lat = struct.unpack(f'{bo}dd', wkb[off:off + 16])
            coords[oid].append((lon, lat))
            codes[oid] = row["code_bbch_surveyed"]

    locations = []
    for oid, xy in coords.items():
        lons, lats = zip(*xy)
        locations.append({
            "id": oid,
            "lon": round(float(np.median(lons)), 6),
            "lat": round(float(np.median(lats)), 6),
            "code": codes[oid],
        })
    return jsonify(locations)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    print(f"Starting phenology web tool on http://localhost:{args.port}")
    app.run(host="127.0.0.1", port=args.port, debug=args.debug)

#!/usr/bin/env python3
"""
Phenology Explorer — Flask backend.

Extracts Sentinel-2 time series via STAC/COG (AWS Element84, no credentials),
applies outlier detection, smoothing (Savitzky-Golay or DCT/Garcia), fits
phenological models (double logistic), and streams progress to the frontend.

Usage:
    python webapp/server.py [--port 5001]
    gunicorn webapp.server:app --bind 0.0.0.0:5001 --timeout 300
"""

import argparse
import json
import os
import threading
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

# GDAL env for efficient COG access
os.environ.update({
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF",
    "GDAL_HTTP_MAX_RETRY": "3",
    "GDAL_HTTP_RETRY_DELAY": "2",
})

import numpy as np
from flask import Flask, Response, jsonify, render_template, request, stream_with_context
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

# AWS Element84 Earth Search — free, no credentials needed
STAC_URL = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-l2a"

# Band groups — download only what's needed
NDVI_BANDS = {"B04": "red", "B08": "nir", "SCL": "scl"}
SPECTRAL_BANDS = {"B02": "blue", "B03": "green", "B04": "red", "B08": "nir", "SCL": "scl"}
ALL_BANDS = {
    "B02": "blue", "B03": "green", "B04": "red", "B05": "rededge1",
    "B06": "rededge2", "B07": "rededge3", "B08": "nir", "B8A": "nir08",
    "B11": "swir16", "B12": "swir22", "SCL": "scl",
}

SCL_GOOD = {4, 5}  # vegetation, bare soil

# Max cache entries. Each entry is ~500 bytes (scene metadata + band values).
# 5000 entries ≈ 2.5 MB, holds ~70 full-year extractions.
CACHE_MAX_ENTRIES = 5000


CACHE_DIR = ROOT / "data" / "cache"
CACHE_FILE = CACHE_DIR / "pixel_cache.json"
CACHE_MAX_DISK_MB = 50  # max disk cache size in MB


class LRUCache:
    """Thread-safe LRU cache with disk persistence."""

    def __init__(self, max_entries=CACHE_MAX_ENTRIES, persist_path=None):
        self._cache = OrderedDict()
        self._max = max_entries
        self._lock = threading.Lock()
        self._persist_path = persist_path
        self._dirty = 0  # writes since last save
        self.hits = 0
        self.misses = 0
        if persist_path:
            self._load()

    def _load(self):
        """Load cache from disk."""
        try:
            if self._persist_path and Path(self._persist_path).exists():
                with open(self._persist_path) as f:
                    entries = json.load(f)
                # entries is list of [key_list, value]
                for key_list, value in entries[-self._max :]:
                    self._cache[tuple(tuple(k) if isinstance(k, list) else k for k in key_list)] = value
                print(f"Cache loaded: {len(self._cache)} entries from {self._persist_path}")
        except Exception as e:
            print(f"Cache load failed (starting fresh): {e}")

    def _save(self):
        """Persist cache to disk."""
        if not self._persist_path:
            return
        try:
            Path(self._persist_path).parent.mkdir(parents=True, exist_ok=True)
            data = json.dumps([[list(k), v] for k, v in self._cache.items()])
            # Check size before writing
            size_mb = len(data) / (1024 * 1024)
            if size_mb > CACHE_MAX_DISK_MB:
                # Trim oldest entries to fit
                while len(self._cache) > 10 and len(data) / (1024 * 1024) > CACHE_MAX_DISK_MB:
                    self._cache.popitem(last=False)
                    data = json.dumps([[list(k), v] for k, v in self._cache.items()])
            with open(self._persist_path, "w") as f:
                f.write(data)
        except Exception as e:
            print(f"Cache save failed: {e}")

    def get(self, key):
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self.hits += 1
                return self._cache[key]
            self.misses += 1
            return None

    def put(self, key, value):
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = value
            else:
                while len(self._cache) >= self._max:
                    self._cache.popitem(last=False)
                self._cache[key] = value
            self._dirty += 1
            # Auto-save every 20 new entries
            if self._dirty >= 20:
                self._dirty = 0
                self._save()

    def flush(self):
        """Force save to disk."""
        with self._lock:
            self._save()
            self._dirty = 0

    @property
    def size(self):
        return len(self._cache)


pixel_cache = LRUCache(persist_path=CACHE_FILE)


def _json_line(type, **kwargs):
    """Format a single NDJSON line for streaming."""
    return json.dumps({"type": type, **kwargs}, default=_np_enc) + "\n"


def _np_enc(obj):
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Not serializable: {type(obj)}")


# ===================================================================
# Outlier detection
# ===================================================================

def detect_outliers(doys, ndvis, method="mad", z_threshold=3.5):
    """Detect outliers in NDVI time series.

    Methods:
        mad: Modified Z-score via Median Absolute Deviation
        iqr: Interquartile Range
        temporal: Deviation from temporal neighborhood median

    Returns boolean mask (True = outlier).
    """
    n = len(ndvis)
    mask = np.zeros(n, dtype=bool)

    # Physical bounds — always applied
    mask |= (ndvis < -0.2) | (ndvis > 1.0)

    if method == "mad":
        median = np.median(ndvis)
        mad = np.median(np.abs(ndvis - median))
        if mad > 1e-6:
            modified_z = 0.6745 * (ndvis - median) / mad
            mask |= np.abs(modified_z) > z_threshold

    elif method == "iqr":
        q1, q3 = np.percentile(ndvis, [25, 75])
        iqr = q3 - q1
        mask |= (ndvis < q1 - 1.5 * iqr) | (ndvis > q3 + 1.5 * iqr)

    elif method == "temporal":
        for i in range(n):
            nearby = np.abs(doys - doys[i]) < 30
            nearby[i] = False
            if np.sum(nearby) >= 2:
                local_med = np.median(ndvis[nearby])
                local_mad = np.median(np.abs(ndvis[nearby] - local_med))
                if local_mad > 1e-6:
                    z = 0.6745 * abs(ndvis[i] - local_med) / local_mad
                    mask[i] = z > z_threshold

    return mask


# ===================================================================
# Phenological models
# ===================================================================

def double_logistic(t, a1, a2, a3, a4, a5, a6):
    """Beck et al. (2006) double logistic."""
    return a1 + a2 * (
        1.0 / (1.0 + np.exp(-a3 * (t - a4)))
        - 1.0 / (1.0 + np.exp(-a5 * (t - a6)))
    )


def fit_double_logistic_iterative(doys, ndvis, n_iter=3):
    """Iterative double logistic fitting with robust initial estimates.

    Pass 1: Estimate params from data percentiles + gradient analysis.
    Pass 2+: Reweight by residuals (Huber-like) and refit.
    """
    baseline = float(np.percentile(ndvis, 10))
    peak = float(np.percentile(ndvis, 90))
    amplitude = max(peak - baseline, 0.05)

    # Approximate greenup/senescence DOYs from gradient of interpolated data
    daily_doy = np.arange(int(doys.min()), int(doys.max()) + 1)
    daily_ndvi = np.interp(daily_doy, doys, ndvis)
    if len(daily_ndvi) > 5:
        sg_win = min(15, len(daily_ndvi) // 2 * 2 + 1)
        if sg_win >= 5:
            grad = np.gradient(savgol_filter(daily_ndvi, sg_win, 2))
        else:
            grad = np.gradient(daily_ndvi)
        greenup_doy = float(daily_doy[np.argmax(grad)])
        senescence_doy = float(daily_doy[np.argmin(grad)])
    else:
        greenup_doy = float(doys.min() + (doys.max() - doys.min()) * 0.3)
        senescence_doy = float(doys.min() + (doys.max() - doys.min()) * 0.7)

    if senescence_doy <= greenup_doy:
        senescence_doy = greenup_doy + 60

    p0 = [baseline, amplitude, 0.08, greenup_doy, 0.08, senescence_doy]
    lo = [max(baseline - 0.3, -0.5), 0.01, 0.005, max(doys.min() - 30, 1),
          0.005, max(doys.min() - 30, 1)]
    hi = [min(baseline + 0.3, 1.0), 1.5, 2.0, min(doys.max() + 30, 400),
          2.0, min(doys.max() + 30, 400)]

    weights = np.ones_like(ndvis)
    best_params = None
    best_rmse = np.inf
    fit_info = []

    for iteration in range(n_iter):
        try:
            params, _ = curve_fit(
                double_logistic, doys, ndvis, p0=p0,
                bounds=(lo, hi),
                sigma=1.0 / np.maximum(weights, 0.1),
                maxfev=10000,
            )
            fitted = double_logistic(doys, *params)
            residuals = ndvis - fitted
            rmse = float(np.sqrt(np.mean(residuals ** 2)))
            fit_info.append({"iteration": iteration + 1, "rmse": round(rmse, 5)})

            if rmse < best_rmse:
                best_rmse = rmse
                best_params = params.copy()

            # Huber-like reweighting
            mad_r = np.median(np.abs(residuals))
            if mad_r > 1e-6:
                weights = np.where(
                    np.abs(residuals) > 2 * mad_r,
                    mad_r / np.maximum(np.abs(residuals), 1e-6),
                    1.0,
                )
            p0 = params.tolist()
        except Exception as e:
            fit_info.append({"iteration": iteration + 1, "error": str(e)})
            break

    return best_params, best_rmse, fit_info


# ===================================================================
# Smoothing filters
# ===================================================================

def smooth_savgol(doys, values, window=31, poly=3):
    daily_doy = np.arange(1, 366)
    daily_vals = np.interp(daily_doy, doys, values)
    win = min(window, len(daily_vals))
    if win % 2 == 0:
        win -= 1
    win = max(win, poly + 2)
    return daily_doy, savgol_filter(daily_vals, win, poly)


def smooth_dct_garcia(doys, values, s=None):
    daily_doy = np.arange(1, 366)
    y = np.interp(daily_doy, doys, values)
    n = len(y)

    w = np.zeros(n)
    for d in doys:
        idx = int(d) - 1
        if 0 <= idx < n:
            w[idx] = 1.0
    w = uniform_filter1d(w.astype(float), size=5)
    w = np.clip(w, 0.1, 1.0)

    if s is None:
        best_s, best_gcv = 1.0, np.inf
        for log_s in np.linspace(-2, 6, 50):
            s_try = 10 ** log_s
            z = _dct_smooth(y, w, s_try, n)
            rss = np.sum((w * (y - z)) ** 2)
            gamma = 1.0 / (1.0 + s_try * (2 * np.arange(n) * np.pi / n) ** 2)
            denom = (1.0 - np.sum(gamma) / n) ** 2
            if denom > 0:
                gcv = rss / n / denom
                if gcv < best_gcv:
                    best_gcv = gcv
                    best_s = s_try
        s = best_s

    return daily_doy, _dct_smooth(y, w, s, n)


def _dct_smooth(y, w, s, n):
    z = y.copy()
    for _ in range(6):
        wy = w * y + (1 - w) * z
        coeffs = dct(wy, type=2, norm="ortho")
        eig = (2 * (1 - np.cos(np.pi * np.arange(n) / n))) ** 2
        z = idct(coeffs / (1 + s * eig), type=2, norm="ortho")
    return z


# ===================================================================
# Phenometric extraction
# ===================================================================

def extract_phenometrics(t, y, method="amplitude_threshold", threshold=0.2):
    baseline = np.min(y)
    amplitude = np.max(y) - baseline
    pos_idx = np.argmax(y)
    pos = float(t[pos_idx])

    if amplitude < 0.02:
        return {"SOS": None, "POS": pos, "EOS": None,
                "amplitude": float(amplitude), "method": method}

    sos, eos = None, None

    if method == "amplitude_threshold":
        thresh_val = baseline + threshold * amplitude
        rising = y[:pos_idx]
        sos_idx = np.where(rising >= thresh_val)[0]
        sos = float(t[sos_idx[0]]) if len(sos_idx) > 0 else None
        falling = y[pos_idx:]
        eos_idx = np.where(falling >= thresh_val)[0]
        eos = float(t[pos_idx + eos_idx[-1]]) if len(eos_idx) > 0 else None

    elif method == "first_derivative":
        dy = np.gradient(y, t)
        sos = float(t[np.argmax(dy[:pos_idx])]) if pos_idx > 0 else None
        eos_rel = np.argmin(dy[pos_idx:]) if pos_idx < len(dy) else 0
        eos = float(t[pos_idx + eos_rel])

    elif method == "second_derivative":
        dy = np.gradient(y, t)
        d2y = np.gradient(dy, t)
        sos = float(t[np.argmax(d2y[:pos_idx])]) if pos_idx > 0 else None
        eos_rel = np.argmax(d2y[pos_idx:]) if pos_idx < len(d2y) else 0
        eos = float(t[pos_idx + eos_rel])

    return {"SOS": sos, "POS": pos, "EOS": eos,
            "amplitude": float(amplitude), "method": method}


# ===================================================================
# Streaming S2 extraction
# ===================================================================

def extract_scenes_streaming(lon, lat, start_date, end_date, window_size, bands):
    """Generator yielding per-scene pixel data with progress."""
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

    band_key = tuple(sorted(bands.keys()))
    yield {
        "type": "stac_done",
        "n_scenes": len(items),
        "n_bands": len(bands),
        "cache_size": pixel_cache.size,
    }

    proj_coords = None

    for i, item in enumerate(items):
        t0 = time.time()
        props = item.properties
        date_str = props.get("datetime", "")[:10]
        cloud_cover = props.get("eo:cloud_cover", 100)

        # Check cache
        cache_key = (item.id, round(lon, 5), round(lat, 5), window_size, band_key)
        cached = pixel_cache.get(cache_key)
        if cached is not None:
            yield {
                "type": "scene_done",
                "index": i, "total": len(items),
                "date": date_str,
                "elapsed": 0.0,
                "data": cached,
                "cached": True,
            }
            continue

        row_data = {"date": date_str, "cloud_cover": cloud_cover, "scene_id": item.id}

        for band_name, asset_key in bands.items():
            if asset_key not in item.assets:
                row_data[band_name] = None
                continue
            href = item.assets[asset_key].href
            try:
                with rasterio.open(href) as src:
                    if proj_coords is None:
                        tr = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
                        px, py = tr.transform(lon, lat)
                        proj_coords = (px, py)
                    r, c = src.index(proj_coords[0], proj_coords[1])
                    if 0 <= r < src.height and 0 <= c < src.width:
                        half = window_size // 2
                        r0, c0 = max(0, r - half), max(0, c - half)
                        r1, c1 = min(src.height, r + half + 1), min(src.width, c + half + 1)
                        data = src.read(1, window=Window(c0, r0, c1 - c0, r1 - r0))
                        row_data[band_name] = float(np.mean(data))
                    else:
                        row_data[band_name] = None
            except Exception:
                row_data[band_name] = None

        pixel_cache.put(cache_key, row_data)

        yield {
            "type": "scene_done",
            "index": i, "total": len(items),
            "date": date_str,
            "elapsed": round(time.time() - t0, 1),
            "data": row_data,
            "cached": False,
        }


# ===================================================================
# Routes
# ===================================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/datasets")
def datasets_page():
    return render_template("datasets.html")


@app.route("/datasets/analysis")
def datasets_analysis_page():
    return render_template("datasets_analysis.html")


@app.route("/api/extract", methods=["POST"])
def api_extract():
    """Stream extraction progress and results as NDJSON."""
    data = request.get_json()
    if not data or "lon" not in data or "lat" not in data:
        return jsonify({"error": "lon and lat required"}), 400
    lon = float(data["lon"])
    lat = float(data["lat"])
    start_date = data.get("start_date", "2018-01-01")
    end_date = data.get("end_date", "2018-12-31")
    smooth_method = data.get("smooth_method", "savgol")
    sg_window = int(data.get("sg_window", 31))
    sg_poly = int(data.get("sg_poly", 3))
    dct_s = data.get("dct_s")
    if dct_s is not None:
        dct_s = float(dct_s)
    pheno_method = data.get("pheno_method", "amplitude_threshold")
    threshold = float(data.get("threshold", 0.2))
    window_size = int(data.get("window_size", 3))
    band_mode = data.get("band_mode", "ndvi")
    outlier_method = data.get("outlier_method", "mad")
    outlier_threshold = float(data.get("outlier_threshold", 3.5))
    fit_method = data.get("fit_method", "both")  # 'smooth', 'double_logistic', 'both'
    dl_iterations = int(data.get("dl_iterations", 3))
    pheno_source = data.get("pheno_source", "smooth")  # 'smooth' or 'dl'

    bands = {"ndvi": NDVI_BANDS, "spectral": SPECTRAL_BANDS, "all": ALL_BANDS}.get(
        band_mode, NDVI_BANDS
    )

    def generate():
        t_start = time.time()
        yield _json_line("status", msg="Querying STAC catalog...")

        raw_records = []
        try:
            for event in extract_scenes_streaming(
                lon, lat, start_date, end_date, window_size, bands
            ):
                if event["type"] == "stac_done":
                    n, nb = event["n_scenes"], event["n_bands"]
                    cs = event.get("cache_size", 0)
                    yield _json_line(
                        "status",
                        msg=f"Found {n} scenes. Downloading {nb} bands/scene (cache: {cs} entries)...",
                    )
                    yield _json_line("stac_done", n_scenes=n)
                elif event["type"] == "scene_done":
                    raw_records.append(event["data"])
                    # Compute NDVI on the fly for live plotting
                    rd = event["data"]
                    b04, b08 = rd.get("B04"), rd.get("B08")
                    live_ndvi = None
                    if b04 is not None and b08 is not None:
                        s = float(b08) + float(b04)
                        if s > 0:
                            live_ndvi = (float(b08) - float(b04)) / s
                    scl_val = int(rd["SCL"]) if rd.get("SCL") is not None else None
                    yield _json_line(
                        "progress",
                        current=event["index"] + 1,
                        total=event["total"],
                        date=event["date"],
                        elapsed=event["elapsed"],
                        cached=event.get("cached", False),
                        ndvi=live_ndvi,
                        scl=scl_val,
                    )
        except Exception as e:
            yield _json_line("error", msg=f"Extraction failed: {e}")
            pixel_cache.flush()
            return

        pixel_cache.flush()  # persist downloaded data to disk

        if not raw_records:
            yield _json_line("error", msg="No scenes found")
            return

        yield _json_line("status", msg="Computing NDVI...")

        # Compute NDVI / EVI2
        records = []
        for r in raw_records:
            b04, b08, scl = r.get("B04"), r.get("B08"), r.get("SCL")
            if b04 is None or b08 is None:
                continue
            red, nir = float(b04), float(b08)
            ndvi = (nir - red) / (nir + red) if (nir + red) > 0 else None
            evi2 = (
                2.5 * (nir - red) / (nir + 2.4 * red + 10000)
                if (nir + 2.4 * red + 10000) > 0
                else None
            )
            dt = datetime.strptime(r["date"], "%Y-%m-%d")
            scl_val = int(scl) if scl is not None else None
            rec = {
                "date": r["date"],
                "doy": dt.timetuple().tm_yday,
                "ndvi": ndvi,
                "evi2": evi2,
                "scl": scl_val,
                "is_clear": scl_val in SCL_GOOD if scl_val is not None else False,
                "cloud_cover": r.get("cloud_cover"),
                "B04": b04,
                "B08": b08,
                "is_outlier": False,
            }
            if "B02" in r:
                rec["B02"] = r.get("B02")
            if "B03" in r:
                rec["B03"] = r.get("B03")
            records.append(rec)

        if not records:
            yield _json_line("error", msg="No valid pixel data")
            return

        # Filter clear observations
        clear = [r for r in records if r["is_clear"] and r["ndvi"] is not None]
        if len(clear) < 6:
            clear = [r for r in records if r["ndvi"] is not None]

        if len(clear) < 4:
            yield _json_line(
                "result",
                data={
                    "raw": records,
                    "smoothed": None,
                    "phenometrics": None,
                    "double_logistic": None,
                    "n_scenes": len(raw_records),
                    "n_clear": len(clear),
                    "outliers_removed": 0,
                },
            )
            return

        doys = np.array([r["doy"] for r in clear], dtype=float)
        ndvis = np.array([r["ndvi"] for r in clear], dtype=float)
        order = np.argsort(doys)
        doys, ndvis = doys[order], ndvis[order]

        # Outlier detection
        n_outliers = 0
        outlier_doys, outlier_ndvis = [], []
        if outlier_method != "none":
            yield _json_line("status", msg=f"Detecting outliers ({outlier_method})...")
            omask = detect_outliers(doys, ndvis, outlier_method, outlier_threshold)
            n_outliers = int(np.sum(omask))

            # Mark outliers in clear records for frontend display
            clear_sorted = [clear[j] for j in order]
            for j, is_out in enumerate(omask):
                clear_sorted[j]["is_outlier"] = bool(is_out)

            if n_outliers > 0:
                outlier_doys = doys[omask].tolist()
                outlier_ndvis = ndvis[omask].tolist()
                if len(doys) - n_outliers >= 4:
                    doys, ndvis = doys[~omask], ndvis[~omask]
                    yield _json_line(
                        "status",
                        msg=f"Removed {n_outliers} outliers, {len(doys)} remain",
                    )

        # Smooth (always compute for interpolation base, even if not displayed)
        t_smooth = np.arange(1, 366)
        smooth_result = None
        if fit_method in ("smooth", "both"):
            yield _json_line("status", msg=f"Smoothing ({smooth_method})...")
            if smooth_method == "dct":
                t_smooth, y_smooth = smooth_dct_garcia(doys, ndvis, dct_s)
            else:
                t_smooth, y_smooth = smooth_savgol(doys, ndvis, sg_window, sg_poly)
            smooth_result = {
                "t": t_smooth.tolist(),
                "y": y_smooth.tolist(),
                "method": smooth_method,
            }
        else:
            # Still need a smoothed curve for DL initial param estimation
            _, y_smooth = smooth_savgol(doys, ndvis, sg_window, sg_poly)

        # Double logistic fit
        fit_result = None
        if fit_method in ("double_logistic", "both"):
            yield _json_line(
                "status",
                msg=f"Fitting double logistic ({dl_iterations} iterations)...",
            )
            dl_params, dl_rmse, dl_info = fit_double_logistic_iterative(
                doys, ndvis, dl_iterations
            )
            if dl_params is not None:
                y_fit = double_logistic(t_smooth, *dl_params)
                fit_result = {
                    "t": t_smooth.tolist(),
                    "y": y_fit.tolist(),
                    "params": dl_params.tolist(),
                    "rmse": dl_rmse,
                    "iterations": dl_info,
                }

        # Phenometrics — extract from chosen source
        yield _json_line("status", msg="Extracting phenometrics...")
        if pheno_source == "dl" and fit_result is not None:
            y_for_pheno = np.array(fit_result["y"])
        else:
            y_for_pheno = y_smooth
        metrics = extract_phenometrics(t_smooth, y_for_pheno, pheno_method, threshold)

        elapsed = round(time.time() - t_start, 1)
        yield _json_line("status", msg=f"Done in {elapsed}s")
        yield _json_line(
            "result",
            data={
                "lon": lon,
                "lat": lat,
                "n_scenes": len(raw_records),
                "n_clear": len(clear),
                "outliers_removed": n_outliers,
                "outlier_doys": outlier_doys,
                "outlier_ndvis": outlier_ndvis,
                "raw": records,
                "smoothed": smooth_result,
                "double_logistic": fit_result,
                "phenometrics": metrics,
                "elapsed": elapsed,
            },
        )

    return Response(
        stream_with_context(generate()),
        mimetype="application/x-ndjson",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.route("/api/flevovision_locations")
def flevovision_locations():
    import csv
    import struct
    from collections import defaultdict

    csv_path = ROOT / "data" / "flevovision" / "tf_flevo_toshare.csv"
    if not csv_path.exists():
        return jsonify([])

    coords = defaultdict(list)
    codes = {}
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            oid = row["objectid_survey"]
            if oid == "NA":
                continue
            wkb = bytes.fromhex(row["wkb_geometry"])
            bo = "<" if wkb[0] == 1 else ">"
            wtype = struct.unpack(f"{bo}I", wkb[1:5])[0]
            off = 9 if wtype & 0x20000000 else 5
            lon, lat = struct.unpack(f"{bo}dd", wkb[off : off + 16])
            coords[oid].append((lon, lat))
            codes[oid] = row["code_bbch_surveyed"]

    locations = []
    for oid, xy in coords.items():
        lons, lats = zip(*xy)
        locations.append(
            {
                "id": oid,
                "lon": round(float(np.median(lons)), 6),
                "lat": round(float(np.median(lats)), 6),
                "code": codes[oid],
            }
        )
    return jsonify(locations)


BBCH_STAGES = {
    0: "Germination", 1: "Germination", 2: "Germination", 3: "Germination",
    5: "Germination", 7: "Germination", 9: "Emergence",
    10: "Leaf dev", 11: "1st leaf", 12: "2nd leaf", 13: "3rd leaf",
    14: "4th leaf", 15: "5th leaf", 19: "9+ leaves",
    21: "Tillering start", 25: "5 tillers", 29: "Max tillers",
    30: "Stem elong", 31: "1st node", 32: "2nd node", 37: "Flag leaf",
    39: "Flag leaf ligule",
    41: "Booting start", 45: "Late boot", 49: "Heading start",
    51: "Inflorescence", 55: "Mid heading", 59: "Full heading",
    61: "Flowering start", 65: "Mid flowering", 69: "End flowering",
    71: "Grain water", 73: "Early milk", 75: "Medium milk",
    77: "Late milk", 83: "Early dough", 85: "Soft dough", 87: "Hard dough",
    89: "Fully ripe", 92: "Over-ripe", 97: "Dead/harvest", 99: "Harvest",
}

# Crop code mapping
CROP_CODES = {
    "BSO": "Bare soil", "WTW": "Winter wheat", "SBT": "Sugar beet",
    "GRS": "Grass", "ONI": "Onion", "MZE": "Maize", "PTT": "Potato",
    "WBY": "Winter barley", "SBY": "Spring barley", "FLX": "Flax",
    "PES": "Peas", "WRP": "Winter rapeseed", "TLP": "Tulip",
}


@app.route("/api/validation_data")
def api_validation_data():
    """Return ground-truth phenology observations near a given location.

    Query params: lon, lat, radius (degrees, default 0.001 ~100m),
                  start_date, end_date
    """
    import csv
    import struct
    from collections import defaultdict

    lon = float(request.args.get("lon", 0))
    lat = float(request.args.get("lat", 0))
    radius = float(request.args.get("radius", 0.002))
    start_date = request.args.get("start_date", "2000-01-01")
    end_date = request.args.get("end_date", "2099-12-31")

    results = []

    # --- FlevoVision BBCH data ---
    csv_path = ROOT / "data" / "flevovision" / "tf_flevo_toshare.csv"
    if csv_path.exists():
        seen = set()
        with open(csv_path, newline="") as f:
            for row in csv.DictReader(f):
                oid = row.get("objectid_survey", "")
                if oid == "NA" or not oid:
                    continue
                # Parse location
                try:
                    wkb = bytes.fromhex(row["wkb_geometry"])
                    bo = "<" if wkb[0] == 1 else ">"
                    wtype = struct.unpack(f"{bo}I", wkb[1:5])[0]
                    off = 9 if wtype & 0x20000000 else 5
                    rlon, rlat = struct.unpack(f"{bo}dd", wkb[off : off + 16])
                except Exception:
                    continue

                if abs(rlon - lon) > radius or abs(rlat - lat) > radius:
                    continue

                obs_time = row.get("observation_time", "")[:10]
                if obs_time < start_date or obs_time > end_date:
                    continue

                bbch = row.get("bbch", "").strip()
                crop = row.get("code_surveyed", "").strip()
                code = row.get("code_bbch_surveyed", "").strip()

                dedup_key = (oid, obs_time, bbch)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                try:
                    bbch_int = int(bbch)
                except ValueError:
                    bbch_int = None

                dt = datetime.strptime(obs_time, "%Y-%m-%d")
                doy = dt.timetuple().tm_yday

                results.append({
                    "source": "FlevoVision",
                    "date": obs_time,
                    "doy": doy,
                    "bbch": bbch_int,
                    "bbch_desc": BBCH_STAGES.get(bbch_int, f"BBCH {bbch}"),
                    "crop_code": crop,
                    "crop_name": CROP_CODES.get(crop, crop),
                    "code": code,
                    "site_id": oid,
                })

    # --- DWD phenology data (find nearest station) ---
    dwd_dir = ROOT / "data" / "dwd_phenology"
    if dwd_dir.exists():
        # DWD phase IDs for key crop stages
        dwd_phases = {
            5: "Sowing", 10: "Emergence", 12: "Leaf dev",
            15: "Heading", 18: "Flowering", 19: "Milk ripeness",
            21: "Yellow ripeness", 24: "Harvest",
        }
        for f in dwd_dir.glob("PH_Jahresmelder_*.txt"):
            crop_name = f.stem.split("Kulturpflanze_")[-1].replace("_akt", "")
            try:
                with open(f, encoding="latin-1") as fh:
                    header = fh.readline().strip().split(";")
                    header = [h.strip() for h in header]
                    for line in fh:
                        parts = [p.strip() for p in line.strip().split(";")]
                        if len(parts) < len(header):
                            continue
                        rec = dict(zip(header, parts))
                        try:
                            slat = float(rec.get("geograph.Breite", "0"))
                            slon = float(rec.get("geograph.Laenge", "0"))
                        except ValueError:
                            continue
                        # Check proximity (DWD stations are sparse, use wider radius)
                        if abs(slon - lon) > 0.5 or abs(slat - lat) > 0.5:
                            continue
                        date_str = rec.get("Eintrittsdatum", "")
                        if len(date_str) != 8:
                            continue
                        try:
                            dt = datetime.strptime(date_str, "%Y%m%d")
                        except ValueError:
                            continue
                        iso_date = dt.strftime("%Y-%m-%d")
                        if iso_date < start_date or iso_date > end_date:
                            continue
                        phase_id = int(rec.get("Phase_id", 0))
                        results.append({
                            "source": "DWD",
                            "date": iso_date,
                            "doy": dt.timetuple().tm_yday,
                            "bbch": None,
                            "bbch_desc": dwd_phases.get(phase_id, f"Phase {phase_id}"),
                            "crop_code": crop_name,
                            "crop_name": crop_name,
                            "code": f"DWD-{phase_id}",
                            "site_id": rec.get("Stations_id", ""),
                        })
            except Exception:
                continue

    # --- SenSeCo Bulgaria/France in-situ crop phenology ---
    senseco_file = ROOT / "data" / "senseco_phenology" / "insitu_phenology.txt"
    if senseco_file.exists():
        try:
            with open(senseco_file, newline="", encoding="latin-1") as f:
                # Skip comment lines
                lines = [l for l in f if not l.startswith("#")]
            if lines:
                import io
                reader = csv.DictReader(io.StringIO("".join(lines)))
                for row in reader:
                    try:
                        slat = float(row.get("latitude", "0"))
                        slon = float(row.get("longitude", "0"))
                    except (ValueError, TypeError):
                        continue
                    if abs(slon - lon) > radius or abs(slat - lat) > radius:
                        continue
                    pheno = row.get("phenophase", "")
                    pheno_date = row.get("phenophase_date", "")
                    if not pheno_date or pheno_date < start_date or pheno_date > end_date:
                        continue
                    # Extract BBCH number from e.g. "BBCH12"
                    bbch_int = None
                    if pheno.startswith("BBCH"):
                        try:
                            bbch_int = int(pheno[4:])
                        except ValueError:
                            pass
                    try:
                        dt = datetime.strptime(pheno_date, "%Y-%m-%d")
                        doy = dt.timetuple().tm_yday
                    except ValueError:
                        doy = None
                    results.append({
                        "source": "SenSeCo",
                        "date": pheno_date,
                        "doy": doy,
                        "bbch": bbch_int,
                        "bbch_desc": BBCH_STAGES.get(bbch_int, pheno),
                        "crop_code": row.get("crop_type", ""),
                        "crop_name": row.get("crop_type", "").replace("_", " ").title(),
                        "code": pheno,
                        "site_id": row.get("plot_ID", ""),
                    })
        except Exception:
            pass

    # --- Kenya Helmets crop type (not phenology stages, but crop presence) ---
    kenya_csv = ROOT / "data" / "kenya_helmets" / "Helmets_Kenya_v2.csv"
    if kenya_csv.exists():
        try:
            with open(kenya_csv, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        klat = float(row.get("latitude", "0"))
                        klon = float(row.get("longitude", "0"))
                    except (ValueError, TypeError):
                        continue
                    if abs(klon - lon) > radius or abs(klat - lat) > radius:
                        continue
                    crop = row.get("crop_type", "unknown")
                    capture_time = row.get("capture_time", "")[:10]
                    try:
                        dt = datetime.strptime(capture_time, "%Y-%m-%d")
                        doy = dt.timetuple().tm_yday
                    except (ValueError, TypeError):
                        doy = None
                    results.append({
                        "source": "Kenya Helmets",
                        "date": capture_time,
                        "doy": doy,
                        "bbch": None,
                        "bbch_desc": f"Crop: {crop}",
                        "crop_code": crop,
                        "crop_name": crop,
                        "code": "crop_type",
                        "site_id": row.get("image_path", ""),
                    })
        except Exception:
            pass

    # Sort by DOY
    results.sort(key=lambda x: (x["doy"] or 0))
    return jsonify(results)


@app.route("/api/phenocam_locations")
def phenocam_locations():
    """Return PhenoCam agriculture site locations parsed from CSV headers."""
    phenocam_dir = ROOT / "data" / "phenocam"
    if not phenocam_dir.exists():
        return jsonify([])

    locations = []
    seen = set()
    for f in phenocam_dir.glob("*_1day.csv"):
        site_name = f.stem.rsplit("_", 2)[0]
        if site_name in seen:
            continue
        lat_val, lon_val, veg_type = None, None, None
        try:
            with open(f) as fh:
                for line in fh:
                    if not line.startswith("#"):
                        break
                    if line.startswith("# Lat:"):
                        lat_val = float(line.split(":")[1].strip())
                    elif line.startswith("# Lon:"):
                        lon_val = float(line.split(":")[1].strip())
                    elif line.startswith("# Veg Type:"):
                        veg_type = line.split(":")[1].strip()
            if lat_val is not None and lon_val is not None:
                seen.add(site_name)
                locations.append({
                    "id": site_name,
                    "lat": lat_val,
                    "lon": lon_val,
                    "code": veg_type or "AG",
                    "source": "phenocam",
                })
        except Exception:
            continue
    return jsonify(locations)


@app.route("/api/dwd_locations")
def dwd_locations():
    """Return unique DWD station locations from station metadata file."""
    stations_file = ROOT / "data" / "dwd_phenology" / "stations.txt"
    if not stations_file.exists():
        return jsonify([])

    locations = []
    try:
        with open(stations_file, encoding="latin-1") as fh:
            header = [h.strip() for h in fh.readline().strip().split(";")]
            id_idx = header.index("Stations_id")
            lat_col = [h for h in header if "Breite" in h]
            lon_col = [h for h in header if "Laenge" in h]
            name_col = [h for h in header if "Stationsname" in h]
            if not lat_col or not lon_col:
                return jsonify([])
            lat_idx = header.index(lat_col[0])
            lon_idx = header.index(lon_col[0])
            name_idx = header.index(name_col[0]) if name_col else None

            for line in fh:
                parts = line.strip().split(";")
                if len(parts) <= max(id_idx, lat_idx, lon_idx):
                    continue
                try:
                    sid = parts[id_idx].strip()
                    slat = float(parts[lat_idx].strip())
                    slon = float(parts[lon_idx].strip())
                    name = parts[name_idx].strip() if name_idx is not None else sid
                    if 47 < slat < 56 and 5 < slon < 16:
                        locations.append({
                            "id": sid,
                            "lat": slat,
                            "lon": slon,
                            "code": name[:30],
                            "source": "dwd",
                        })
                except (ValueError, IndexError):
                    continue
    except Exception:
        pass
    return jsonify(locations)


@app.route("/api/check_cache")
def api_check_cache():
    """Check how many scenes are cached for a location."""
    lon = float(request.args.get("lon", 0))
    lat = float(request.args.get("lat", 0))
    count = 0
    rlon, rlat = round(lon, 5), round(lat, 5)
    with pixel_cache._lock:
        for key in pixel_cache._cache:
            if len(key) >= 3 and key[1] == rlon and key[2] == rlat:
                count += 1
    return jsonify({"cached_scenes": count, "lon": lon, "lat": lat})


@app.route("/api/dataset_locations/<dataset_id>")
def dataset_locations(dataset_id):
    """Return locations for any dataset from validation_locations.csv."""
    import csv

    csv_path = ROOT / "data" / "validation_locations.csv"
    if not csv_path.exists():
        return jsonify([])

    seen = set()
    locations = []
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            if row["dataset"] != dataset_id:
                continue
            lid = row["location_id"]
            if lid in seen:
                continue
            seen.add(lid)
            try:
                lat = float(row["lat"])
                lon = float(row["lon"])
            except (ValueError, TypeError):
                continue
            locations.append({
                "id": lid,
                "lat": lat,
                "lon": lon,
                "code": row.get("crop_type", lid),
            })
    return jsonify(locations)


@app.route("/api/datasets")
def api_datasets():
    """Available phenology datasets and their status."""
    return jsonify(
        [
            {
                "id": "sentinel2_live",
                "name": "Sentinel-2 L2A (live)",
                "region": "Global",
                "source": "AWS Element84 STAC",
                "desc": "Click map to extract 10m S2 time series on-demand from COGs.",
                "available": True,
                "type": "satellite",
            },
            {
                "id": "flevovision",
                "name": "FlevoVision",
                "region": "Flevoland, NL",
                "source": "D'Andrimont et al. (2022)",
                "desc": "259 crop sites with BBCH ground truth phenology stages.",
                "available": (ROOT / "data" / "flevovision" / "tf_flevo_toshare.csv").exists(),
                "type": "ground_truth",
            },
            {
                "id": "eurocropsml",
                "name": "EuroCropsML",
                "region": "Europe",
                "source": "Zenodo (Schneider et al.)",
                "desc": "706K parcels, full-year S2 13-band time series, 176 crop classes.",
                "available": (ROOT / "data" / "eurocropsml").is_dir(),
                "type": "satellite_archive",
            },
            {
                "id": "dwd_phenology",
                "name": "DWD Germany",
                "region": "Germany",
                "source": "opendata.dwd.de (free, open)",
                "desc": "1200 stations, 160 phenophases of crops, fruit, wild plants. No login.",
                "available": (ROOT / "data" / "dwd_phenology").is_dir(),
                "type": "ground_truth",
            },
            {
                "id": "phenocam",
                "name": "PhenoCam",
                "region": "N. America / Global",
                "source": "phenocam.nau.edu",
                "desc": "Camera-derived GCC vegetation greenness time series, 738 sites.",
                "available": (ROOT / "data" / "phenocam").is_dir(),
                "type": "camera",
            },
            {
                "id": "usa_npn",
                "name": "USA-NPN",
                "region": "USA",
                "source": "usanpn.org (free)",
                "desc": "Citizen science phenology: flowering, leafout dates for crops and trees.",
                "available": (ROOT / "data" / "usa_npn").is_dir(),
                "type": "ground_truth",
            },
            {
                "id": "plantwatch",
                "name": "PlantWatch Canada",
                "region": "Canada",
                "source": "naturewatch.ca (free)",
                "desc": "57K+ observations of spring flowering and leafout dates.",
                "available": (ROOT / "data" / "plantwatch").is_dir(),
                "type": "ground_truth",
            },
            {
                "id": "pep725",
                "name": "PEP725",
                "region": "Europe (46 countries)",
                "source": "pep725.eu (free registration)",
                "desc": "13M+ phenological records, 265 species, 1868-present. Crops included.",
                "available": (ROOT / "data" / "pep725").is_dir(),
                "type": "ground_truth",
            },
            {
                "id": "senseco",
                "name": "SenSeCo (Bulgaria & France)",
                "region": "Bulgaria + France",
                "source": '<a href="https://zenodo.org/records/8067432">Zenodo</a> (CC-BY 4.0)',
                "desc": "In-situ BBCH crop phenology with sowing/harvest dates. Rapeseed, wheat, sunflower.",
                "available": (ROOT / "data" / "senseco_phenology" / "insitu_phenology.txt").exists(),
                "type": "ground_truth",
            },
            {
                "id": "kenya_helmets",
                "name": "Kenya Helmets Crop Type",
                "region": "Kenya (16 counties)",
                "source": '<a href="https://zenodo.org/records/15467063">Zenodo</a> (CC-BY-SA 4.0)',
                "desc": '6K+ georeferenced crop type points (2021-22). <a href="https://doi.org/10.1038/s41597-025-05762-7">Paper</a>.',
                "available": (ROOT / "data" / "kenya_helmets" / "Helmets_Kenya_v2.csv").exists(),
                "type": "ground_truth",
            },
            {
                "id": "china_maize",
                "name": "NE China Maize Phenology",
                "region": "NE China (61 stations)",
                "source": '<a href="https://doi.org/10.57760/sciencedb.28709">ScienceDB</a> (open)',
                "desc": '10 phenological stages, 1981-2024. <a href="https://doi.org/10.1038/s41597-025-06330-9">Paper</a>.',
                "available": (ROOT / "data" / "china_maize_phenology").is_dir()
                and any((ROOT / "data" / "china_maize_phenology").glob("*.xlsx")),
                "type": "ground_truth",
            },
            {
                "id": "modis_mcd12q2",
                "name": "MODIS MCD12Q2",
                "region": "Global (500m)",
                "source": '<a href="https://lpdaac.usgs.gov/products/mcd12q2v061/">LP DAAC</a> (free login)',
                "desc": "Satellite-derived SOS/EOS phenology from EVI2, yearly 2001-present.",
                "available": (ROOT / "data" / "modis_phenology").is_dir()
                and any((ROOT / "data" / "modis_phenology").glob("*")),
                "type": "satellite_archive",
            },
        ]
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    print(f"Starting phenology web tool on http://localhost:{args.port}")
    app.run(host="0.0.0.0", port=args.port, debug=args.debug)

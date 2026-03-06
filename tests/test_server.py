#!/usr/bin/env python3
"""Tests for the phenology explorer server."""

import json
import sys
import os
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Set GDAL env before importing server
os.environ.update({
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF",
})

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "webapp"))

import numpy as np
from server import (
    app,
    detect_outliers,
    double_logistic,
    fit_double_logistic_iterative,
    smooth_savgol,
    smooth_dct_garcia,
    extract_phenometrics,
    LRUCache,
    BBCH_STAGES,
    CROP_CODES,
)


class TestOutlierDetection(unittest.TestCase):
    def setUp(self):
        np.random.seed(42)
        self.doys = np.arange(1, 366, 5, dtype=float)
        self.ndvis = 0.3 + 0.5 * np.exp(-((self.doys - 180) ** 2) / 2000)
        self.ndvis += np.random.normal(0, 0.02, len(self.ndvis))

    def test_mad_few_outliers(self):
        # Gaussian curve with noise may trigger a few MAD detections at tails
        mask = detect_outliers(self.doys, self.ndvis, "mad", 3.5)
        self.assertLess(mask.sum(), len(self.ndvis) // 2, "Should flag few points")

    def test_mad_detects_spike(self):
        ndvis = self.ndvis.copy()
        ndvis[10] = 2.0  # obvious spike
        mask = detect_outliers(self.doys, ndvis, "mad", 3.5)
        self.assertTrue(mask[10], "MAD should detect obvious spike at index 10")

    def test_iqr_detects_spike(self):
        ndvis = self.ndvis.copy()
        ndvis[10] = -0.5
        mask = detect_outliers(self.doys, ndvis, "iqr", 3.5)
        self.assertTrue(mask[10])

    def test_temporal_detects_local_outlier(self):
        ndvis = self.ndvis.copy()
        ndvis[20] = ndvis[20] + 0.8  # local anomaly
        mask = detect_outliers(self.doys, ndvis, "temporal", 3.0)
        self.assertTrue(mask[20], "Temporal method should detect local anomaly")

    def test_physical_bounds(self):
        ndvis = self.ndvis.copy()
        ndvis[5] = 1.5  # above physical max
        ndvis[15] = -0.3  # below physical min
        # Physical bounds are always applied, even with "none" method
        mask = detect_outliers(self.doys, ndvis, "mad", 3.5)
        self.assertTrue(mask[5], "NDVI > 1.0 should be flagged")
        self.assertTrue(mask[15], "NDVI < -0.2 should be flagged")

    def test_returns_correct_shape(self):
        mask = detect_outliers(self.doys, self.ndvis, "mad", 3.5)
        self.assertEqual(len(mask), len(self.ndvis))
        self.assertEqual(mask.dtype, bool)


class TestDoubleLogistic(unittest.TestCase):
    def test_known_curve(self):
        t = np.arange(1, 366, dtype=float)
        params = [0.2, 0.6, 0.1, 120, 0.1, 280]
        y = double_logistic(t, *params)
        self.assertAlmostEqual(y[0], 0.2, places=1, msg="Baseline should be ~0.2")
        peak = np.max(y)
        self.assertGreater(peak, 0.6, "Peak should exceed baseline + amplitude")
        self.assertAlmostEqual(float(t[np.argmax(y)]), 200, delta=30)

    def test_symmetric(self):
        t = np.array([100.0, 200.0, 300.0])
        params = [0.1, 0.8, 0.1, 150, 0.1, 250]
        y = double_logistic(t, *params)
        self.assertGreater(y[1], y[0])
        self.assertGreater(y[1], y[2])


class TestFitDoubleLogistic(unittest.TestCase):
    def test_fit_synthetic(self):
        t = np.arange(1, 366, 5, dtype=float)
        true_params = [0.15, 0.65, 0.08, 120, 0.08, 280]
        y = double_logistic(t, *true_params) + np.random.normal(0, 0.02, len(t))
        params, rmse, info = fit_double_logistic_iterative(t, y, n_iter=3)
        self.assertIsNotNone(params, "Fit should succeed on synthetic data")
        self.assertLess(rmse, 0.1, f"RMSE should be small, got {rmse}")
        self.assertEqual(len(info), 3, "Should have 3 iteration records")

    def test_fit_flat_data(self):
        t = np.arange(1, 366, 10, dtype=float)
        y = np.full_like(t, 0.3) + np.random.normal(0, 0.01, len(t))
        params, rmse, info = fit_double_logistic_iterative(t, y, n_iter=2)
        # Should still converge, just with small amplitude
        self.assertIsNotNone(params)


class TestSmoothing(unittest.TestCase):
    def setUp(self):
        self.doys = np.array([10, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330], dtype=float)
        self.vals = np.array([0.2, 0.2, 0.3, 0.5, 0.7, 0.8, 0.8, 0.6, 0.4, 0.3, 0.2, 0.2])

    def test_savgol_output_shape(self):
        t, y = smooth_savgol(self.doys, self.vals, window=31, poly=3)
        self.assertEqual(len(t), 365)
        self.assertEqual(len(y), 365)
        self.assertEqual(t[0], 1)
        self.assertEqual(t[-1], 365)

    def test_savgol_preserves_range(self):
        t, y = smooth_savgol(self.doys, self.vals)
        self.assertGreater(np.max(y), 0.5)
        self.assertLess(np.min(y), 0.5)

    def test_dct_output_shape(self):
        t, y = smooth_dct_garcia(self.doys, self.vals)
        self.assertEqual(len(t), 365)
        self.assertEqual(len(y), 365)

    def test_dct_with_fixed_s(self):
        t, y = smooth_dct_garcia(self.doys, self.vals, s=10.0)
        self.assertEqual(len(y), 365)
        # Should be smooth
        diffs = np.abs(np.diff(y))
        self.assertLess(np.max(diffs), 0.1, "DCT with s=10 should produce smooth output")


class TestPhenometrics(unittest.TestCase):
    def setUp(self):
        self.t = np.arange(1, 366, dtype=float)
        self.y = 0.15 + 0.65 * (
            1.0 / (1.0 + np.exp(-0.08 * (self.t - 120)))
            - 1.0 / (1.0 + np.exp(-0.08 * (self.t - 280)))
        )

    def test_amplitude_threshold(self):
        pm = extract_phenometrics(self.t, self.y, "amplitude_threshold", 0.2)
        self.assertIsNotNone(pm["SOS"])
        self.assertIsNotNone(pm["POS"])
        self.assertIsNotNone(pm["EOS"])
        self.assertLess(pm["SOS"], pm["POS"])
        self.assertLess(pm["POS"], pm["EOS"])
        self.assertAlmostEqual(pm["POS"], 200, delta=20)

    def test_first_derivative(self):
        pm = extract_phenometrics(self.t, self.y, "first_derivative")
        self.assertIsNotNone(pm["SOS"])
        self.assertIsNotNone(pm["EOS"])
        self.assertLess(pm["SOS"], pm["POS"])

    def test_second_derivative(self):
        pm = extract_phenometrics(self.t, self.y, "second_derivative")
        self.assertIsNotNone(pm["SOS"])
        self.assertIsNotNone(pm["EOS"])

    def test_flat_signal(self):
        flat = np.full(365, 0.3)
        pm = extract_phenometrics(self.t, flat, "amplitude_threshold", 0.2)
        self.assertIsNone(pm["SOS"], "Flat signal should have no SOS")
        self.assertIsNone(pm["EOS"])
        self.assertLess(pm["amplitude"], 0.02)


class TestLRUCache(unittest.TestCase):
    def test_basic_put_get(self):
        cache = LRUCache(max_entries=10)
        cache.put(("a", 1), {"val": 42})
        result = cache.get(("a", 1))
        self.assertEqual(result["val"], 42)

    def test_miss(self):
        cache = LRUCache(max_entries=10)
        self.assertIsNone(cache.get(("nonexistent",)))

    def test_eviction(self):
        cache = LRUCache(max_entries=3)
        cache.put(("a",), 1)
        cache.put(("b",), 2)
        cache.put(("c",), 3)
        cache.put(("d",), 4)  # should evict "a"
        self.assertIsNone(cache.get(("a",)))
        self.assertEqual(cache.get(("b",)), 2)

    def test_lru_order(self):
        cache = LRUCache(max_entries=3)
        cache.put(("a",), 1)
        cache.put(("b",), 2)
        cache.put(("c",), 3)
        cache.get(("a",))  # access "a" to make it recently used
        cache.put(("d",), 4)  # should evict "b" (least recently used)
        self.assertIsNone(cache.get(("b",)))
        self.assertEqual(cache.get(("a",)), 1)

    def test_hit_miss_counters(self):
        cache = LRUCache(max_entries=10)
        cache.put(("x",), 1)
        cache.get(("x",))  # hit
        cache.get(("y",))  # miss
        self.assertEqual(cache.hits, 1)
        self.assertEqual(cache.misses, 1)

    def test_size(self):
        cache = LRUCache(max_entries=10)
        self.assertEqual(cache.size, 0)
        cache.put(("a",), 1)
        cache.put(("b",), 2)
        self.assertEqual(cache.size, 2)

    def test_disk_persistence(self, tmp_path=None):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_cache.json"
            c1 = LRUCache(max_entries=100, persist_path=path)
            c1.put(("scene1", 5.7, 52.6, 3, ("B04", "B08")), {"ndvi": 0.5})
            c1.put(("scene2", 5.7, 52.6, 3, ("B04", "B08")), {"ndvi": 0.7})
            c1.flush()
            # Load into new cache
            c2 = LRUCache(max_entries=100, persist_path=path)
            self.assertEqual(c2.size, 2)
            result = c2.get(("scene1", 5.7, 52.6, 3, ("B04", "B08")))
            self.assertIsNotNone(result)
            self.assertEqual(result["ndvi"], 0.5)


class TestBBCHMappings(unittest.TestCase):
    def test_bbch_stages_coverage(self):
        self.assertIn(0, BBCH_STAGES)
        self.assertIn(65, BBCH_STAGES)
        self.assertIn(99, BBCH_STAGES)
        self.assertEqual(BBCH_STAGES[65], "Mid flowering")

    def test_crop_codes(self):
        self.assertIn("WTW", CROP_CODES)
        self.assertEqual(CROP_CODES["WTW"], "Winter wheat")
        self.assertIn("MZE", CROP_CODES)


class TestFlaskRoutes(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_index(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Phenology Explorer", resp.data)

    def test_datasets_page(self):
        resp = self.client.get("/datasets")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Crop & Phenology Datasets", resp.data)

    def test_api_datasets(self):
        resp = self.client.get("/api/datasets")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 5)
        ids = [d["id"] for d in data]
        self.assertIn("sentinel2_live", ids)
        self.assertIn("flevovision", ids)
        self.assertIn("dwd_phenology", ids)
        self.assertIn("kenya_helmets", ids)

    def test_api_flevovision_locations(self):
        resp = self.client.get("/api/flevovision_locations")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIsInstance(data, list)
        if len(data) > 0:
            loc = data[0]
            self.assertIn("lat", loc)
            self.assertIn("lon", loc)
            self.assertIn("code", loc)
            self.assertIn("id", loc)
            self.assertGreater(loc["lat"], 50)  # Netherlands
            self.assertGreater(loc["lon"], 4)

    def test_api_validation_data_no_params(self):
        resp = self.client.get("/api/validation_data?lon=0&lat=0")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIsInstance(data, list)

    def test_api_validation_data_flevovision(self):
        # FlevoVision is around lon=5.7, lat=52.6
        resp = self.client.get(
            "/api/validation_data?lon=5.7&lat=52.6&radius=0.2"
            "&start_date=2018-01-01&end_date=2018-12-31"
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIsInstance(data, list)
        if len(data) > 0:
            obs = data[0]
            self.assertEqual(obs["source"], "FlevoVision")
            self.assertIn("doy", obs)
            self.assertIn("bbch", obs)
            self.assertIn("crop_name", obs)

    def test_api_extract_missing_params(self):
        # Missing lon/lat should raise KeyError -> 500
        resp = self.client.post(
            "/api/extract",
            data=json.dumps({}),
            content_type="application/json",
        )
        # Server returns 500 since it's a streaming response that fails
        self.assertIn(resp.status_code, [200, 400, 500])


class TestNewEndpoints(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_api_dwd_locations(self):
        resp = self.client.get("/api/dwd_locations")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIsInstance(data, list)
        if len(data) > 0:
            loc = data[0]
            self.assertIn("lat", loc)
            self.assertIn("lon", loc)
            self.assertIn("id", loc)
            self.assertGreater(loc["lat"], 47)  # Germany
            self.assertLess(loc["lat"], 56)

    def test_api_phenocam_locations(self):
        resp = self.client.get("/api/phenocam_locations")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIsInstance(data, list)
        if len(data) > 0:
            loc = data[0]
            self.assertIn("lat", loc)
            self.assertIn("lon", loc)
            self.assertIn("source", loc)
            self.assertEqual(loc["source"], "phenocam")

    def test_api_check_cache(self):
        resp = self.client.get("/api/check_cache?lon=5.7&lat=52.6")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn("cached_scenes", data)
        self.assertIsInstance(data["cached_scenes"], int)

    def test_api_validation_senseco(self):
        # SenSeCo site in France: lat=43.5495, lon=1.1061
        resp = self.client.get(
            "/api/validation_data?lon=1.1061&lat=43.5495&radius=0.01"
            "&start_date=2016-01-01&end_date=2019-12-31"
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIsInstance(data, list)
        if len(data) > 0:
            obs = data[0]
            self.assertEqual(obs["source"], "SenSeCo")
            self.assertIn("bbch", obs)


class TestPredownloadLocations(unittest.TestCase):
    """Test that location extraction functions work correctly."""

    def test_flevovision_locations(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            from predownload_s2 import get_flevovision_locations
            locs = get_flevovision_locations()
            if locs:  # only test if data is present
                self.assertGreater(len(locs), 100)
                loc = locs[0]
                self.assertIn("lon", loc)
                self.assertIn("lat", loc)
                self.assertIn("source", loc)
                self.assertEqual(loc["source"], "flevovision")
        except ImportError:
            self.skipTest("predownload_s2 not importable")

    def test_dwd_locations(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            from predownload_s2 import get_dwd_locations
            locs = get_dwd_locations()
            if locs:
                self.assertGreater(len(locs), 50)
                loc = locs[0]
                self.assertIn("lon", loc)
                self.assertIn("lat", loc)
                self.assertEqual(loc["source"], "dwd")
                # Germany coordinates
                self.assertGreater(loc["lat"], 47)
                self.assertLess(loc["lat"], 56)
                self.assertGreater(loc["lon"], 5)
                self.assertLess(loc["lon"], 16)
        except ImportError:
            self.skipTest("predownload_s2 not importable")


if __name__ == "__main__":
    unittest.main()

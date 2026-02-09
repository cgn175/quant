#!/usr/bin/env python3
"""ML inference microservice with three model types.

Endpoints:
    GET  /health              — health check + loaded models
    POST /predict             — v1 XGBoost trend filter (legacy)
    POST /predict_regime      — Regime Classifier (Traffic Light)
    POST /predict_volatility  — Volatility Predictor (Dynamic Stop-Loss)
"""

import argparse
import json
import os
import signal
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import numpy as np

try:
    import xgboost as xgb
    HAS_XGB = True
except ImportError:
    HAS_XGB = False

try:
    import joblib
except ImportError:
    from sklearn.externals import joblib  # type: ignore

LOG_EPS = 1e-8


# ---------------------------------------------------------------------------
# XGBoost Registry (legacy v1 trend filter)
# ---------------------------------------------------------------------------

class XGBModelRegistry:
    def __init__(self, models_dir: str):
        self.models: dict[str, xgb.Booster] = {}
        self.meta: dict[str, dict] = {}
        if HAS_XGB:
            self._load_all(Path(models_dir))

    def _load_all(self, models_dir: Path):
        if not models_dir.exists():
            return
        for meta_path in sorted(models_dir.glob("*_meta.json")):
            symbol = meta_path.stem.replace("_meta", "")
            model_path = meta_path.parent / f"{symbol}.json"
            if not model_path.exists():
                continue
            with open(meta_path) as f:
                self.meta[symbol] = json.load(f)
            booster = xgb.Booster()
            booster.load_model(str(model_path))
            self.models[symbol] = booster
            print(f"[xgb] Loaded: {symbol} ({len(self.meta[symbol]['feature_names'])} features)", file=sys.stderr)

    @property
    def symbols(self) -> list[str]:
        return sorted(self.models.keys())

    @property
    def version(self) -> str:
        for m in self.meta.values():
            return m.get("feature_version", "unknown")
        return "unknown"

    def predict(self, symbol: str, features: dict[str, float]) -> float:
        meta = self.meta[symbol]
        feature_names = meta["feature_names"]
        missing = [f for f in feature_names if f not in features]
        if missing:
            raise ValueError(f"missing features: {missing}")
        arr = np.array([[features[f] for f in feature_names]], dtype=np.float32)
        dmat = xgb.DMatrix(arr, feature_names=feature_names)
        probs = self.models[symbol].predict(dmat)
        return float(probs[0])


# ---------------------------------------------------------------------------
# Sklearn Registry (regime + volatility models)
# ---------------------------------------------------------------------------

class SklearnRegistry:
    """Loads sklearn .pkl models with _meta.json companion files."""

    def __init__(self, models_dir: str, name: str):
        self.name = name
        self.models: dict[str, object] = {}
        self.meta: dict[str, dict] = {}
        self._load_all(Path(models_dir))

    def _load_all(self, models_dir: Path):
        if not models_dir.exists():
            print(f"[{self.name}] Directory not found: {models_dir}", file=sys.stderr)
            return
        for meta_path in sorted(models_dir.glob("*_meta.json")):
            symbol = meta_path.stem.replace("_meta", "")
            model_path = meta_path.parent / f"{symbol}.pkl"
            if not model_path.exists():
                print(f"[{self.name}] WARN: model file missing for {symbol}", file=sys.stderr)
                continue
            with open(meta_path) as f:
                self.meta[symbol] = json.load(f)
            self.models[symbol] = joblib.load(str(model_path))
            n_feat = len(self.meta[symbol].get("feature_names", []))
            print(f"[{self.name}] Loaded: {symbol} ({n_feat} features)", file=sys.stderr)

    @property
    def symbols(self) -> list[str]:
        return sorted(self.models.keys())

    @property
    def version(self) -> str:
        for m in self.meta.values():
            return m.get("feature_version", "unknown")
        return "unknown"

    def _build_array(self, symbol: str, features: dict[str, float]) -> np.ndarray:
        feature_names = self.meta[symbol]["feature_names"]
        missing = [f for f in feature_names if f not in features]
        if missing:
            raise ValueError(f"missing features: {missing}")
        return np.array([[features[f] for f in feature_names]], dtype=np.float64)

    def predict_proba(self, symbol: str, features: dict[str, float]) -> float:
        """For classifiers: return probability of class 1."""
        arr = self._build_array(symbol, features)
        probs = self.models[symbol].predict_proba(arr)
        return float(probs[0, 1])

    def predict_value(self, symbol: str, features: dict[str, float]) -> float:
        """For regressors: return predicted value."""
        arr = self._build_array(symbol, features)
        pred = self.models[symbol].predict(arr)
        return float(pred[0])

    def predict_range_pct(self, symbol: str, features: dict[str, float]) -> float:
        """For volatility model: predict range %, handling log transform."""
        log_pred = self.predict_value(symbol, features)
        log_eps = self.meta[symbol].get("log_eps", LOG_EPS)
        return float(np.exp(log_pred) - log_eps)


# ---------------------------------------------------------------------------
# Global registries
# ---------------------------------------------------------------------------

xgb_registry: XGBModelRegistry | None = None
regime_registry: SklearnRegistry | None = None
vol_registry: SklearnRegistry | None = None


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"{self.client_address[0]} - {format % args}", file=sys.stderr)

    def _send_json(self, status: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            self._send_json(400, {"error": f"invalid JSON: {e}"})
            return None

    def _extract_symbol_features(self, body: dict, registry_models: dict) -> tuple:
        """Extract and validate symbol + features from request body.
        Returns (symbol, features) or sends error and returns (None, None).
        """
        symbol = body.get("symbol")
        if not symbol:
            self._send_json(400, {"error": "missing 'symbol' field"})
            return None, None
        if symbol not in registry_models:
            self._send_json(404, {"error": f"unknown symbol: {symbol}"})
            return None, None
        features = body.get("features")
        if not isinstance(features, dict):
            self._send_json(400, {"error": "missing or invalid 'features' field"})
            return None, None
        return symbol, features

    # ---- GET ----
    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {
                "status": "ok",
                "xgb_models": xgb_registry.symbols if xgb_registry else [],
                "xgb_version": xgb_registry.version if xgb_registry else "none",
                "regime_models": regime_registry.symbols if regime_registry else [],
                "regime_version": regime_registry.version if regime_registry else "none",
                "vol_models": vol_registry.symbols if vol_registry else [],
                "vol_version": vol_registry.version if vol_registry else "none",
            })
        else:
            self._send_json(404, {"error": "not found"})

    # ---- POST ----
    def do_POST(self):
        if self.path == "/predict":
            self._handle_predict_xgb()
        elif self.path == "/predict_regime":
            self._handle_predict_regime()
        elif self.path == "/predict_volatility":
            self._handle_predict_volatility()
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_predict_xgb(self):
        """Legacy v1 XGBoost trend filter."""
        if not xgb_registry or not xgb_registry.models:
            self._send_json(503, {"error": "no XGBoost models loaded"})
            return

        body = self._read_json()
        if body is None:
            return

        symbol, features = self._extract_symbol_features(body, xgb_registry.models)
        if symbol is None:
            return

        try:
            prob = xgb_registry.predict(symbol, features)
        except ValueError as e:
            self._send_json(400, {"error": str(e)})
            return
        except Exception as e:
            self._send_json(500, {"error": f"prediction failed: {e}"})
            return

        self._send_json(200, {
            "symbol": symbol,
            "prob": round(prob, 6),
            "model_version": xgb_registry.meta[symbol].get("feature_version", "unknown"),
        })

    def _handle_predict_regime(self):
        """Regime Classifier (Traffic Light)."""
        if not regime_registry or not regime_registry.models:
            self._send_json(503, {"error": "no regime models loaded"})
            return

        body = self._read_json()
        if body is None:
            return

        symbol, features = self._extract_symbol_features(body, regime_registry.models)
        if symbol is None:
            return

        try:
            prob_safe = regime_registry.predict_proba(symbol, features)
        except ValueError as e:
            self._send_json(400, {"error": str(e)})
            return
        except Exception as e:
            self._send_json(500, {"error": f"prediction failed: {e}"})
            return

        self._send_json(200, {
            "symbol": symbol,
            "prob_safe": round(prob_safe, 6),
            "model_version": regime_registry.version,
        })

    def _handle_predict_volatility(self):
        """Volatility Predictor (Dynamic Stop-Loss)."""
        if not vol_registry or not vol_registry.models:
            self._send_json(503, {"error": "no volatility models loaded"})
            return

        body = self._read_json()
        if body is None:
            return

        symbol, features = self._extract_symbol_features(body, vol_registry.models)
        if symbol is None:
            return

        try:
            pred_range_pct = vol_registry.predict_range_pct(symbol, features)
        except ValueError as e:
            self._send_json(400, {"error": str(e)})
            return
        except Exception as e:
            self._send_json(500, {"error": f"prediction failed: {e}"})
            return

        self._send_json(200, {
            "symbol": symbol,
            "pred_range_pct": round(pred_range_pct, 8),
            "model_version": vol_registry.version,
        })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="ML inference server (multi-model)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("ML_SERVER_PORT", "9001")))
    parser.add_argument("--models-dir", default="ml/models",
                        help="Base directory for model files")
    args = parser.parse_args()

    models_base = Path(args.models_dir)

    global xgb_registry, regime_registry, vol_registry

    # Load legacy XGBoost models (trend_v1)
    xgb_registry = XGBModelRegistry(str(models_base))

    # Load regime models
    regime_registry = SklearnRegistry(str(models_base / "regime_v1"), name="regime")

    # Load volatility models
    vol_registry = SklearnRegistry(str(models_base / "vol_v1"), name="vol")

    total_models = (
        len(xgb_registry.models)
        + len(regime_registry.models)
        + len(vol_registry.models)
    )

    if total_models == 0:
        print("WARNING: no models loaded at all", file=sys.stderr)

    server = HTTPServer(("0.0.0.0", args.port), Handler)
    print(
        f"ML server listening on :{args.port}\n"
        f"  XGB:    {xgb_registry.symbols} ({xgb_registry.version})\n"
        f"  Regime: {regime_registry.symbols} ({regime_registry.version})\n"
        f"  Vol:    {vol_registry.symbols} ({vol_registry.version})",
        file=sys.stderr,
    )

    def shutdown(signum, frame):
        print(f"\nReceived signal {signum}, shutting down...", file=sys.stderr)
        threading.Thread(target=server.shutdown).start()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    server.serve_forever()
    server.server_close()
    print("Server stopped.", file=sys.stderr)


if __name__ == "__main__":
    main()

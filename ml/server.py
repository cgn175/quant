#!/usr/bin/env python3
"""XGBoost inference microservice using stdlib http.server."""

import argparse
import json
import os
import signal
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import numpy as np
import xgboost as xgb


class ModelRegistry:
    def __init__(self, models_dir: str):
        self.models: dict[str, xgb.Booster] = {}
        self.meta: dict[str, dict] = {}
        self._load_all(Path(models_dir))

    def _load_all(self, models_dir: Path):
        for meta_path in sorted(models_dir.glob("*_meta.json")):
            symbol = meta_path.stem.replace("_meta", "")
            model_path = meta_path.parent / f"{symbol}.json"
            if not model_path.exists():
                print(f"WARN: model file missing for {symbol}, skipping", file=sys.stderr)
                continue
            with open(meta_path) as f:
                self.meta[symbol] = json.load(f)
            booster = xgb.Booster()
            booster.load_model(str(model_path))
            self.models[symbol] = booster
            print(f"Loaded model: {symbol} ({len(self.meta[symbol]['feature_names'])} features)", file=sys.stderr)

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


registry: ModelRegistry | None = None


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

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {
                "status": "ok",
                "models_loaded": registry.symbols,
                "version": registry.version,
            })
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/predict":
            self._send_json(404, {"error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            body = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            self._send_json(400, {"error": f"invalid JSON: {e}"})
            return

        symbol = body.get("symbol")
        if not symbol:
            self._send_json(400, {"error": "missing 'symbol' field"})
            return
        if symbol not in registry.models:
            self._send_json(404, {"error": f"unknown symbol: {symbol}"})
            return

        features = body.get("features")
        if not isinstance(features, dict):
            self._send_json(400, {"error": "missing or invalid 'features' field"})
            return

        try:
            prob = registry.predict(symbol, features)
        except ValueError as e:
            self._send_json(400, {"error": str(e)})
            return
        except Exception as e:
            self._send_json(500, {"error": f"prediction failed: {e}"})
            return

        self._send_json(200, {
            "symbol": symbol,
            "prob": round(prob, 6),
            "model_version": registry.meta[symbol].get("feature_version", "unknown"),
        })


def main():
    parser = argparse.ArgumentParser(description="XGBoost inference server")
    parser.add_argument("--port", type=int, default=int(os.environ.get("ML_SERVER_PORT", "9001")))
    parser.add_argument("--models-dir", default="ml/models")
    args = parser.parse_args()

    global registry
    registry = ModelRegistry(args.models_dir)
    if not registry.models:
        print("ERROR: no models loaded, exiting", file=sys.stderr)
        sys.exit(1)

    server = HTTPServer(("0.0.0.0", args.port), Handler)
    print(f"ML server listening on :{args.port} | models={registry.symbols} | version={registry.version}", file=sys.stderr)

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

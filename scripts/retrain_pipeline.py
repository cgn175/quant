#!/usr/bin/env python3
"""ML Model Retraining Pipeline — automated orchestrator.

This script handles the end-to-end ML model retraining lifecycle:
  1. Incremental data fetch (4H candles + funding rates)
  2. Training all model variants into staging directory
  3. Model evaluation (compare new vs current models)
  4. Atomic deployment with backup and rollback
  5. ML server restart and health verification

Subcommands:
    fetch      — Incremental fetch from Binance to training.db
    train      — Train all model variants into staging directory
    evaluate   — Compare staged models vs current models
    deploy     — Atomic deployment + server restart + health check
    run        — Execute all steps in sequence (for cron)

Usage:
    python3 scripts/retrain_pipeline.py fetch
    python3 scripts/retrain_pipeline.py train --run-id 20260209_1200
    python3 scripts/retrain_pipeline.py evaluate --run-id 20260209_1200
    python3 scripts/retrain_pipeline.py deploy --run-id 20260209_1200
    python3 scripts/retrain_pipeline.py run

For cron (daily 2am):
    0 2 * * * cd /path/to/quant && python3 scripts/retrain_pipeline.py run >> logs/retrain.log 2>&1
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import yaml
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ccxt
import pandas as pd

try:
    import joblib
except ImportError:
    from sklearn.externals import joblib  # type: ignore

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "training.db"
LOCK_FILE = ROOT / "data" / "retrain.lock"
LOG_DIR = ROOT / "logs"
MODELS_LIVE_DIR = ROOT / "ml" / "models"
MODELS_STAGING_BASE = ROOT / "ml" / "models_staging"
MODELS_BACKUP_BASE = ROOT / "ml" / "models_backups"
SERVER_SCRIPT = ROOT / "ml" / "server.py"
SERVER_PID_FILE = ROOT / "ml" / "server.pid"
SERVER_PORT = 9001
SERVER_STARTUP_TIMEOUT = 10  # seconds

# Model variants to train (variant_name -> script path)
MODEL_VARIANTS = {
    "regime_v1": ROOT / "ml" / "regime" / "train_regime.py",
    "regime_v2": ROOT / "ml" / "regime" / "train_regime_v2.py",
    "regime_v1_long": ROOT / "ml" / "regime" / "train_regime_directional_save.py",
    "vol_v1": ROOT / "ml" / "volatility" / "train_volatility.py",
}

# Symbols to train
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

# Evaluation thresholds
AUC_TOLERANCE = 0.02  # Allow up to 2pp AUC drop
MAE_TOLERANCE = 0.0005  # Allow up to 0.05pp MAE increase for volatility
MAX_AUC_GAP = 0.20  # Reject models with overfitting gap > 20pp

# Fetch parameters
CANDLE_TIMEFRAME = "4h"
BACKFILL_CANDLES = 3  # Overlap to handle exchange corrections
FOUR_HOURS_MS = 4 * 60 * 60 * 1000

# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def load_telegram_config():
    """Load Telegram config from config.yaml."""
    config_path = ROOT / "config.yaml"
    if not config_path.exists():
        return None, None
    
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
            alerts = config.get("alerts", {})
            return alerts.get("telegram_bot_token"), alerts.get("telegram_chat_id")
    except Exception as e:
        log(f"WARN: Failed to load config.yaml: {e}")
        return None, None

def notify(message: str, is_error: bool = False):
    """Send Telegram notification."""
    token, chat_id = load_telegram_config()
    if not token or not chat_id:
        log("WARN: Telegram not configured, skipping notification")
        return

    emoji = "❌" if is_error else "✅"
    title = "ML Pipeline Error" if is_error else "ML Pipeline Success"
    text = f"{emoji} *{title}*\n\n{message}"
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }).encode()
    
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req) as resp:
            if resp.status != 200:
                log(f"WARN: Telegram notification failed: {resp.status}")
    except Exception as e:
        log(f"WARN: Telegram notification failed: {e}")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(msg: str):
    """Print timestamped log message."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Monitoring (Prometheus Pushgateway)
# ---------------------------------------------------------------------------

def push_metrics(job_name: str, metrics: dict):
    """Push metrics to Prometheus Pushgateway."""
    # This assumes a Pushgateway is running on localhost:9091
    # If not, this function gracefully fails
    pushgateway_url = "http://localhost:9091/metrics/job/retrain_pipeline"
    
    data = f"# TYPE ml_pipeline_last_run_timestamp gauge\n"
    data += f"ml_pipeline_last_run_timestamp {int(time.time())}\n"
    
    for name, value in metrics.items():
        data += f"# TYPE {name} gauge\n"
        data += f"{name} {value}\n"
        
    try:
        req = urllib.request.Request(pushgateway_url, data=data.encode(), method="POST")
        with urllib.request.urlopen(req) as resp:
            if resp.status != 200:
                log(f"WARN: Pushgateway failed: {resp.status}")
    except Exception:
        # Silently fail if Pushgateway is not available
        pass

# ---------------------------------------------------------------------------
# File Locking (prevent concurrent runs)
# ---------------------------------------------------------------------------

class FileLock:
    """Exclusive file lock to prevent concurrent pipeline runs."""

    def __init__(self, lockfile: Path):
        self.lockfile = lockfile
        self.lockfile.parent.mkdir(parents=True, exist_ok=True)
        self.fd = None

    def __enter__(self):
        self.fd = open(self.lockfile, "w")
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.fd.write(f"{os.getpid()}\n")
            self.fd.flush()
        except IOError:
            log(f"ERROR: Another pipeline run is in progress (lock: {self.lockfile})")
            sys.exit(1)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.fd:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            self.fd.close()


# ---------------------------------------------------------------------------
# Subcommand: fetch (incremental data from Binance)
# ---------------------------------------------------------------------------

def cmd_fetch():
    """Incremental fetch of 4H candles and funding rates from Binance."""
    log("=== FETCH: Incremental data update ===")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    # Create tables if they don't exist
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            open_time INTEGER NOT NULL,
            close_time INTEGER NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            is_closed INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            UNIQUE(symbol, open_time)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS funding (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            funding_rate REAL NOT NULL,
            UNIQUE(symbol, timestamp)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_funding_symbol_time ON funding(symbol, timestamp DESC)")
    conn.commit()

    exchange = ccxt.binance({"enableRateLimit": True})
    funding_exchange = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "future"}})

    for symbol in SYMBOLS:
        log(f"Fetching {symbol}...")

        # --- Fetch candles ---
        last_candle_time = conn.execute(
            "SELECT MAX(open_time) FROM candles WHERE symbol = ?", (symbol,)
        ).fetchone()[0]

        if last_candle_time is None:
            log(f"  No existing candle data for {symbol}, fetching last 180 days...")
            since = exchange.parse8601((datetime.utcnow() - timedelta(days=180)).isoformat())
        else:
            # Backfill a few candles to handle exchange corrections
            since = last_candle_time - (BACKFILL_CANDLES * FOUR_HOURS_MS)
            log(f"  Last candle: {datetime.fromtimestamp(last_candle_time / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')}")

        candles_fetched = 0
        limit = 1000
        all_candles = []

        while True:
            try:
                ohlcv = exchange.fetch_ohlcv(symbol.replace("USDT", "/USDT"), CANDLE_TIMEFRAME, since=since, limit=limit)
                if not ohlcv:
                    break

                all_candles.extend(ohlcv)
                since = ohlcv[-1][0] + 1

                if len(ohlcv) < limit:
                    break

                time.sleep(exchange.rateLimit / 1000)

            except Exception as e:
                log(f"  ERROR fetching candles: {e}")
                time.sleep(5)
                continue

        # Filter out the current unclosed candle
        now_ms = int(time.time() * 1000)
        current_candle_start = (now_ms // FOUR_HOURS_MS) * FOUR_HOURS_MS
        closed_candles = [c for c in all_candles if c[0] < current_candle_start]

        if closed_candles:
            created_at = int(time.time() * 1000)
            records = [
                (symbol, c[0], c[0] + FOUR_HOURS_MS - 1, c[1], c[2], c[3], c[4], c[5], 1, created_at)
                for c in closed_candles
            ]
            conn.executemany(
                "INSERT OR REPLACE INTO candles "
                "(symbol, open_time, close_time, open, high, low, close, volume, is_closed, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                records,
            )
            conn.commit()
            candles_fetched = len(records)
            log(f"  Candles: {candles_fetched} rows ingested")
        else:
            log(f"  Candles: no new data")

        # --- Fetch funding rates ---
        last_funding_time = conn.execute(
            "SELECT MAX(timestamp) FROM funding WHERE symbol = ?", (symbol,)
        ).fetchone()[0]

        if last_funding_time is None:
            log(f"  No existing funding data for {symbol}, fetching last 730 days...")
            since_funding = funding_exchange.parse8601((datetime.utcnow() - timedelta(days=730)).isoformat())
        else:
            since_funding = last_funding_time + 1
            log(f"  Last funding: {datetime.fromtimestamp(last_funding_time / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')}")

        funding_fetched = 0
        all_funding = []

        while True:
            try:
                rates = funding_exchange.fetch_funding_rate_history(
                    symbol.replace("USDT", "/USDT"), since=since_funding, limit=1000
                )
                if not rates:
                    break

                all_funding.extend(rates)
                since_funding = rates[-1]["timestamp"] + 1

                if len(rates) < 1000:
                    break

                time.sleep(funding_exchange.rateLimit / 1000)

            except Exception as e:
                log(f"  ERROR fetching funding: {e}")
                time.sleep(5)
                continue

        if all_funding:
            records = [(symbol, r["timestamp"], r.get("fundingRate", 0.0)) for r in all_funding]
            conn.executemany(
                "INSERT OR REPLACE INTO funding (symbol, timestamp, funding_rate) VALUES (?, ?, ?)",
                records,
            )
            conn.commit()
            funding_fetched = len(records)
            log(f"  Funding: {funding_fetched} rows ingested")
        else:
            log(f"  Funding: no new data")

    conn.close()
    log("=== FETCH: Complete ===\n")


# ---------------------------------------------------------------------------
# Subcommand: train (all model variants into staging)
# ---------------------------------------------------------------------------

def cmd_train(run_id: str):
    """Train all model variants into staging directory."""
    log(f"=== TRAIN: Run ID = {run_id} ===")

    staging_dir = MODELS_STAGING_BASE / run_id
    staging_dir.mkdir(parents=True, exist_ok=True)

    # --- Train Regime v1 (all 4 symbols) ---
    log("Training Regime v1 (all symbols)...")
    regime_v1_dir = staging_dir / "regime_v1"
    subprocess.run([
        sys.executable,
        str(MODEL_VARIANTS["regime_v1"]),
        "--model-dir", str(regime_v1_dir),
    ], check=True)

    # --- Train Regime v2 (all symbols, but only ETH will be used) ---
    log("Training Regime v2 (all symbols)...")
    regime_v2_dir = staging_dir / "regime_v2"
    subprocess.run([
        sys.executable,
        str(MODEL_VARIANTS["regime_v2"]),
        "--model-dir", str(regime_v2_dir),
    ], check=True)

    # --- Train Regime v1 LONG (SOL only) ---
    log("Training Regime v1 LONG (SOL only)...")
    subprocess.run([
        sys.executable,
        str(MODEL_VARIANTS["regime_v1_long"]),
        "--symbol", "SOLUSDT",
        "--direction", "LONG",
        "--models-base", str(staging_dir),
    ], check=True)

    # --- Train Volatility v1 (all 4 symbols) ---
    log("Training Volatility v1 (all symbols)...")
    vol_v1_dir = staging_dir / "vol_v1"
    subprocess.run([
        sys.executable,
        str(MODEL_VARIANTS["vol_v1"]),
        "--model-dir", str(vol_v1_dir),
    ], check=True)

    log(f"=== TRAIN: Complete (staged at {staging_dir}) ===\n")


# ---------------------------------------------------------------------------
# Subcommand: evaluate (compare staged vs current models)
# ---------------------------------------------------------------------------

def cmd_evaluate(run_id: str) -> bool:
    """Evaluate staged models against current live models.
    
    Returns True if deployment is approved, False otherwise.
    """
    log(f"=== EVALUATE: Run ID = {run_id} ===")

    staging_dir = MODELS_STAGING_BASE / run_id
    if not staging_dir.exists():
        log(f"ERROR: Staging directory not found: {staging_dir}")
        return False

    # Evaluation results
    results = {
        "regime_v1": {},
        "regime_v2": {},
        "regime_v1_long": {},
        "vol_v1": {},
    }
    deploy_approved = True

    # --- Evaluate Regime v1 (all 4 symbols) ---
    log("Evaluating Regime v1...")
    for symbol in SYMBOLS:
        approved = evaluate_regime_model(
            staging_dir / "regime_v1" / f"{symbol}.pkl",
            staging_dir / "regime_v1" / f"{symbol}_meta.json",
            MODELS_LIVE_DIR / "regime_v1" / f"{symbol}.pkl",
            MODELS_LIVE_DIR / "regime_v1" / f"{symbol}_meta.json",
            symbol, "regime_v1",
        )
        results["regime_v1"][symbol] = approved
        if not approved:
            deploy_approved = False

    # --- Evaluate Regime v2 (ETH only matters for production) ---
    log("Evaluating Regime v2...")
    for symbol in SYMBOLS:
        approved = evaluate_regime_model(
            staging_dir / "regime_v2" / f"{symbol}.pkl",
            staging_dir / "regime_v2" / f"{symbol}_meta.json",
            MODELS_LIVE_DIR / "regime_v2" / f"{symbol}.pkl",
            MODELS_LIVE_DIR / "regime_v2" / f"{symbol}_meta.json",
            symbol, "regime_v2",
        )
        results["regime_v2"][symbol] = approved
        # Only ETH matters for deployment gate (per ML_V2 report)
        if symbol == "ETHUSDT" and not approved:
            deploy_approved = False

    # --- Evaluate Regime v1 LONG (SOL only) ---
    log("Evaluating Regime v1 LONG (SOL)...")
    approved = evaluate_regime_model(
        staging_dir / "regime_v1_long" / "SOLUSDT.pkl",
        staging_dir / "regime_v1_long" / "SOLUSDT_meta.json",
        MODELS_LIVE_DIR / "regime_v1_long" / "SOLUSDT.pkl",
        MODELS_LIVE_DIR / "regime_v1_long" / "SOLUSDT_meta.json",
        "SOLUSDT", "regime_v1_long",
    )
    results["regime_v1_long"]["SOLUSDT"] = approved
    if not approved:
        deploy_approved = False

    # --- Evaluate Volatility v1 (all 4 symbols) ---
    log("Evaluating Volatility v1...")
    for symbol in SYMBOLS:
        approved = evaluate_volatility_model(
            staging_dir / "vol_v1" / f"{symbol}.pkl",
            staging_dir / "vol_v1" / f"{symbol}_meta.json",
            MODELS_LIVE_DIR / "vol_v1" / f"{symbol}.pkl",
            MODELS_LIVE_DIR / "vol_v1" / f"{symbol}_meta.json",
            symbol,
        )
        results["vol_v1"][symbol] = approved
        if not approved:
            deploy_approved = False

    # --- Summary ---
    log("\n=== EVALUATION SUMMARY ===")
    for variant, symbol_results in results.items():
        for symbol, approved in symbol_results.items():
            status = "✅ APPROVED" if approved else "❌ REJECTED"
            log(f"  {variant:20s} {symbol:10s} {status}")

    if deploy_approved:
        log("\n✅ DEPLOYMENT APPROVED")
    else:
        log("\n❌ DEPLOYMENT REJECTED (one or more models failed evaluation)")

    # Push evaluation metrics
    push_metrics("evaluate", {
        "ml_pipeline_evaluate_success": 1 if deploy_approved else 0,
    })

    log("=== EVALUATE: Complete ===\n")
    return deploy_approved


def evaluate_regime_model(
    staged_pkl: Path,
    staged_meta: Path,
    live_pkl: Path,
    live_meta: Path,
    symbol: str,
    variant: str,
) -> bool:
    """Evaluate a single regime model (classifier).
    
    Returns True if deployment is approved.
    """
    if not staged_meta.exists():
        log(f"  {symbol} ({variant}): WARN - no staged meta file")
        return False

    with open(staged_meta) as f:
        new_meta = json.load(f)

    # If no live model exists, approve the new model
    if not live_meta.exists():
        log(f"  {symbol} ({variant}): NEW MODEL - no live baseline, approving")
        return True

    with open(live_meta) as f:
        old_meta = json.load(f)

    # Extract metrics
    if variant == "regime_v2":
        # regime_v2 stores metrics under "metrics_v2"
        new_auc = new_meta.get("metrics_v2", {}).get("test_auc", 0)
        old_auc = old_meta.get("metrics_v2", {}).get("test_auc", 0)
        new_gap = new_meta.get("metrics_v2", {}).get("auc_gap", 0)
        new_n_test = new_meta.get("n_test_entries", 0)
    else:
        # regime_v1 and regime_v1_long store under "metrics"
        new_auc = new_meta.get("metrics", {}).get("test_auc", 0)
        old_auc = old_meta.get("metrics", {}).get("test_auc", 0)
        new_gap = new_meta.get("metrics", {}).get("auc_gap", 0)
        new_n_test = new_meta.get("n_test_entries", 0)

    # Evaluation gates
    auc_delta = new_auc - old_auc
    auc_ok = new_auc >= old_auc - AUC_TOLERANCE
    gap_ok = new_gap <= MAX_AUC_GAP
    data_ok = new_n_test >= 10

    approved = auc_ok and gap_ok and data_ok

    status = "✅ PASS" if approved else "❌ FAIL"
    log(f"  {symbol} ({variant}): {status}")
    log(f"    Test AUC:  {old_auc:.4f} → {new_auc:.4f}  (Δ={auc_delta:+.4f}, tol={AUC_TOLERANCE})")
    log(f"    AUC Gap:   {new_gap:.4f}  (max={MAX_AUC_GAP})")
    log(f"    Test N:    {new_n_test}  (min=10)")

    if not auc_ok:
        log(f"    ⚠️  AUC drop exceeds tolerance")
    if not gap_ok:
        log(f"    ⚠️  Overfitting gap too large")
    if not data_ok:
        log(f"    ⚠️  Insufficient test data")

    return approved


def evaluate_volatility_model(
    staged_pkl: Path,
    staged_meta: Path,
    live_pkl: Path,
    live_meta: Path,
    symbol: str,
) -> bool:
    """Evaluate a single volatility model (regressor).
    
    Returns True if deployment is approved.
    """
    if not staged_meta.exists():
        log(f"  {symbol} (vol_v1): WARN - no staged meta file")
        return False

    with open(staged_meta) as f:
        new_meta = json.load(f)

    # If no live model exists, approve the new model
    if not live_meta.exists():
        log(f"  {symbol} (vol_v1): NEW MODEL - no live baseline, approving")
        return True

    with open(live_meta) as f:
        old_meta = json.load(f)

    # Extract metrics
    new_mae = new_meta.get("metrics", {}).get("test_mae", 999)
    old_mae = old_meta.get("metrics", {}).get("test_mae", 999)

    # Evaluation gates
    mae_delta = new_mae - old_mae
    mae_ok = new_mae <= old_mae + MAE_TOLERANCE

    approved = mae_ok

    status = "✅ PASS" if approved else "❌ FAIL"
    log(f"  {symbol} (vol_v1): {status}")
    log(f"    Test MAE:  {old_mae*100:.4f}% → {new_mae*100:.4f}%  (Δ={mae_delta*100:+.4f}%, tol={MAE_TOLERANCE*100:.2f}%)")

    if not mae_ok:
        log(f"    ⚠️  MAE increase exceeds tolerance")

    return approved


# ---------------------------------------------------------------------------
# Subcommand: deploy (atomic swap + server restart + health check)
# ---------------------------------------------------------------------------

def cmd_deploy(run_id: str):
    """Deploy staged models to production with atomic swap and rollback."""
    log(f"=== DEPLOY: Run ID = {run_id} ===")

    staging_dir = MODELS_STAGING_BASE / run_id
    if not staging_dir.exists():
        log(f"ERROR: Staging directory not found: {staging_dir}")
        sys.exit(1)

    # Create timestamped backup directory
    backup_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_dir = MODELS_BACKUP_BASE / backup_timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    # List of model directories to swap
    model_dirs = ["regime_v1", "regime_v2", "regime_v1_long", "vol_v1"]

    # --- Step 1: Backup current live models ---
    log("Backing up current live models...")
    for model_dir in model_dirs:
        live_dir = MODELS_LIVE_DIR / model_dir
        if live_dir.exists():
            shutil.copytree(live_dir, backup_dir / model_dir)
            log(f"  Backed up: {model_dir}")

    # --- Step 2: Atomic swap (remove old, move staged to live) ---
    log("Deploying staged models...")
    try:
        for model_dir in model_dirs:
            live_dir = MODELS_LIVE_DIR / model_dir
            staged_dir = staging_dir / model_dir

            if not staged_dir.exists():
                log(f"  WARN: Staged directory not found: {model_dir}, skipping")
                continue

            # Remove old live directory
            if live_dir.exists():
                shutil.rmtree(live_dir)

            # Move staged to live (atomic on same filesystem)
            shutil.move(str(staged_dir), str(live_dir))
            log(f"  Deployed: {model_dir}")

        # Write deployment manifest
        manifest = {
            "run_id": run_id,
            "timestamp": backup_timestamp,
            "deployed_at": datetime.now(timezone.utc).isoformat(),
            "backup_dir": str(backup_dir),
        }
        manifest_path = MODELS_LIVE_DIR / "DEPLOYED_RUN.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
        log(f"  Deployment manifest: {manifest_path}")

        # Push success metric
        push_metrics("deploy", {"ml_pipeline_deploy_success": 1})

    except Exception as e:
        log(f"ERROR during deployment: {e}")
        # Push failure metric
        push_metrics("deploy", {"ml_pipeline_deploy_success": 0})
        log("Rolling back from backup...")
        rollback_from_backup(backup_dir)
        sys.exit(1)

    # --- Step 3: Restart ML server ---
    log("Restarting ML server...")
    try:
        stop_ml_server()
        start_ml_server()
        verify_ml_server()
        log("✅ ML server restarted and verified")

    except Exception as e:
        log(f"ERROR: ML server health check failed: {e}")
        log("Rolling back from backup...")
        rollback_from_backup(backup_dir)
        stop_ml_server()
        start_ml_server()
        try:
            verify_ml_server()
            log("✅ Rollback successful, server healthy")
        except:
            log("❌ CRITICAL: Rollback failed, ML server not healthy")
            sys.exit(1)
        sys.exit(1)

    log("=== DEPLOY: Complete ===\n")


def rollback_from_backup(backup_dir: Path):
    """Restore models from backup directory."""
    log(f"Restoring from backup: {backup_dir}")

    model_dirs = ["regime_v1", "regime_v2", "regime_v1_long", "vol_v1"]

    for model_dir in model_dirs:
        backup_model_dir = backup_dir / model_dir
        live_dir = MODELS_LIVE_DIR / model_dir

        if not backup_model_dir.exists():
            continue

        # Remove current live directory
        if live_dir.exists():
            shutil.rmtree(live_dir)

        # Restore from backup
        shutil.copytree(backup_model_dir, live_dir)
        log(f"  Restored: {model_dir}")


def stop_ml_server():
    """Stop the ML server process."""
    if not SERVER_PID_FILE.exists():
        log("  No PID file found, server may not be running")
        return

    with open(SERVER_PID_FILE) as f:
        pid = int(f.read().strip())

    log(f"  Stopping ML server (PID={pid})...")

    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(2)

        # Check if still alive
        try:
            os.kill(pid, 0)
            log(f"  Process still alive, sending SIGKILL...")
            os.kill(pid, signal.SIGKILL)
            time.sleep(1)
        except OSError:
            pass  # Process is dead

        log("  ML server stopped")

    except ProcessLookupError:
        log("  Process already dead")

    # Remove PID file
    SERVER_PID_FILE.unlink(missing_ok=True)


def start_ml_server():
    """Start the ML server process."""
    log(f"  Starting ML server on port {SERVER_PORT}...")

    log_file = LOG_DIR / "ml_server.log"
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    with open(log_file, "a") as f:
        proc = subprocess.Popen(
            [sys.executable, str(SERVER_SCRIPT), "--models-dir", str(MODELS_LIVE_DIR), "--port", str(SERVER_PORT)],
            stdout=f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    # Write PID file
    with open(SERVER_PID_FILE, "w") as f:
        f.write(str(proc.pid))

    log(f"  ML server started (PID={proc.pid})")

    # Give it a moment to start
    time.sleep(2)


def verify_ml_server():
    """Verify ML server is healthy by polling /health endpoint."""
    import urllib.request
    import urllib.error

    url = f"http://localhost:{SERVER_PORT}/health"
    log(f"  Verifying ML server health ({url})...")

    start_time = time.time()
    while time.time() - start_time < SERVER_STARTUP_TIMEOUT:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    data = json.loads(response.read())
                    if data.get("status") == "ok":
                        log(f"  Health check: OK")
                        log(f"    XGB models: {len(data.get('xgb_models', []))}")
                        log(f"    Regime v1 models: {len(data.get('regime_v1_models', []))}")
                        log(f"    Regime v2 models: {len(data.get('regime_v2_models', []))}")
                        log(f"    Regime LONG models: {len(data.get('regime_long_models', []))}")
                        log(f"    Vol models: {len(data.get('vol_models', []))}")
                        return
        except (urllib.error.URLError, ConnectionRefusedError, TimeoutError):
            time.sleep(1)
            continue

    raise RuntimeError(f"ML server health check failed after {SERVER_STARTUP_TIMEOUT}s")


# ---------------------------------------------------------------------------
# Subcommand: run (all steps in sequence)
# ---------------------------------------------------------------------------

def cmd_run():
    """Execute all pipeline steps in sequence."""
    log("=== RUN: Full pipeline execution ===")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log(f"Run ID: {run_id}")

    # 1. Fetch
    cmd_fetch()

    # 2. Train
    cmd_train(run_id)

    # 3. Evaluate
    approved = cmd_evaluate(run_id)
    if not approved:
        log("❌ PIPELINE ABORTED: Evaluation rejected deployment")
        sys.exit(1)

    # 4. Deploy
    try:
        cmd_deploy(run_id)
        notify(f"🚀 ML Pipeline completed successfully!\nRun ID: {run_id}\nModels deployed and server restarted.")
        push_metrics("run", {"ml_pipeline_success": 1})
    except Exception as e:
        log(f"ERROR: Deployment failed: {e}")
        notify(f"⚠️ ML Pipeline deployment failed\nRun ID: {run_id}\nError: {e}", is_error=True)
        push_metrics("run", {"ml_pipeline_success": 0})
        sys.exit(1)

    log("=== RUN: Complete ===")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="ML Model Retraining Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommand")

    # fetch
    subparsers.add_parser("fetch", help="Incremental fetch from Binance")

    # train
    train_parser = subparsers.add_parser("train", help="Train models into staging")
    train_parser.add_argument("--run-id", required=True, help="Run ID (e.g., 20260209_1200)")

    # evaluate
    eval_parser = subparsers.add_parser("evaluate", help="Evaluate staged models")
    eval_parser.add_argument("--run-id", required=True, help="Run ID")

    # deploy
    deploy_parser = subparsers.add_parser("deploy", help="Deploy staged models")
    deploy_parser.add_argument("--run-id", required=True, help="Run ID")

    # run (all steps)
    subparsers.add_parser("run", help="Execute all steps in sequence")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Acquire lock (only for run command, other commands can be run manually)
    if args.command == "run":
        with FileLock(LOCK_FILE):
            cmd_run()
    elif args.command == "fetch":
        cmd_fetch()
    elif args.command == "train":
        cmd_train(args.run_id)
    elif args.command == "evaluate":
        approved = cmd_evaluate(args.run_id)
        sys.exit(0 if approved else 1)
    elif args.command == "deploy":
        cmd_deploy(args.run_id)


if __name__ == "__main__":
    main()

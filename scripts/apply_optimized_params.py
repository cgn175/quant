#!/usr/bin/env python3
"""Merge optimized params from opt/results/ into config.yaml.

Usage:
    python3 scripts/apply_optimized_params.py                  # dry-run (default)
    python3 scripts/apply_optimized_params.py --no-dry-run     # apply changes
"""

from __future__ import annotations

import argparse
import statistics
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

PARAM_MAP = {
    "donchian_period": ("strategy", "donchian_period"),
    "ema_fast": ("strategy", "ema_fast"),
    "ema_slow": ("strategy", "ema_slow"),
    "atr_stop_multiplier": ("strategy", "atr_stop_multiplier"),
    "adx_threshold": ("strategy", "adx_threshold"),
    "chandelier_lookback": ("strategy", "chandelier_lookback"),
}


def load_results(results_dir: Path) -> list[dict]:
    """Load all best_params_*.yaml files."""
    files = sorted(results_dir.glob("best_params_*.yaml"))
    results = []
    for f in files:
        with open(f) as fh:
            results.append(yaml.safe_load(fh))
    return results


def consensus_params(results: list[dict]) -> dict:
    """Compute consensus: if all agree use that value, else use median/mode."""
    if not results:
        return {}

    all_params = [r["params"] for r in results]
    keys = all_params[0].keys()
    consensus = {}

    for key in keys:
        values = [p[key] for p in all_params]
        unique = set(values)
        if len(unique) == 1:
            consensus[key] = values[0]
        elif isinstance(values[0], int):
            consensus[key] = int(round(statistics.median(values)))
        else:
            consensus[key] = round(statistics.median(values), 1)

    return consensus


def compute_diff(config: dict, new_params: dict) -> list[str]:
    """Return human-readable diff lines."""
    lines = []
    for param_name, (section, key) in PARAM_MAP.items():
        if param_name not in new_params:
            continue
        old_val = config.get(section, {}).get(key, "N/A")
        new_val = new_params[param_name]
        if old_val != new_val:
            lines.append(f"  {section}.{key}: {old_val} -> {new_val}")
        else:
            lines.append(f"  {section}.{key}: {old_val} (unchanged)")
    return lines


def apply_params(config: dict, new_params: dict) -> dict:
    """Apply new params into config dict (mutates and returns)."""
    for param_name, (section, key) in PARAM_MAP.items():
        if param_name not in new_params:
            continue
        if section not in config:
            config[section] = {}
        config[section][key] = new_params[param_name]
    return config


def main():
    parser = argparse.ArgumentParser(
        description="Apply optimized params to config.yaml"
    )
    parser.add_argument("--results-dir", type=str,
                        default=str(ROOT / "opt" / "results"))
    parser.add_argument("--config", type=str,
                        default=str(ROOT / "config.yaml"))
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Show diff without writing (default)")
    parser.add_argument("--no-dry-run", action="store_true",
                        help="Actually write changes")
    args = parser.parse_args()

    if args.no_dry_run:
        args.dry_run = False

    results_dir = Path(args.results_dir)
    config_path = Path(args.config)

    results = load_results(results_dir)
    if not results:
        print(f"No result files found in {results_dir}")
        return

    print(f"Loaded {len(results)} result file(s):")
    for r in results:
        print(f"  {r['symbol']}: Sortino={r['sortino_ratio']:.4f}")

    new_params = consensus_params(results)
    print(f"\nConsensus params: {new_params}")

    with open(config_path) as f:
        config = yaml.safe_load(f)

    diff = compute_diff(config, new_params)
    print("\nChanges:")
    for line in diff:
        print(line)

    if args.dry_run:
        print("\n(dry-run mode — no changes written)")
    else:
        apply_params(config, new_params)
        with open(config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        print(f"\nWritten to {config_path}")


if __name__ == "__main__":
    main()

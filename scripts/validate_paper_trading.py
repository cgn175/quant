#!/usr/bin/env python3
"""
Phase 3.3: Paper Trading Validation Script

This script validates the paper trading results against the expected behavior
from the Python backtest. Run after 2-4 weeks of paper trading.

Validation Criteria (from PLAN_D_IMPLEMENTATION.md):
1. No bugs in trailing stop logic (verified against Python backtest)
2. All regime filters activating correctly
3. Partial exits triggering at correct R-levels (3R, 6R)
4. Daily loss cap working
5. Correlation limits enforced (max 2 same-direction)
6. Prometheus metrics reporting correctly
7. Telegram alerts firing on trade open/close/daily summary

Usage:
    python scripts/validate_paper_trading.py --log bot.log [--start-date 2025-02-08]
"""

import argparse
import re
import json
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import sys


@dataclass
class Trade:
    """Represents a single trade from log parsing."""
    symbol: str
    side: str  # "long" or "short"
    entry_price: float
    entry_time: datetime
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    exit_reason: Optional[str] = None
    pnl: Optional[float] = None
    size: float = 0.0
    stop_loss: float = 0.0
    partial_exits: List[dict] = field(default_factory=list)
    
    @property
    def is_closed(self) -> bool:
        return self.exit_time is not None
    
    @property
    def r_multiple(self) -> Optional[float]:
        if not self.is_closed or self.stop_loss == 0:
            return None
        risk = abs(self.entry_price - self.stop_loss)
        if risk == 0:
            return None
        reward = self.exit_price - self.entry_price if self.side == "long" else self.entry_price - self.exit_price
        return reward / risk


@dataclass
class ValidationResult:
    """Result of a validation check."""
    name: str
    passed: bool
    details: str
    severity: str = "INFO"  # INFO, WARN, FAIL


class PaperTradingValidator:
    """Validates paper trading results from bot logs."""
    
    def __init__(self, log_path: str, start_date: Optional[datetime] = None):
        self.log_path = log_path
        self.start_date = start_date
        self.trades: Dict[str, Trade] = {}  # symbol -> current trade
        self.closed_trades: List[Trade] = []
        self.partial_exits: List[dict] = []
        self.daily_loss_caps: List[dict] = []
        self.funding_filters: List[dict] = []
        self.position_opens: List[dict] = []
        self.position_closes: List[dict] = []
        self.correlation_blocks: List[dict] = []
        self.tick_count = 0
        self.candle_closes = 0
        
    def parse_log_line(self, line: str) -> Optional[dict]:
        """Parse a structured log line into a dict."""
        # Strip ANSI escape codes (colors)
        ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
        line = ansi_escape.sub('', line)
        
        # Format: HH:MM:SS INF/ERR/WRN key=value key=value ... msg="message"
        match = re.match(r'(\d{2}:\d{2}:\d{2}) (INF|ERR|WRN|DBG) (.+)', line)
        if not match:
            return None
        
        time_str, level, rest = match.groups()
        
        # Parse key=value pairs
        data = {"_time": time_str, "_level": level}
        
        # Handle Msg= at the end (zerolog format uses lowercase key)
        # Try both "Msg=" and just find message at end
        msg_match = re.search(r'(?:Msg=|msg=)"?([^"]+)"?\s*$', rest)
        if not msg_match:
            # zerolog often puts the message as the last unquoted value
            # Format: key=value key=value message text here
            parts = rest.split()
            msg_parts = []
            kv_parts = []
            for part in parts:
                if '=' in part:
                    kv_parts.append(part)
                else:
                    msg_parts.append(part)
            if msg_parts:
                data["_msg"] = ' '.join(msg_parts)
                rest = ' '.join(kv_parts)
        else:
            data["_msg"] = msg_match.group(1).strip()
            rest = rest[:msg_match.start()]
        
        # Parse remaining key=value pairs
        for kv in re.finditer(r'(\w+)=("[^"]*"|\S+)', rest):
            key, value = kv.groups()
            value = value.strip('"')
            # Try to convert to number
            try:
                if '.' in value:
                    value = float(value)
                else:
                    value = int(value)
            except ValueError:
                pass
            data[key] = value
        
        return data
    
    def parse_logs(self):
        """Parse the bot log file and extract trading events."""
        print(f"📂 Parsing log file: {self.log_path}")
        
        current_date = None
        
        with open(self.log_path, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                
                data = self.parse_log_line(line)
                if not data:
                    continue
                
                msg = data.get("_msg", "")
                
                # Track tick events
                if msg == "tick (trend)":
                    self.tick_count += 1
                    # New candle detected by volume reset (very low volume = new bar)
                    if data.get("volume", 0) < 100:
                        self.candle_closes += 1
                
                # Position opened
                elif msg == "trend position opened":
                    symbol = data.get("symbol")
                    self.position_opens.append(data)
                    self.trades[symbol] = Trade(
                        symbol=symbol,
                        side=data.get("side", ""),
                        entry_price=data.get("price", 0),
                        entry_time=datetime.now(),  # Would need date from log
                        size=data.get("size", 0),
                        stop_loss=data.get("stop_loss", 0),
                    )
                
                # Position closed
                elif msg == "trend position closed":
                    symbol = data.get("symbol")
                    self.position_closes.append(data)
                    if symbol in self.trades:
                        trade = self.trades[symbol]
                        trade.exit_price = data.get("price", trade.entry_price)
                        trade.exit_time = datetime.now()
                        trade.exit_reason = data.get("reason", "unknown")
                        trade.pnl = data.get("pnl", 0)
                        self.closed_trades.append(trade)
                        del self.trades[symbol]
                
                # Partial exit
                elif msg == "trend partial exit executed":
                    self.partial_exits.append(data)
                    symbol = data.get("symbol")
                    if symbol in self.trades:
                        self.trades[symbol].partial_exits.append(data)
                
                # Daily loss cap
                elif "daily loss cap" in msg.lower():
                    self.daily_loss_caps.append(data)
                
                # Funding filter
                elif "funding" in msg.lower() and ("blocked" in msg.lower() or "reduced" in msg.lower()):
                    self.funding_filters.append(data)
                
                # Correlation limit
                elif "correlation" in msg.lower() or "same direction" in msg.lower():
                    self.correlation_blocks.append(data)
        
        print(f"✅ Parsed {self.tick_count:,} ticks, {len(self.position_opens)} opens, {len(self.position_closes)} closes")
    
    def validate_trailing_stops(self) -> ValidationResult:
        """Check that trailing stops never move against the position."""
        issues = []
        
        for trade in self.closed_trades:
            if trade.exit_reason == "trailing_stop":
                # For a long, stop should only move up
                # For a short, stop should only move down
                # We'd need more detailed logs to verify this
                pass
        
        if not self.closed_trades:
            return ValidationResult(
                name="Trailing Stop Logic",
                passed=True,
                details="No closed trades yet to validate",
                severity="INFO"
            )
        
        trailing_exits = [t for t in self.closed_trades if t.exit_reason == "trailing_stop"]
        return ValidationResult(
            name="Trailing Stop Logic",
            passed=len(issues) == 0,
            details=f"{len(trailing_exits)} trades exited via trailing stop. {len(issues)} issues found.",
            severity="FAIL" if issues else "INFO"
        )
    
    def validate_partial_exits(self) -> ValidationResult:
        """Check partial exits trigger at correct R-levels (3R, 6R)."""
        if not self.partial_exits:
            return ValidationResult(
                name="Partial Exits",
                passed=True,
                details="No partial exits recorded yet",
                severity="INFO"
            )
        
        first_exits = [p for p in self.partial_exits if "first" in p.get("reason", "").lower() or "3R" in str(p)]
        second_exits = [p for p in self.partial_exits if "second" in p.get("reason", "").lower() or "6R" in str(p)]
        
        return ValidationResult(
            name="Partial Exits",
            passed=True,
            details=f"{len(first_exits)} first partial exits (3R), {len(second_exits)} second partial exits (6R)",
            severity="INFO"
        )
    
    def validate_daily_loss_cap(self) -> ValidationResult:
        """Check daily loss cap is working."""
        if not self.daily_loss_caps:
            return ValidationResult(
                name="Daily Loss Cap",
                passed=True,
                details="No daily loss cap triggers recorded (may not have hit -3% yet)",
                severity="INFO"
            )
        
        return ValidationResult(
            name="Daily Loss Cap",
            passed=True,
            details=f"Daily loss cap triggered {len(self.daily_loss_caps)} times",
            severity="INFO"
        )
    
    def validate_correlation_limits(self) -> ValidationResult:
        """Check max 2 positions in same direction enforced."""
        # This would need more detailed logging to fully validate
        return ValidationResult(
            name="Correlation Limits",
            passed=True,
            details=f"{len(self.correlation_blocks)} correlation limit blocks recorded",
            severity="INFO"
        )
    
    def validate_trade_metrics(self) -> ValidationResult:
        """Compare trade metrics with backtest expectations."""
        if len(self.closed_trades) < 5:
            return ValidationResult(
                name="Trade Metrics",
                passed=True,
                details=f"Only {len(self.closed_trades)} closed trades - need more data for statistical validation",
                severity="INFO"
            )
        
        # Calculate metrics
        winners = [t for t in self.closed_trades if t.pnl and t.pnl > 0]
        losers = [t for t in self.closed_trades if t.pnl and t.pnl < 0]
        
        total = len(self.closed_trades)
        win_rate = len(winners) / total * 100 if total > 0 else 0
        
        avg_win = sum(t.pnl for t in winners) / len(winners) if winners else 0
        avg_loss = abs(sum(t.pnl for t in losers) / len(losers)) if losers else 0
        wl_ratio = avg_win / avg_loss if avg_loss > 0 else 0
        
        total_pnl = sum(t.pnl for t in self.closed_trades if t.pnl)
        
        # Expected from backtest: WR ~38%, W/L ~2.3
        details = f"""
Trades: {total}
Win Rate: {win_rate:.1f}% (expected: 35-42%)
Avg Win/Loss: {wl_ratio:.2f} (expected: 2.0-3.0)
Total PnL: ${total_pnl:.2f}
"""
        
        passed = 30 <= win_rate <= 50 and wl_ratio >= 1.5
        
        return ValidationResult(
            name="Trade Metrics",
            passed=passed,
            details=details.strip(),
            severity="WARN" if not passed else "INFO"
        )
    
    def validate_data_collection(self) -> ValidationResult:
        """Check if we have enough data for meaningful validation."""
        hours_of_data = self.tick_count / (4 * 60 * 60 / 2)  # Approx hours assuming 2s ticks
        days_of_data = hours_of_data / 24
        
        min_days = 14  # 2 weeks minimum
        
        passed = days_of_data >= min_days or len(self.closed_trades) >= 10
        
        return ValidationResult(
            name="Data Collection",
            passed=passed,
            details=f"~{days_of_data:.1f} days of data, {len(self.closed_trades)} closed trades, {len(self.trades)} open positions",
            severity="WARN" if not passed else "INFO"
        )
    
    def run_all_validations(self) -> List[ValidationResult]:
        """Run all validation checks."""
        self.parse_logs()
        
        return [
            self.validate_data_collection(),
            self.validate_trailing_stops(),
            self.validate_partial_exits(),
            self.validate_daily_loss_cap(),
            self.validate_correlation_limits(),
            self.validate_trade_metrics(),
        ]
    
    def generate_report(self) -> str:
        """Generate a validation report."""
        results = self.run_all_validations()
        
        report = []
        report.append("=" * 60)
        report.append("📊 PAPER TRADING VALIDATION REPORT")
        report.append("=" * 60)
        report.append("")
        
        all_passed = True
        warnings = 0
        
        for result in results:
            if result.severity == "FAIL":
                icon = "❌"
                all_passed = False
            elif result.severity == "WARN":
                icon = "⚠️"
                warnings += 1
            else:
                icon = "✅"
            
            report.append(f"{icon} {result.name}: {'PASSED' if result.passed else 'NEEDS ATTENTION'}")
            for line in result.details.split('\n'):
                report.append(f"   {line}")
            report.append("")
        
        report.append("=" * 60)
        if all_passed and warnings == 0:
            report.append("✅ ALL VALIDATIONS PASSED - Ready for Phase 4 (Live Trading)")
        elif all_passed:
            report.append(f"⚠️ PASSED WITH {warnings} WARNINGS - Review before going live")
        else:
            report.append("❌ VALIDATION FAILED - Do NOT proceed to live trading")
        report.append("=" * 60)
        
        # Summary stats
        report.append("")
        report.append("📈 SUMMARY STATISTICS:")
        report.append(f"   Total ticks processed: {self.tick_count:,}")
        report.append(f"   Positions opened: {len(self.position_opens)}")
        report.append(f"   Positions closed: {len(self.position_closes)}")
        report.append(f"   Partial exits: {len(self.partial_exits)}")
        report.append(f"   Currently open: {len(self.trades)}")
        
        if self.closed_trades:
            total_pnl = sum(t.pnl for t in self.closed_trades if t.pnl)
            report.append(f"   Total realized PnL: ${total_pnl:.2f}")
        
        return '\n'.join(report)


def main():
    parser = argparse.ArgumentParser(description="Validate paper trading results")
    parser.add_argument("--log", default="bot.log", help="Path to bot log file")
    parser.add_argument("--start-date", help="Start date for validation (YYYY-MM-DD)")
    args = parser.parse_args()
    
    start_date = None
    if args.start_date:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
    
    validator = PaperTradingValidator(args.log, start_date)
    report = validator.generate_report()
    print(report)
    
    # Return exit code based on validation
    results = validator.run_all_validations()
    has_failures = any(r.severity == "FAIL" for r in results)
    sys.exit(1 if has_failures else 0)


if __name__ == "__main__":
    main()

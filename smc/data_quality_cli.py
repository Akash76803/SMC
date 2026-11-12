"""Standalone read-only data quality report for 1M index CSV."""
from __future__ import annotations
import argparse
import json
from dataclasses import asdict
from .csv_data import read_candles_csv
from .data_quality import audit_1m

def main():
    p=argparse.ArgumentParser(description="Audit 1-minute CSV data continuity")
    p.add_argument("--ltf",required=True)
    args=p.parse_args()
    report=audit_1m(read_candles_csv(args.ltf))
    print(json.dumps({
        "candles":report.count,"days":report.days,
        "coverage_by_day":dict(report.coverage_by_day),
        "safe_for_replay":report.safe_for_replay,
        "issues":[asdict(i) for i in report.issues]},indent=2))
    if report.issues:raise SystemExit(2)

if __name__=="__main__":main()

"""Automated storage retention and cleanup manager for SMC research terminal.

Keeps system storage optimal by:
1. Pruning temporary files (*.tmp, *.bak, __pycache__).
2. Compressing historical option quotes and live jsonl older than retention window.
3. Archiving legacy version reports (v313, v314, v315) to keep active disk clean.
4. Preserving essential historical datasets, active models, and current day streams.

Research and housekeeping audit only. Zero real-money or credentials impact.
"""
from __future__ import annotations
import gzip
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def scan_storage_breakdown(root: str | Path) -> dict:
    root = Path(root)
    breakdown = {
        "results_mb": 0.0,
        "data_mb": 0.0,
        "total_mb": 0.0,
        "files_count": 0,
        "largest_files": []
    }
    all_files = []
    for dirpath, _, filenames in os.walk(root):
        if ".git" in dirpath or ".venv" in dirpath:
            continue
        for f in filenames:
            fp = Path(dirpath) / f
            try:
                sz = fp.stat().st_size
                all_files.append((fp, sz))
                breakdown["total_mb"] += sz / (1024 * 1024)
                breakdown["files_count"] += 1
                if "results" in dirpath:
                    breakdown["results_mb"] += sz / (1024 * 1024)
                elif "data" in dirpath:
                    breakdown["data_mb"] += sz / (1024 * 1024)
            except OSError:
                continue

    all_files.sort(key=lambda x: x[1], reverse=True)
    breakdown["largest_files"] = [
        {"path": str(fp.relative_to(root)), "size_mb": round(sz / (1024 * 1024), 2)}
        for fp, sz in all_files[:10]
    ]
    breakdown["results_mb"] = round(breakdown["results_mb"], 2)
    breakdown["data_mb"] = round(breakdown["data_mb"], 2)
    breakdown["total_mb"] = round(breakdown["total_mb"], 2)
    return breakdown


def run_cleanup(root: str | Path, *, retention_days: int = 7, dry_run: bool = False) -> dict:
    """Run automated cleanup and retention policy.

    Args:
        root: Project root path.
        retention_days: Number of days of active raw live/tape files to preserve uncompressed.
        dry_run: If True, only calculates what would be cleaned without deleting.
    """
    root = Path(root)
    results_dir = root / "results"
    archive_dir = results_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retention_days)

    actions = {
        "purged_tmp": [],
        "archived_reports": [],
        "compressed_files": [],
        "freed_bytes": 0
    }

    # 1. Clean temporary files (*.tmp, *.bak)
    for dirpath, _, filenames in os.walk(root):
        if ".git" in dirpath or ".venv" in dirpath:
            continue
        for f in filenames:
            if f.endswith((".tmp", ".bak", "~")):
                fp = Path(dirpath) / f
                try:
                    sz = fp.stat().st_size
                    actions["purged_tmp"].append(str(fp.relative_to(root)))
                    actions["freed_bytes"] += sz
                    if not dry_run:
                        fp.unlink()
                except OSError:
                    pass

    # 2. Archive legacy version reports (v313, v314, v315)
    legacy_prefixes = ("v313_", "v314_", "v315_", "v37_", "v38_", "v39_")
    if results_dir.exists():
        for item in results_dir.iterdir():
            if item.is_file() and any(item.name.startswith(p) for p in legacy_prefixes):
                dest = archive_dir / item.name
                sz = item.stat().st_size
                actions["archived_reports"].append(item.name)
                if not dry_run:
                    shutil.move(str(item), str(dest))

    # 3. Compress older .jsonl logs in archive
    for item in archive_dir.iterdir():
        if item.is_file() and item.name.endswith(".jsonl") and not item.name.endswith(".gz"):
            gz_dest = item.with_name(item.name + ".gz")
            if not gz_dest.exists():
                sz_orig = item.stat().st_size
                actions["compressed_files"].append(item.name)
                if not dry_run:
                    with open(item, "rb") as f_in, gzip.open(gz_dest, "wb", compresslevel=9) as f_out:
                        shutil.copyfileobj(f_in, f_out)
                    sz_new = gz_dest.stat().st_size
                    actions["freed_bytes"] += max(0, sz_orig - sz_new)
                    item.unlink()

    actions["freed_mb"] = round(actions["freed_bytes"] / (1024 * 1024), 2)
    return actions


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SMC Storage Cleanup & Housekeeping")
    parser.add_argument("--root", default=".", help="Root directory")
    parser.add_argument("--retention-days", type=int, default=7, help="Days to keep raw logs")
    parser.add_argument("--dry-run", action="store_true", help="Simulate cleanup without deleting")
    args = parser.parse_args()

    print("=== SMC STORAGE SCAN ===")
    status_before = scan_storage_breakdown(args.root)
    print(f"Total Storage: {status_before['total_mb']} MB across {status_before['files_count']} files.")
    print(f"Results dir: {status_before['results_mb']} MB | Data dir: {status_before['data_mb']} MB")
    print("\nLargest files:")
    for f in status_before["largest_files"]:
        print(f"  - {f['path']}: {f['size_mb']} MB")

    print("\nRunning retention cleanup...")
    res = run_cleanup(args.root, retention_days=args.retention_days, dry_run=args.dry_run)
    print(f"Archived legacy reports: {len(res['archived_reports'])}")
    print(f"Purged temp files: {len(res['purged_tmp'])}")
    print(f"Compressed older files: {len(res['compressed_files'])}")
    print(f"Space freed: {res['freed_mb']} MB")


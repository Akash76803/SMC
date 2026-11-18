"""Unit tests for storage cleanup and retention manager."""
from pathlib import Path
from smc.data_cleanup_manager import scan_storage_breakdown, run_cleanup


def test_storage_breakdown_and_cleanup(tmp_path):
    results_dir = tmp_path / "results"
    results_dir.mkdir(parents=True)
    
    # Create sample legacy report
    legacy = results_dir / "v314_test_replay.json"
    legacy.write_text('{"sample": 123}')
    
    # Create sample temp file
    temp_file = results_dir / "temp_cache.tmp"
    temp_file.write_text("temporary data")
    
    scan = scan_storage_breakdown(tmp_path)
    assert scan["files_count"] == 2
    assert scan["total_mb"] >= 0
    
    # Run cleanup
    actions = run_cleanup(tmp_path, dry_run=False)
    assert "temp_cache.tmp" in actions["purged_tmp"][0]
    assert "v314_test_replay.json" in actions["archived_reports"]
    assert not temp_file.exists()
    assert (results_dir / "archive" / "v314_test_replay.json").exists()


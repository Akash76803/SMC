from types import SimpleNamespace
from smc.replay_cli import summarize_snapshots

def test_snapshot_diagnostics_reason_counts():
    snapshots=[SimpleNamespace(state="WAIT",reason="NO_SWEEP_SETUP"),
               SimpleNamespace(state="WAIT",reason="NO_SWEEP_SETUP"),
               SimpleNamespace(state="NO_TRADE",reason="HTF_BIAS_MISMATCH"),
               SimpleNamespace(state="WAIT",reason="HTF_WARMUP")]
    result=summarize_snapshots(snapshots)
    assert result["states"]=={"NO_TRADE":1,"WAIT":3}
    assert result["reasons"]=={
        "HTF_BIAS_MISMATCH":1,"HTF_WARMUP":1,"NO_SWEEP_SETUP":2
    }
    empty=summarize_snapshots([])
    assert empty["states"]=={} and empty["reasons"]=={}
    assert empty["entry_state_observations"]=={}

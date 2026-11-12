from smc.replay_cli import summarize_snapshots
from smc.historical_replay import ReplaySnapshot

def test_stage_diagnostics():
    snapshots=[
        ReplaySnapshot(None,"WAIT","NO_CURRENT_RETEST",45,30,
                       (("WAITING_CHOCH",2),("EXPIRED",1)),
                       (("WAIT_FOR_CONFIRMED_CHOCH",2),("CHOCH_TIMEOUT",1))),
        ReplaySnapshot(None,"WAIT","NO_CURRENT_RETEST",46,30,
                       (("WAITING_CHOCH",1),("EXPIRED",2)),
                       (("WAIT_FOR_CONFIRMED_CHOCH",1),("CHOCH_TIMEOUT",2))),
    ]
    report=summarize_snapshots(snapshots)
    assert report["entry_state_observations"]=={"EXPIRED":3,"WAITING_CHOCH":3}
    assert report["entry_reason_observations"]["CHOCH_TIMEOUT"]==3
    assert report["last_evaluated_entry_states"]=={"EXPIRED":2,"WAITING_CHOCH":1}

def test_empty_stage_diagnostics():
    report=summarize_snapshots([ReplaySnapshot(None,"WAIT","NO_SWEEP_SETUP",1,1)])
    assert report["entry_state_observations"]=={}

from smc.smc_module_fvg import scan_smc_fvg
from smc.smc_module_mss import scan_smc_mss
from smc.smc_module_ob import scan_smc_ob
from smc.smc_module_sweep import scan_smc_sweep


def bars(rows):
    return [dict(timestamp=f'2026-11-18T09:{20 + 5 * i}:00+05:30',
                 open=o, high=h, low=l, close=c)
            for i, (o, h, l, c) in enumerate(rows)]


def test_confirmed_swing_sweep_and_displacement_are_independent():
    history = bars([(100, 105, 95, 103), (103, 110, 90, 99), (99, 105, 96, 101)])
    sweep, = scan_smc_sweep(history + bars([(0, 0, 0, 0)] * 3 + [(97, 102, 84, 100)])[3:],
                            interval_minutes=5)
    assert (sweep['direction'], sweep['stop_loss'], sweep['target']) == ('BULLISH', 82, 136)
    structure = bars([(100, 105, 95, 103), (103, 110, 90, 99),
                      (103, 105, 96, 101), (101, 120, 100, 119),
                      (111, 114, 104, 110)])
    shift, = scan_smc_mss(structure)
    block, = scan_smc_ob(structure, interval_minutes=5)
    assert shift['stop_loss'] == 100
    assert block['entry'] == 105 and block['risk_reward'] == 2.5


def test_fvg_requires_a_subsequent_midpoint_retest():
    history = bars([(100, 105, 95, 103), (103, 116, 101, 114), (116, 122, 113, 120),
                    (116, 117, 108, 111)])
    assert scan_smc_fvg(history[:3], interval_minutes=5) == []
    signal, = scan_smc_fvg(history, interval_minutes=5)
    assert signal['entry'] == 109 and signal['risk_reward'] == 2

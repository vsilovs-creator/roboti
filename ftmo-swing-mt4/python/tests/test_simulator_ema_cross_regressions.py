"""Regression tests for two P0 bugs found by an independent code audit
(2026-09-18, see docs/AUDIT_2026-09-18.md) in run_h1_signal_simulation:

1. A newly-opened position's own entry candle was never checked for
   SL/TP -- the exit-processing block ran BEFORE the position existed, so
   its own bar's intrabar move was silently skipped, turning what should
   have been a same-bar SL hit into a much worse "gap" exit on the
   following bar's open.
2. `new_idea_within_risk_caps` (the configured portfolio/correlated-group
   caps) was never called at all in this H1 simulator -- only the
   account-floor check ran, so `max_concurrent_risk_usd` and
   `correlated_group_max_risk_usd` had no effect regardless of value.

Both are fixed in simulator_ema_cross.py; these tests pin the fix down so
they can't silently regress.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ftmo_sim.bars import RichCandle
from ftmo_sim.config import load_config
from ftmo_sim.order_exec import Position
from ftmo_sim.simulator_ema_cross import _swap_usd_for_one_night, run_h1_signal_simulation
from ftmo_sim.strategy_ema_cross import EmaCrossSignal
from ftmo_sim.symbol_spec import SymbolSpec

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "config.example.json"

BASE = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)


def _flat_m1(symbol_price: float, hours: int = 12, kinks: dict | None = None) -> list[RichCandle]:
    kinks = kinks or {}
    bars = []
    t = BASE
    for _ in range(hours * 60):
        o = h = l = c = symbol_price
        if t in kinks:
            o, h, l, c = kinks[t]
        bars.append(RichCandle(open_time_utc=t, open=o, high=h, low=l, close=c))
        t += timedelta(minutes=1)
    return bars


class _OneShotSignalEngine:
    """Fires exactly one hand-crafted signal at a fixed H1 candle time."""

    def __init__(self, symbol, fire_at, direction="BUY", sl=1.09900, tp=1.20000):
        self.symbol = symbol
        self.fire_at = fire_at
        self.direction = direction
        self.sl = sl
        self.tp = tp
        self.fired = False

    def on_h1_candle(self, candle):
        if not self.fired and candle.open_time_utc == self.fire_at:
            self.fired = True
            return EmaCrossSignal(
                symbol=self.symbol, direction=self.direction, signal_close_time_utc=candle.open_time_utc,
                sl_price=self.sl, tp_price=self.tp, fast_ema=0, slow_ema=0, atr_h1=0,
            )
        return None


def test_entry_bar_sl_checked_not_skipped_to_next_bar_gap():
    cfg = load_config(CONFIG_PATH)
    entry_candle_time = BASE + timedelta(hours=11)
    kinks = {
        entry_candle_time: (1.10000, 1.10000, 1.09000, 1.09000),  # low breaches SL intrabar
        entry_candle_time + timedelta(minutes=1): (1.09000, 1.09000, 1.09000, 1.09000),
    }
    m1 = {
        "EURUSD": _flat_m1(1.10000, kinks=kinks),
        "GBPUSD": _flat_m1(1.30000),
    }
    engine_factory = lambda s: _OneShotSignalEngine(
        "EURUSD", fire_at=BASE + timedelta(hours=10),
    ) if s == "EURUSD" else _OneShotSignalEngine("GBPUSD", fire_at=BASE + timedelta(days=999))

    result = run_h1_signal_simulation(cfg, m1, engine_factory=engine_factory)
    assert len(result.closed_trades) == 1
    trade = result.closed_trades[0]
    # Fixed behavior: exits at the SL level, within the entry candle itself.
    assert trade.exit_reason == "SL"
    assert trade.exit_price == 1.09900
    # Loss should be close to the configured 25 USD risk budget, not the
    # ~223 USD a next-bar gap exit would produce.
    assert -30.0 < trade.net_pnl_usd < -20.0


def test_portfolio_cap_zero_blocks_all_entries():
    import json
    import tempfile

    raw = json.loads(CONFIG_PATH.read_text())
    raw["risk"]["max_concurrent_risk_usd"] = 0.0
    raw["risk"]["correlated_group_max_risk_usd"] = 0.0
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        json.dump(raw, tmp)
        tmp_path = Path(tmp.name)
    try:
        cfg = load_config(tmp_path)
        m1 = {"EURUSD": _flat_m1(1.10000), "GBPUSD": _flat_m1(1.30000)}
        engine_factory = lambda s: _OneShotSignalEngine(s, fire_at=BASE + timedelta(hours=10))
        result = run_h1_signal_simulation(cfg, m1, engine_factory=engine_factory)
        assert len(result.closed_trades) == 0
        assert any(sk.reason == "CORRELATED_OR_PORTFOLIO_RISK_CAP" for sk in result.skipped_signals)
    finally:
        tmp_path.unlink()


def test_correlated_group_cap_blocks_second_same_direction_symbol():
    import json
    import tempfile

    raw = json.loads(CONFIG_PATH.read_text())
    raw["risk"]["risk_per_idea_usd"] = 30.0  # 30+30=60 > 50 correlated cap
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        json.dump(raw, tmp)
        tmp_path = Path(tmp.name)
    try:
        cfg = load_config(tmp_path)
        fire_at = BASE + timedelta(hours=10)
        m1 = {"EURUSD": _flat_m1(1.10000), "GBPUSD": _flat_m1(1.30000)}
        sl_by_symbol = {"EURUSD": (1.09900, 1.20000), "GBPUSD": (1.29900, 1.40000)}
        engine_factory = lambda s: _OneShotSignalEngine(
            s, fire_at=fire_at, direction="BUY", sl=sl_by_symbol[s][0], tp=sl_by_symbol[s][1],
        )
        result = run_h1_signal_simulation(cfg, m1, engine_factory=engine_factory)
        # Both fire at the same H1 candle, same direction (both short-USD).
        # EURUSD is processed first and allowed (never appears in
        # skipped_signals; price is flat so it just stays open, hence not in
        # closed_trades either). GBPUSD must be blocked by the group cap.
        assert not any(sk.signal.symbol == "EURUSD" for sk in result.skipped_signals)
        gbp_skips = [sk for sk in result.skipped_signals if sk.signal.symbol == "GBPUSD"]
        assert len(gbp_skips) == 1
        assert gbp_skips[0].reason == "CORRELATED_OR_PORTFOLIO_RISK_CAP"
    finally:
        tmp_path.unlink()


EURUSD_SPEC = SymbolSpec(
    name="EURUSD", digits=5, contract_size=100000, min_lot=0.01, max_lot=50.0,
    lot_step=0.01, swap_long_points=-11.06, swap_short_points=0.59,
    triple_swap_weekday=2, quote_currency="USD",
)


def test_swap_usd_matches_hand_computed_value():
    pos = Position(
        idea_id="i1", symbol="EURUSD", direction="BUY", lots=2.0, entry_price=1.1000,
        sl=1.0950, tp=1.1100, entry_time_utc=None, risk_usd_at_entry=25.0,
    )
    # -11.06 points * 0.00001 point size * 100000 contract size * 2 lots = -22.12
    assert _swap_usd_for_one_night(pos, EURUSD_SPEC, night_starting_weekday=0) == pytest.approx(-22.12)
    # Same night but starting on the triple-swap weekday (Wednesday=2): x3.
    assert _swap_usd_for_one_night(pos, EURUSD_SPEC, night_starting_weekday=2) == pytest.approx(-66.36)


def test_swap_accrues_once_per_night_held_and_triples_on_wednesday():
    # 2026-01-05 is a Monday. A position opened that day and held flat
    # through the window crosses 4 FTMO-day rollovers: into Tue (normal),
    # into Wed (normal), into Thu (the night starting Wednesday -- tripled),
    # into Fri (normal). Total = 1 + 1 + 3 + 1 = 6 night-units.
    cfg = load_config(CONFIG_PATH)
    m1 = {
        "EURUSD": _flat_m1(1.10000, hours=4 * 24),
        "GBPUSD": _flat_m1(1.30000, hours=4 * 24),
    }
    engine_factory = lambda s: _OneShotSignalEngine(
        "EURUSD", fire_at=BASE + timedelta(hours=1),
    ) if s == "EURUSD" else _OneShotSignalEngine("GBPUSD", fire_at=BASE + timedelta(days=999))

    result = run_h1_signal_simulation(cfg, m1, engine_factory=engine_factory)
    assert len(result.closed_trades) == 0  # flat price, never hits SL/TP -- still open
    assert len(result.swap_ledger) == 4

    one_night = _swap_usd_for_one_night(
        Position(idea_id="x", symbol="EURUSD", direction="BUY", lots=result.swap_ledger[0][3],
                  entry_price=0, sl=0, tp=0, entry_time_utc=None, risk_usd_at_entry=0),
        cfg.symbols["EURUSD"], night_starting_weekday=0,
    )
    assert result.total_swap_usd == pytest.approx(6 * one_night)
    # FIXED 2026-09-18 (Codex F5): the still-open EURUSD position's
    # entry-side commission (2.50 USD/lot/side) was already deducted from
    # balance at open time -- final_balance must reflect it even though
    # the position never closes (never reaching the exit-side leg).
    entry_commission = result.open_positions_at_end["EURUSD"].entry_commission_usd
    assert entry_commission > 0.0
    assert result.final_balance == pytest.approx(
        cfg.initial_balance + result.total_swap_usd - entry_commission
    )


def test_same_tick_entry_risk_view_ignores_other_symbols_own_entry_bar_close():
    """A second, independent follow-up audit (2026-09-18) found that a
    symbol's OWN entry-bar close (only knowable later within that same
    minute) was leaking into another symbol's simultaneous entry decision
    via the correlated/portfolio risk-cap check, since a newly-opened
    position's "remaining risk" was computed from that bar's close rather
    than treated as its full, just-sized risk (no move has happened yet at
    the open). Reproduced: with only EURUSD's entry-minute CLOSE changed
    (its OPEN, and therefore its actual fill price, held fixed), GBPUSD's
    simultaneous entry outcome used to differ. Fixed; this pins it down."""
    import json
    import tempfile

    raw = json.loads(CONFIG_PATH.read_text())
    raw["risk"]["risk_per_idea_usd"] = 30.0
    raw["risk"]["correlated_group_max_risk_usd"] = 50.0
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        json.dump(raw, tmp)
        tmp_path = Path(tmp.name)
    try:
        cfg = load_config(tmp_path)
        fire_at = BASE + timedelta(hours=10)
        fill_time = fire_at + timedelta(hours=1)

        def flat_with_entry_bar_close(price, entry_bar_close):
            bars = []
            t = BASE
            for _ in range(12 * 60):
                o = h = l = c = price
                if t == fill_time:
                    o, c = price, entry_bar_close
                    h, l = max(o, c), min(o, c)
                bars.append(RichCandle(open_time_utc=t, open=o, high=h, low=l, close=c))
                t += timedelta(minutes=1)
            return bars

        results = []
        for eur_entry_bar_close in (1.10000, 1.11500):
            m1 = {
                "EURUSD": flat_with_entry_bar_close(1.10000, eur_entry_bar_close),
                "GBPUSD": _flat_m1(1.30000),
            }
            sl_by_symbol = {"EURUSD": (1.09900, 1.20000), "GBPUSD": (1.29900, 1.40000)}
            engine_factory = lambda s: _OneShotSignalEngine(
                s, fire_at=fire_at, direction="BUY", sl=sl_by_symbol[s][0], tp=sl_by_symbol[s][1],
            )
            result = run_h1_signal_simulation(cfg, m1, engine_factory=engine_factory)
            gbp_skip_reasons = [sk.reason for sk in result.skipped_signals if sk.signal.symbol == "GBPUSD"]
            results.append(gbp_skip_reasons)

        assert results[0] == results[1]
    finally:
        tmp_path.unlink()


class _ScriptedSignalEngine:
    """Fires a hand-scripted signal at each of several fixed H1 candle
    times -- used to test S4/S5's on_opposite_signal handling, which needs
    a SECOND (opposite-direction) signal to arrive while the first
    position from the same engine is still open."""

    def __init__(self, symbol, script: dict):
        self.symbol = symbol
        self.script = script  # {candle_open_time_utc: (direction, sl, tp)}

    def on_h1_candle(self, candle):
        entry = self.script.get(candle.open_time_utc)
        if entry is None:
            return None
        direction, sl, tp = entry
        return EmaCrossSignal(
            symbol=self.symbol, direction=direction, signal_close_time_utc=candle.open_time_utc,
            sl_price=sl, tp_price=tp, fast_ema=0, slow_ema=0, atr_h1=0,
        )


def _s4_s5_fixture():
    cfg = load_config(CONFIG_PATH)
    buy_fire_at = BASE + timedelta(hours=10)
    sell_fire_at = BASE + timedelta(hours=15)
    m1 = {
        "EURUSD": _flat_m1(1.10000, hours=24),
        "GBPUSD": _flat_m1(1.30000, hours=24),
    }
    script = {
        buy_fire_at: ("BUY", 1.09900, 1.20000),
        sell_fire_at: ("SELL", 1.10500, 1.00000),
    }
    engine_factory = lambda s: _ScriptedSignalEngine(s, script) if s == "EURUSD" else _ScriptedSignalEngine(s, {})
    return cfg, m1, engine_factory


def test_on_opposite_signal_skip_leaves_position_open_and_drops_new_signal():
    # S2/S3's existing, unchanged behaviour: the opposite signal is just
    # dropped, the original BUY position is left open untouched.
    cfg, m1, engine_factory = _s4_s5_fixture()
    result = run_h1_signal_simulation(cfg, m1, engine_factory=engine_factory, on_opposite_signal="skip")
    assert len(result.closed_trades) == 0
    assert "EURUSD" in result.open_positions_at_end
    assert result.open_positions_at_end["EURUSD"].direction == "BUY"
    assert any(sk.reason == "SYMBOL_ALREADY_HAS_OPEN_POSITION" for sk in result.skipped_signals)


def test_on_opposite_signal_close_only_exits_and_does_not_reopen():
    # S4: the opposite signal closes the open BUY position and is then
    # consumed -- no new SELL position opens from that same event.
    cfg, m1, engine_factory = _s4_s5_fixture()
    result = run_h1_signal_simulation(cfg, m1, engine_factory=engine_factory, on_opposite_signal="close_only")
    assert len(result.closed_trades) == 1
    assert result.closed_trades[0].exit_reason == "OPPOSITE_SIGNAL_EXIT"
    assert result.closed_trades[0].position.direction == "BUY"
    assert result.open_positions_at_end == {}
    assert any(sk.reason == "OPPOSITE_SIGNAL_CONSUMED_CLOSE_ONLY" for sk in result.skipped_signals)


def test_on_opposite_signal_close_and_reverse_exits_then_opens_new_idea():
    # S5: same close as S4, but then a fresh SELL idea opens from the same
    # signal event, sized independently (no doubling/no recovery sizing).
    cfg, m1, engine_factory = _s4_s5_fixture()
    result = run_h1_signal_simulation(cfg, m1, engine_factory=engine_factory, on_opposite_signal="close_and_reverse")
    assert len(result.closed_trades) == 1
    assert result.closed_trades[0].exit_reason == "OPPOSITE_SIGNAL_EXIT"
    assert result.closed_trades[0].position.direction == "BUY"
    assert "EURUSD" in result.open_positions_at_end
    reversed_pos = result.open_positions_at_end["EURUSD"]
    assert reversed_pos.direction == "SELL"
    # Sized fresh from the normal 25 USD budget, not doubled/related to the
    # just-closed BUY idea's lots.
    assert reversed_pos.risk_usd_at_entry <= cfg.risk_per_idea_usd + 1e-6
    assert not any(sk.reason == "OPPOSITE_SIGNAL_CONSUMED_CLOSE_ONLY" for sk in result.skipped_signals)


def _h1_bucket_m1(hour_index: int, open_, high_, low_, close_) -> list[RichCandle]:
    """60 M1 bars for one H1 bucket whose resample() aggregate has exactly
    the given open/high/low/close (assumes high_ is the true max and low_
    the true min across open_/close_ too, which every call site below
    respects)."""
    t = BASE + timedelta(hours=hour_index)
    bars = [RichCandle(open_time_utc=t, open=open_, high=open_, low=open_, close=open_)]
    bars.append(RichCandle(open_time_utc=t + timedelta(minutes=1), open=open_, high=high_, low=low_, close=close_))
    for m in range(2, 60):
        bars.append(RichCandle(open_time_utc=t + timedelta(minutes=m), open=close_, high=close_, low=close_, close=close_))
    return bars


def test_donchian_sl_anchored_to_actual_fill_not_signal_close_and_no_tp_trigger():
    """S6: SL = fill_price -/+ 2xATR, computed from the ACTUAL transacted
    fill (next H1 bar's M1 open), not the signal candle's own close -- and
    with no fixed TP, a large favorable move must never close the
    position via a fabricated TP level."""
    from ftmo_sim.strategy_donchian import DonchianAtrEngine

    cfg = load_config(CONFIG_PATH)
    engine_factory = lambda s: (
        DonchianAtrEngine(s, entry_period=3, exit_period=2, atr_period=1, atr_sl_multiple=2.0)
        if s == "EURUSD" else DonchianAtrEngine(s, entry_period=999, exit_period=999, atr_period=1, atr_sl_multiple=2.0)
    )

    eur_m1 = []
    eur_m1 += _h1_bucket_m1(0, 1.10000, 1.10000, 1.10000, 1.10000)
    eur_m1 += _h1_bucket_m1(1, 1.10000, 1.10000, 1.10000, 1.10000)
    eur_m1 += _h1_bucket_m1(2, 1.10000, 1.10000, 1.10000, 1.10000)
    # Breaks u3=1.10000 by a small amount -> small, realistic ATR -> BUY signal.
    eur_m1 += _h1_bucket_m1(3, 1.10000, 1.10030, 1.09990, 1.10020)
    # Fill bucket: a 50-pip gap up from the signal candle's own close
    # (1.10020) -- deliberately far, so an SL anchored to the signal
    # close vs. anchored to the real ~1.10500 fill land in clearly
    # different, non-overlapping ranges.
    eur_m1 += _h1_bucket_m1(4, 1.10500, 1.10520, 1.10490, 1.10500)
    # Then a huge favorable spike -- must NOT close via any TP (there is none).
    eur_m1 += _h1_bucket_m1(5, 1.10500, 5.00000, 1.10500, 1.10500)
    for extra_hour in range(6, 12):
        eur_m1 += _h1_bucket_m1(extra_hour, 1.10500, 1.10500, 1.10500, 1.10500)

    m1 = {"EURUSD": eur_m1, "GBPUSD": _flat_m1(1.30000, hours=12)}
    result = run_h1_signal_simulation(cfg, m1, engine_factory=engine_factory, on_opposite_signal="skip")

    assert len(result.closed_trades) == 0  # never hit any TP (there is none) or SL (never went low enough)
    assert "EURUSD" in result.open_positions_at_end
    pos = result.open_positions_at_end["EURUSD"]
    assert pos.tp is None
    # A signal-close-anchored SL would sit at roughly 1.10020 - 0.0008 =
    # ~1.0994; a fill-anchored SL sits much higher, near ~1.1042 -- assert
    # it landed in the fill-anchored range, not anywhere near the
    # signal-close-anchored one.
    assert pos.sl > 1.10000
    assert pos.sl < pos.entry_price


def test_donchian_discretionary_exit_closes_matching_direction_position():
    """S6: the 10-bar-extreme (here: 2-bar, for a compact test) crossing
    exit must actually close an open matching-direction position through
    the full run_h1_signal_simulation pipeline -- not just compute the
    right boolean in isolation (already covered by
    test_strategy_donchian.py's unit tests)."""
    from ftmo_sim.strategy_donchian import DonchianAtrEngine

    cfg = load_config(CONFIG_PATH)
    engine_factory = lambda s: (
        DonchianAtrEngine(s, entry_period=3, exit_period=2, atr_period=1, atr_sl_multiple=2.0)
        if s == "EURUSD" else DonchianAtrEngine(s, entry_period=999, exit_period=999, atr_period=1, atr_sl_multiple=2.0)
    )

    eur_m1 = []
    eur_m1 += _h1_bucket_m1(0, 1.10000, 1.10000, 1.10000, 1.10000)
    eur_m1 += _h1_bucket_m1(1, 1.10000, 1.10000, 1.10000, 1.10000)
    eur_m1 += _h1_bucket_m1(2, 1.10000, 1.10000, 1.10000, 1.10000)
    eur_m1 += _h1_bucket_m1(3, 1.10000, 1.10030, 1.09990, 1.10020)  # BUY entry signal
    eur_m1 += _h1_bucket_m1(4, 1.10500, 1.10520, 1.10490, 1.10500)  # fills here
    eur_m1 += _h1_bucket_m1(5, 1.10500, 5.00000, 1.10500, 1.10500)  # no TP to hit
    # Exit window going into hour 6 is {hour4, hour5} lows = {1.10490, 1.10500}
    # -> min = 1.10490. This candle's close breaks below it -> close_long.
    # Its own LOW (1.10445) is kept just above the SL (fill 1.10510 -
    # 2xATR 0.00080 = 1.10430) so the SL doesn't fire first intrabar.
    eur_m1 += _h1_bucket_m1(6, 1.10480, 1.10480, 1.10445, 1.10440)
    eur_m1 += _h1_bucket_m1(7, 1.10440, 1.10440, 1.10440, 1.10440)  # exit fills here
    for extra_hour in range(8, 12):
        eur_m1 += _h1_bucket_m1(extra_hour, 1.10440, 1.10440, 1.10440, 1.10440)

    m1 = {"EURUSD": eur_m1, "GBPUSD": _flat_m1(1.30000, hours=12)}
    result = run_h1_signal_simulation(cfg, m1, engine_factory=engine_factory, on_opposite_signal="skip")

    assert result.open_positions_at_end == {}
    assert len(result.closed_trades) == 1
    trade = result.closed_trades[0]
    assert trade.exit_reason == "DISCRETIONARY_EXIT"
    assert trade.position.direction == "BUY"
    assert trade.exit_time_utc == BASE + timedelta(hours=7)
    assert trade.exit_price == pytest.approx(1.10440)  # hour 7's M1 open, no slippage applied


def test_final_equity_matches_final_balance_when_last_tick_closes_last_position():
    """A second follow-up audit (2026-09-18) found that a trade opened and
    closed within the very LAST timestamp of a run updated final_balance
    but not the already-recorded last equity-curve point (which was
    recorded before that timestamp's own entries/closures happened) --
    final_equity could come back stale (still the untouched initial
    balance) while final_balance correctly reflected the loss. Reproduced
    exactly: balance 9974.70, open_positions 0, but final_equity 10000
    before the fix. With no open positions at the end, these two must
    agree."""
    cfg = load_config(CONFIG_PATH)
    fire_at = BASE + timedelta(hours=10)
    fill_time = fire_at + timedelta(hours=1)

    bars = []
    t = BASE
    while t <= fill_time:
        o = h = l = c = 1.10000
        if t == fill_time:
            o, h, l, c = 1.10000, 1.10000, 1.09000, 1.09000  # breaches its own SL intrabar
        bars.append(RichCandle(open_time_utc=t, open=o, high=h, low=l, close=c))
        t += timedelta(minutes=1)
    m1 = {
        "EURUSD": bars,
        "GBPUSD": [RichCandle(open_time_utc=b.open_time_utc, open=1.3, high=1.3, low=1.3, close=1.3) for b in bars],
    }

    engine_factory = lambda s: _OneShotSignalEngine(
        "EURUSD", fire_at=fire_at,
    ) if s == "EURUSD" else _OneShotSignalEngine("GBPUSD", fire_at=BASE + timedelta(days=999))

    result = run_h1_signal_simulation(cfg, m1, engine_factory=engine_factory)
    assert len(result.closed_trades) == 1
    assert result.open_positions_at_end == {}
    assert result.final_equity == pytest.approx(result.final_balance)
    assert result.final_balance < cfg.initial_balance  # sanity: the loss actually happened

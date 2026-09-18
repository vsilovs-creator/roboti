"""Spec section 9 test 11 (single-candle SL/TP collision) and section 8's
SL-first / no-double-spread / gap-fill rules."""
from datetime import datetime, timezone

from ftmo_sim.bars import RichCandle
from ftmo_sim.order_exec import force_close, open_position, simulate_exit
from ftmo_sim.symbol_spec import SymbolSpec

EURUSD = SymbolSpec(
    name="EURUSD", digits=5, contract_size=100000, min_lot=0.01, max_lot=50.0,
    lot_step=0.01, swap_long_points=-11.06, swap_short_points=0.59,
    triple_swap_weekday=2, quote_currency="USD",
)
SPREAD = 0.0001  # 10 points


def bar(h, m, o, hi, lo, cl):
    return RichCandle(open_time_utc=datetime(2026, 1, 5, h, m, tzinfo=timezone.utc), open=o, high=hi, low=lo, close=cl)


def test_same_bar_sl_and_tp_resolves_sl_first_and_flags_ambiguous():
    pos = open_position("i1", "EURUSD", "BUY", 1.0, 1.1000, sl=1.0990, tp=1.1020,
                         entry_time_utc=datetime(2026, 1, 5, 8, 10, tzinfo=timezone.utc), spread=SPREAD, risk_usd_at_entry=100.0)
    # One M1 candle whose range reaches both SL (1.0990) and TP (1.1020).
    ambiguous_bar = bar(8, 11, 1.1005, 1.1025, 1.0985, 1.1010)
    trade = simulate_exit(pos, [ambiguous_bar], EURUSD, "USD", SPREAD, None)
    assert trade is not None
    assert trade.exit_reason == "SL"
    assert trade.exit_price == 1.0990
    assert trade.same_bar_ambiguous is True
    assert trade.net_pnl_usd < 0


def test_gap_past_sl_fills_at_open_not_at_sl_level():
    pos = open_position("i1", "EURUSD", "BUY", 1.0, 1.1000, sl=1.0990, tp=1.1050,
                         entry_time_utc=datetime(2026, 1, 5, 8, 10, tzinfo=timezone.utc), spread=SPREAD, risk_usd_at_entry=100.0)
    # Next bar opens well below SL (a gap) -- must fill at the open, not 1.0990.
    gap_bar = bar(8, 11, 1.0950, 1.0955, 1.0940, 1.0945)
    trade = simulate_exit(pos, [gap_bar], EURUSD, "USD", SPREAD, None)
    assert trade.exit_reason == "SL_GAP"
    assert trade.exit_price == 1.0950
    assert trade.exit_price != pos.sl


def test_spread_charged_once_per_round_trip_long():
    bid_entry = 1.1000
    pos = open_position("i1", "EURUSD", "BUY", 1.0, bid_entry, sl=1.0950, tp=1.1050,
                         entry_time_utc=datetime(2026, 1, 5, 8, 10, tzinfo=timezone.utc), spread=SPREAD, risk_usd_at_entry=100.0)
    assert pos.entry_price == bid_entry + SPREAD  # bought at Ask
    tp_bar = bar(8, 11, 1.1040, 1.1055, 1.1035, 1.1045)  # bid high reaches TP
    trade = simulate_exit(pos, [tp_bar], EURUSD, "USD", SPREAD, None)
    assert trade.exit_reason == "TP"
    assert trade.exit_price == pos.tp  # exits at Bid, no second spread charge
    expected_gross = (pos.tp - pos.entry_price) * EURUSD.contract_size * pos.lots
    assert trade.gross_pnl_usd == expected_gross


def test_spread_charged_once_per_round_trip_short():
    bid_entry = 1.1000
    pos = open_position("i1", "EURUSD", "SELL", 1.0, bid_entry, sl=1.1050, tp=1.0950,
                         entry_time_utc=datetime(2026, 1, 5, 8, 10, tzinfo=timezone.utc), spread=SPREAD, risk_usd_at_entry=100.0)
    assert pos.entry_price == bid_entry  # sold at Bid
    tp_bar = bar(8, 11, 1.0960, 1.0965, 1.0945, 1.0955)  # bid low + spread reaches TP
    trade = simulate_exit(pos, [tp_bar], EURUSD, "USD", SPREAD, None)
    assert trade.exit_reason == "TP"
    expected_gross = (pos.entry_price - pos.tp) * EURUSD.contract_size * pos.lots
    assert trade.gross_pnl_usd == expected_gross


def test_commission_reduces_net_but_not_gross():
    pos = open_position("i1", "EURUSD", "BUY", 2.0, 1.1000, sl=1.0950, tp=1.1050,
                         entry_time_utc=datetime(2026, 1, 5, 8, 10, tzinfo=timezone.utc), spread=SPREAD, risk_usd_at_entry=100.0)
    tp_bar = bar(8, 11, 1.1040, 1.1055, 1.1035, 1.1045)
    trade = simulate_exit(pos, [tp_bar], EURUSD, "USD", SPREAD, commission_round_turn_usd_per_lot=7.0)
    assert trade.commission_usd == 14.0  # 7 USD/lot * 2 lots
    assert trade.net_pnl_usd == trade.gross_pnl_usd - 14.0


def test_session_close_forces_exit_at_1600_london():
    pos = open_position("i1", "EURUSD", "BUY", 1.0, 1.1000, sl=1.0950, tp=1.1050,
                         entry_time_utc=datetime(2026, 1, 5, 8, 10, tzinfo=timezone.utc), spread=SPREAD, risk_usd_at_entry=100.0)
    still_open_bar = bar(15, 59, 1.1010, 1.1015, 1.1005, 1.1012)
    close_bar = bar(16, 0, 1.1012, 1.1018, 1.1008, 1.1015)
    trade = simulate_exit(pos, [still_open_bar, close_bar], EURUSD, "USD", SPREAD, None)
    assert trade.exit_reason == "SESSION_CLOSE"
    assert trade.exit_time_utc == close_bar.open_time_utc


def test_slippage_worsens_market_entry_fill_for_both_directions():
    # docs/EXPERIMENT_PLAN_2026-09-18.md section 3 (C2/C3): adverse slippage
    # on a market ENTRY fill -- a BUY pays MORE, a SELL receives LESS.
    slip = 0.00005
    long_pos = open_position("i1", "EURUSD", "BUY", 1.0, 1.1000, sl=1.0950, tp=1.1050,
                              entry_time_utc=datetime(2026, 1, 5, 8, 10, tzinfo=timezone.utc),
                              spread=SPREAD, risk_usd_at_entry=100.0, slippage_price=slip)
    assert long_pos.entry_price == 1.1000 + SPREAD + slip
    short_pos = open_position("i1", "EURUSD", "SELL", 1.0, 1.1000, sl=1.1050, tp=1.0950,
                               entry_time_utc=datetime(2026, 1, 5, 8, 10, tzinfo=timezone.utc),
                               spread=SPREAD, risk_usd_at_entry=100.0, slippage_price=slip)
    assert short_pos.entry_price == 1.1000 - slip


def test_slippage_worsens_sl_fill_but_not_tp_fill():
    # SL is a stop-out (market fill) and gets slippage; TP does not.
    slip = 0.00005
    pos = open_position("i1", "EURUSD", "BUY", 1.0, 1.1000, sl=1.0950, tp=1.1050,
                         entry_time_utc=datetime(2026, 1, 5, 8, 10, tzinfo=timezone.utc), spread=SPREAD, risk_usd_at_entry=100.0)
    sl_bar = bar(8, 11, 1.0970, 1.0975, 1.0940, 1.0945)  # touches SL 1.0950, no gap
    trade = simulate_exit(pos, [sl_bar], EURUSD, "USD", SPREAD, None, slippage_price=slip)
    assert trade.exit_reason == "SL"
    assert trade.exit_price == pos.sl - slip  # worse (lower) than the raw SL level

    tp_pos = open_position("i1", "EURUSD", "BUY", 1.0, 1.1000, sl=1.0950, tp=1.1050,
                            entry_time_utc=datetime(2026, 1, 5, 8, 10, tzinfo=timezone.utc), spread=SPREAD, risk_usd_at_entry=100.0)
    tp_bar = bar(8, 11, 1.1040, 1.1055, 1.1035, 1.1045)
    tp_trade = simulate_exit(tp_pos, [tp_bar], EURUSD, "USD", SPREAD, None, slippage_price=slip)
    assert tp_trade.exit_reason == "TP"
    assert tp_trade.exit_price == tp_pos.tp  # unaffected by slippage


def test_slippage_worsens_gapped_sl_fill_in_the_same_adverse_direction():
    slip = 0.00005
    pos = open_position("i1", "EURUSD", "BUY", 1.0, 1.1000, sl=1.0990, tp=1.1050,
                         entry_time_utc=datetime(2026, 1, 5, 8, 10, tzinfo=timezone.utc), spread=SPREAD, risk_usd_at_entry=100.0)
    gap_bar = bar(8, 11, 1.0950, 1.0955, 1.0940, 1.0945)
    trade = simulate_exit(pos, [gap_bar], EURUSD, "USD", SPREAD, None, slippage_price=slip)
    assert trade.exit_reason == "SL_GAP"
    assert trade.exit_price == gap_bar.open - slip


def test_force_close_slippage_is_adverse_for_both_directions():
    slip = 0.00005
    long_pos = open_position("i1", "EURUSD", "BUY", 1.0, 1.1000, sl=1.0950, tp=1.1050,
                              entry_time_utc=datetime(2026, 1, 5, 8, 10, tzinfo=timezone.utc), spread=SPREAD, risk_usd_at_entry=100.0)
    trade = force_close(long_pos, 1.0995, datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc), "RISK_STOP",
                         EURUSD, "USD", None, slippage_price=slip)
    assert trade.exit_price == 1.0995 - slip

    short_pos = open_position("i1", "EURUSD", "SELL", 1.0, 1.1000, sl=1.1050, tp=1.0950,
                               entry_time_utc=datetime(2026, 1, 5, 8, 10, tzinfo=timezone.utc), spread=SPREAD, risk_usd_at_entry=100.0)
    trade2 = force_close(short_pos, 1.1005, datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc), "RISK_STOP",
                          EURUSD, "USD", None, slippage_price=slip)
    assert trade2.exit_price == 1.1005 + slip


def test_session_close_disabled_lets_swing_positions_hold_overnight():
    # A trend/swing strategy (strategy_ema_cross.py, strategy_bb_reversion.py)
    # is meant to hold across the 16:00 London boundary -- the force-close is
    # specific to the intraday London breakout baseline, not a universal rule.
    pos = open_position("i1", "EURUSD", "BUY", 1.0, 1.1000, sl=1.0950, tp=1.1050,
                         entry_time_utc=datetime(2026, 1, 5, 8, 10, tzinfo=timezone.utc), spread=SPREAD, risk_usd_at_entry=100.0)
    past_1600_bar = bar(20, 0, 1.1012, 1.1018, 1.1008, 1.1015)
    trade = simulate_exit(pos, [past_1600_bar], EURUSD, "USD", SPREAD, None, enforce_session_close=False)
    assert trade is None  # still open -- neither SL nor TP hit, and no forced close

"""Spec section 9 test 7 (lot-sizing half): lot-step rounding, minimum lot
exceeding the risk budget, and the cross-currency tick-value guard."""
import pytest

from ftmo_sim.symbol_spec import (
    SymbolSpec,
    floor_to_lot_step,
    lots_for_risk,
    risk_usd_for_lots,
    value_per_price_unit_per_lot,
)

EURUSD = SymbolSpec(
    name="EURUSD", digits=5, contract_size=100000, min_lot=0.01, max_lot=50.0,
    lot_step=0.01, swap_long_points=-11.06, swap_short_points=0.59,
    triple_swap_weekday=2, quote_currency="USD",
)


def test_floor_to_lot_step_rounds_down_never_up():
    assert floor_to_lot_step(0.239, 0.01) == 0.23
    assert floor_to_lot_step(0.01, 0.01) == 0.01
    assert floor_to_lot_step(0.0, 0.01) == 0.0
    assert floor_to_lot_step(0.009999, 0.01) == 0.0


def test_min_lot_exceeds_risk_budget_returns_zero():
    # A huge SL distance means even the minimum lot risks far more than the
    # budget -- the caller must skip the trade, never silently trade min lot.
    lots = lots_for_risk(risk_usd=1.0, sl_distance_price=0.05, spec=EURUSD, account_currency="USD")
    assert lots == 0.0


def test_lots_for_risk_matches_hand_computed_value():
    # risk=25 USD, sl_distance=0.0010 price units, contract 100000 ->
    # risk_per_lot = 0.0010*100000 = 100 USD/lot -> raw = 0.25 lots exactly.
    lots = lots_for_risk(risk_usd=25.0, sl_distance_price=0.0010, spec=EURUSD, account_currency="USD")
    assert lots == 0.25
    assert risk_usd_for_lots(lots, 0.0010, EURUSD, "USD") == pytest.approx(25.0)


def test_lots_clamped_to_max_lot():
    lots = lots_for_risk(risk_usd=1_000_000.0, sl_distance_price=0.0001, spec=EURUSD, account_currency="USD")
    assert lots == EURUSD.max_lot


def test_cross_currency_tick_value_not_silently_assumed():
    eur_account_symbol = SymbolSpec(
        name="GBPJPY", digits=3, contract_size=100000, min_lot=0.01, max_lot=50.0,
        lot_step=0.01, swap_long_points=0.0, swap_short_points=0.0,
        triple_swap_weekday=2, quote_currency="JPY",
    )
    with pytest.raises(NotImplementedError):
        value_per_price_unit_per_lot(eur_account_symbol, account_currency="USD")


def test_lots_for_risk_folds_in_extra_cost_per_lot():
    # Same scenario as test_lots_for_risk_matches_hand_computed_value
    # (risk=25, sl_distance=0.0010 -> 100 USD/lot from price alone), now with
    # a 5 USD/lot commission folded into the same 25 USD budget: per-lot
    # cost becomes 105 USD/lot -> 25/105 = 0.238... -> floors to 0.23 lots,
    # not the 0.25 lots price-alone sizing would give (2026-09-18 follow-up
    # audit: commission must not sit outside the planned risk budget).
    lots = lots_for_risk(
        risk_usd=25.0, sl_distance_price=0.0010, spec=EURUSD, account_currency="USD",
        extra_cost_usd_per_lot=5.0,
    )
    assert lots == 0.23
    total_risk = risk_usd_for_lots(lots, 0.0010, EURUSD, "USD", extra_cost_usd_per_lot=5.0)
    assert total_risk <= 25.0

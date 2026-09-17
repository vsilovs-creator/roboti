"""Instrument specification and cost/lot-sizing model.

Values here come from the instrument-specification screenshots (a snapshot,
not a guaranteed historical constant -- see docs/UNKNOWNS.md) and from the
config file. EURUSD and GBPUSD both quote in USD with a USD account currency,
so tick value conversion to account currency is direct; the conversion path
for a cross where quote currency != account currency is deliberately left
unimplemented (raises) rather than silently assumed.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal


@dataclass(frozen=True)
class SymbolSpec:
    name: str
    digits: int
    contract_size: float
    min_lot: float
    max_lot: float
    lot_step: float
    swap_long_points: float
    swap_short_points: float
    triple_swap_weekday: int  # Monday=0 .. Sunday=6
    quote_currency: str
    broker_suffix: str = ""

    @property
    def broker_symbol(self) -> str:
        return self.name + self.broker_suffix

    @property
    def point_size(self) -> float:
        return 10 ** (-self.digits)

    @classmethod
    def from_config(cls, name: str, cfg: dict) -> "SymbolSpec":
        weekday_map = {
            "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
            "Friday": 4, "Saturday": 5, "Sunday": 6,
        }
        return cls(
            name=name,
            digits=cfg["digits"],
            contract_size=cfg["contract_size"],
            min_lot=cfg["min_lot"],
            max_lot=cfg["max_lot"],
            lot_step=cfg["lot_step"],
            swap_long_points=cfg["swap_long_points"],
            swap_short_points=cfg["swap_short_points"],
            triple_swap_weekday=weekday_map[cfg["triple_swap_weekday"]],
            quote_currency=cfg["quote_currency"],
            broker_suffix=cfg.get("broker_suffix", ""),
        )


def value_per_price_unit_per_lot(spec: SymbolSpec, account_currency: str) -> float:
    """USD value of a 1.0-price-unit move for a 1.0-lot position.

    Only implemented for quote_currency == account_currency (true for
    EURUSD/GBPUSD against a USD account). Any other combination requires a
    currency conversion leg this prototype does not model, so it fails loudly
    instead of guessing a conversion rate.
    """
    if spec.quote_currency != account_currency:
        raise NotImplementedError(
            f"{spec.name}: quote currency {spec.quote_currency} != account currency "
            f"{account_currency}; cross-currency tick-value conversion is not implemented"
        )
    return spec.contract_size


def floor_to_lot_step(raw_lots: float, lot_step: float) -> float:
    """Round DOWN to the nearest lot step using Decimal to avoid float drift."""
    if raw_lots <= 0:
        return 0.0
    step = Decimal(str(lot_step))
    raw = Decimal(str(raw_lots))
    steps = (raw / step).to_integral_value(rounding=ROUND_DOWN)
    return float(steps * step)


def lots_for_risk(
    risk_usd: float,
    sl_distance_price: float,
    spec: SymbolSpec,
    account_currency: str,
) -> float:
    """Lot size (rounded down to lot_step, clamped to [0, max_lot]) whose
    worst-case loss at sl_distance_price does not exceed risk_usd.

    Returns 0.0 if even the minimum lot would exceed the risk budget --
    callers must treat 0.0 as "skip this trade", never silently trade the
    minimum lot anyway.
    """
    if sl_distance_price <= 0:
        return 0.0
    per_unit_per_lot = value_per_price_unit_per_lot(spec, account_currency)
    risk_per_lot = sl_distance_price * per_unit_per_lot
    if risk_per_lot <= 0:
        return 0.0
    raw_lots = risk_usd / risk_per_lot
    lots = floor_to_lot_step(raw_lots, spec.lot_step)
    lots = min(lots, spec.max_lot)
    if lots < spec.min_lot:
        return 0.0
    return lots


def risk_usd_for_lots(lots: float, sl_distance_price: float, spec: SymbolSpec, account_currency: str) -> float:
    per_unit_per_lot = value_per_price_unit_per_lot(spec, account_currency)
    return lots * sl_distance_price * per_unit_per_lot

#property strict
// SymbolSpec.mqh -- live instrument specs read from MarketInfo(), plus lot
// sizing. Never hardcode digits/contract size/lot step: read them live and
// fail closed if they look implausible.
// NOT_RUN: never compiled/tested. Mirrors ../../python/ftmo_sim/symbol_spec.py.

#ifndef FTMO_SYMBOLSPEC_MQH
#define FTMO_SYMBOLSPEC_MQH

struct SymbolSpec
  {
   string name;
   int    digits;
   double contractSize;
   double minLot;
   double maxLot;
   double lotStep;
   double stopsLevelPoints;
   double point;
  };

bool LoadSymbolSpec(string symbol, SymbolSpec &spec)
  {
   if(!MarketInfo(symbol, MODE_TRADEALLOWED) && MarketInfo(symbol, MODE_BID) == 0)
     {
      Print("FTMO: symbol not available / not selected: ", symbol);
      return false;
     }
   spec.name             = symbol;
   spec.digits           = (int)MarketInfo(symbol, MODE_DIGITS);
   spec.contractSize     = MarketInfo(symbol, MODE_LOTSIZE);
   spec.minLot           = MarketInfo(symbol, MODE_MINLOT);
   spec.maxLot           = MarketInfo(symbol, MODE_MAXLOT);
   spec.lotStep          = MarketInfo(symbol, MODE_LOTSTEP);
   spec.stopsLevelPoints = MarketInfo(symbol, MODE_STOPLEVEL);
   spec.point            = MarketInfo(symbol, MODE_POINT);
   if(spec.contractSize <= 0 || spec.lotStep <= 0 || spec.point <= 0)
     {
      Print("FTMO: implausible symbol spec for ", symbol, " -- refusing to trade it");
      return false;
     }
   return true;
  }

double FloorToLotStep(double rawLots, double lotStep)
  {
   if(rawLots <= 0) return 0.0;
   double steps = MathFloor(rawLots / lotStep + 1e-9);
   return steps * lotStep;
  }

// USD value of a 1.0-price-unit move for a 1.0-lot position. Only valid
// when the symbol's quote currency == account currency (true for
// EURUSD/GBPUSD on a USD account) -- MarketInfo has no direct "quote
// currency" constant in MQL4, so the caller is responsible for confirming
// this assumption per symbol (see docs/UNKNOWNS.md).
double ValuePerPriceUnitPerLot(const SymbolSpec &spec)
  {
   return spec.contractSize;
  }

// Lots (floored to lot step, clamped to [0, maxLot]) whose worst-case loss
// at slDistancePrice does not exceed riskUsd. Returns 0.0 if even the
// minimum lot would exceed budget -- caller must skip the trade, never
// silently use the minimum lot anyway.
double LotsForRisk(double riskUsd, double slDistancePrice, const SymbolSpec &spec)
  {
   if(slDistancePrice <= 0) return 0.0;
   double perLot = slDistancePrice * ValuePerPriceUnitPerLot(spec);
   if(perLot <= 0) return 0.0;
   double rawLots = riskUsd / perLot;
   double lots = FloorToLotStep(rawLots, spec.lotStep);
   if(lots > spec.maxLot) lots = spec.maxLot;
   if(lots < spec.minLot) return 0.0;
   return lots;
  }

double RiskUsdForLots(double lots, double slDistancePrice, const SymbolSpec &spec)
  {
   return lots * slDistancePrice * ValuePerPriceUnitPerLot(spec);
  }

#endif

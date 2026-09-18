#property strict
// AccountRisk.mqh -- account-wide floors and the pre-trade worst-case
// projected-equity check. Account-wide means ALL open positions on the
// account, not just this EA's MagicNumber -- see ScanAccountWideRisk().
// NOT_RUN: never compiled/tested. Mirrors ../../python/ftmo_sim/account_risk.py.

#ifndef FTMO_ACCOUNTRISK_MQH
#define FTMO_ACCOUNTRISK_MQH

#include "Config.mqh"

double RobotDailyWorkingFloor(double balanceAtMidnight)
  {
   return balanceAtMidnight - RobotDailyBufferUSD;
  }

double ApplicableRobotFloor(double balanceAtMidnight)
  {
   double daily = RobotDailyWorkingFloor(balanceAtMidnight);
   return MathMax(daily, RobotTotalFloorUSD);
  }

bool IsFloorBreached(double equity, double floorUsd)
  {
   return equity <= floorUsd;
  }

// Scans every open AND pending order on the ACCOUNT (not just this EA's
// MagicNumber): manual trades, other EAs, other symbols, other pendings.
// FIXED 2026-09-18 (follow-up audit): pending orders used to be skipped
// outright with the excuse "this EA never places pendings" -- the audit
// task explicitly rejects that excuse ("Pamatojums 'musu EA neveido
// pending' nav pietiekams"), since a MANUAL or FOREIGN pending order still
// carries real activation risk the account-wide check must see. Returns the
// sum of "remaining risk to SL" for OPEN positions (current mark-to-market
// price -> SL, NOT the full original risk -- that portion is already
// reflected in equity via floating P/L) via the return value, and the
// worst-case activation-then-SL risk for PENDING orders via
// pendingWorstCaseUsd. A position/pending with no SL contributes an
// explicitly large/unbounded flag so callers block new entries rather than
// silently ignoring unknown risk.
double ScanAccountWideRemainingRiskUsd(double &foreignUnknownRiskFlag, double &pendingWorstCaseUsd)
  {
   double total = 0.0;
   foreignUnknownRiskFlag = 0.0;
   pendingWorstCaseUsd = 0.0;
   for(int i = 0; i < OrdersTotal(); i++)
     {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      int type = OrderType();
      double sl = OrderStopLoss();
      double contractSize = MarketInfo(OrderSymbol(), MODE_LOTSIZE);

      if(type == OP_BUY || type == OP_SELL)
        {
         if(sl == 0.0)
           {
            foreignUnknownRiskFlag = 1.0; // unbounded risk -- caller must block entries
            continue;
           }
         double mark = (type == OP_BUY) ? MarketInfo(OrderSymbol(), MODE_BID)
                                         : MarketInfo(OrderSymbol(), MODE_ASK);
         double dist = (type == OP_BUY) ? (mark - sl) : (sl - mark);
         if(dist < 0) dist = 0; // already past SL and not yet closed -- no further downside modeled here
         total += dist * OrderLots() * contractSize;
        }
      else if(type == OP_BUYLIMIT || type == OP_SELLLIMIT || type == OP_BUYSTOP || type == OP_SELLSTOP)
        {
         if(sl == 0.0)
           {
            foreignUnknownRiskFlag = 1.0; // pending with no planned SL -- unbounded, block entries
            continue;
           }
         bool isBuySide = (type == OP_BUYLIMIT || type == OP_BUYSTOP);
         double activationPrice = OrderOpenPrice(); // the pending's trigger price
         double dist = isBuySide ? (activationPrice - sl) : (sl - activationPrice);
         if(dist < 0) dist = 0; // already-inverted pending -- treat as no further modeled downside here
         pendingWorstCaseUsd += dist * OrderLots() * contractSize;
        }
      // any other order type (balance/credit ops) is not a trade -- ignore.
     }
   return total;
  }

double PreTradeProjectedEquity(
   double currentEquity,
   double remainingOpenRiskUsd,
   double pendingWorstCaseUsd,
   double newOrderRiskUsd,
   double unaccountedCostsUsd,
   double executionBufferUsd)
  {
   return currentEquity - remainingOpenRiskUsd - pendingWorstCaseUsd - newOrderRiskUsd
          - unaccountedCostsUsd - executionBufferUsd;
  }

// BUY EURUSD/GBPUSD = long the pair = short USD; SELL = long USD. Mirrors
// ../../python/ftmo_sim/simulator.py::_direction_bucket exactly (same
// string labels) so any future cross-checking against the Python side is
// literal, not just conceptual.
string DirectionBucket(int orderType)
  {
   return (orderType == OP_SELL || orderType == OP_SELLLIMIT || orderType == OP_SELLSTOP)
          ? "LONG_USD" : "SHORT_USD";
  }

// Portfolio (MaxConcurrentRiskUSD) + correlated-group (CorrelatedGroupMaxRiskUSD)
// cap check for a NEW idea, scanning only THIS EA's OWN open positions on the
// two symbols it manages (Sym1/Sym2) -- mirrors
// ../../python/ftmo_sim/account_risk.py::new_idea_within_risk_caps, which is
// likewise evaluated only over the robot's own open ideas (foreign/manual
// risk is a separate, already-covered check via
// ScanAccountWideRemainingRiskUsd's projected-equity gate, not this cap).
// FIXED 2026-09-18 (follow-up audit): this was previously a documented gap
// ("NOTE: same correlated-group-cap gap") in both EA files with no actual
// enforcement. Both managed symbols are treated as ONE correlated group,
// matching config/config.example.json's single-group
// USD_MAJORS_DIRECTIONAL={EURUSD,GBPUSD} on the Python side -- if a future
// deployment manages symbols outside one correlated group, this must be
// revisited to take an explicit per-symbol group mapping instead of
// assuming "both managed symbols are correlated".
bool NewIdeaWithinRiskCaps(
   string sym1, string sym2,
   string newIdeaSymbol, string newIdeaDirectionBucket, double newIdeaRiskUsd,
   double maxConcurrentRiskUsd, double correlatedGroupMaxRiskUsd)
  {
   double totalOwnRisk = 0.0;
   double groupRiskSameDirection = 0.0;
   for(int i = 0; i < OrdersTotal(); i++)
     {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderMagicNumber() != MagicNumber) continue;
      int type = OrderType();
      if(type != OP_BUY && type != OP_SELL) continue;
      string sym = OrderSymbol();
      if(sym != sym1 && sym != sym2) continue; // not one of the two managed symbols

      double sl = OrderStopLoss();
      double mark = (type == OP_BUY) ? MarketInfo(sym, MODE_BID) : MarketInfo(sym, MODE_ASK);
      double dist = (sl == 0.0) ? 0.0 : ((type == OP_BUY) ? (mark - sl) : (sl - mark));
      if(dist < 0) dist = 0;
      double contractSize = MarketInfo(sym, MODE_LOTSIZE);
      double remaining = dist * OrderLots() * contractSize;

      totalOwnRisk += remaining;
      if(DirectionBucket(type) == newIdeaDirectionBucket)
         groupRiskSameDirection += remaining;
     }

   if(totalOwnRisk + newIdeaRiskUsd > maxConcurrentRiskUsd) return false;
   // Both managed symbols are one correlated group by construction here, so
   // the new idea's symbol is always "in the group" -- the group-membership
   // check the Python side does (group_for_symbol returning None for an
   // uncorrelated symbol) is a no-op given that assumption, kept explicit in
   // the comment above rather than in code.
   if(groupRiskSameDirection + newIdeaRiskUsd > correlatedGroupMaxRiskUsd) return false;
   return true;
  }

bool NewEntryAllowed(
   double currentEquity,
   double floorUsd,
   double remainingOpenRiskUsd,
   bool   foreignUnknownRisk,
   double pendingWorstCaseUsd,
   double newOrderRiskUsd,
   double unaccountedCostsUsd,
   double executionBufferUsd)
  {
   if(foreignUnknownRisk) return false; // unknown/unbounded risk on the account -- block, per spec section 4
   double projected = PreTradeProjectedEquity(
      currentEquity, remainingOpenRiskUsd, pendingWorstCaseUsd,
      newOrderRiskUsd, unaccountedCostsUsd, executionBufferUsd);
   return projected > floorUsd;
  }

#endif

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

// Scans every open order on the ACCOUNT (not just this EA's MagicNumber):
// manual trades, other EAs, other symbols. Returns the sum of "remaining
// risk to SL" (current mark-to-market price -> SL, NOT the full original
// risk -- that portion is already reflected in equity via floating P/L).
// A position with no SL contributes an explicitly large/unbounded number so
// callers block new entries rather than silently ignoring unknown risk.
double ScanAccountWideRemainingRiskUsd(double &foreignUnknownRiskFlag)
  {
   double total = 0.0;
   foreignUnknownRiskFlag = 0.0;
   for(int i = 0; i < OrdersTotal(); i++)
     {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderType() != OP_BUY && OrderType() != OP_SELL) continue; // ignore pendings here
      double sl = OrderStopLoss();
      if(sl == 0.0)
        {
         foreignUnknownRiskFlag = 1.0; // unbounded risk -- caller must block entries
         continue;
        }
      double mark = (OrderType() == OP_BUY) ? MarketInfo(OrderSymbol(), MODE_BID)
                                             : MarketInfo(OrderSymbol(), MODE_ASK);
      double dist = (OrderType() == OP_BUY) ? (mark - sl) : (sl - mark);
      if(dist < 0) dist = 0; // already past SL and not yet closed -- no further downside modeled here
      double contractSize = MarketInfo(OrderSymbol(), MODE_LOTSIZE);
      total += dist * OrderLots() * contractSize;
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

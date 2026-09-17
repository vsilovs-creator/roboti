#property strict
#property copyright "FTMO 2-Step Swing prototype -- EXPLORATORY, NOT_RUN (never compiled/tested)"
// FTMO_Swing_EA.mq4 -- single account controller for EURUSD+GBPUSD running
// the London Range Breakout + Retest v1 baseline (spec section 7) under the
// account-wide risk model (spec sections 4-6).
//
// STATUS: NOT_RUN. This file has never been opened in MetaEditor or compiled
// -- no MT4/MetaEditor was available in this environment. It is a faithful,
// structurally complete translation of the tested Python modules under
// ../../python/ftmo_sim/, offered so the design can be reviewed and then
// compiled/tested by someone with MT4 access, per the task's explicit
// instruction to proceed with authorized offline development regardless.
//
// Defaults to signal-only / dry-run: see EnableLiveTrading below. No EA may
// be attached to a real FTMO account by this deliverable -- that requires a
// separate, explicit authorization from the account owner.

#include "../Include/FTMO/Config.mqh"
#include "../Include/FTMO/TimeUtils.mqh"
#include "../Include/FTMO/SymbolSpec.mqh"
#include "../Include/FTMO/AccountRisk.mqh"
#include "../Include/FTMO/Persistence.mqh"
#include "../Include/FTMO/Logging.mqh"
#include "../Include/FTMO/Signals_LondonBreakoutRetest.mqh"
#include "../Include/FTMO/OrderExec.mqh"

input bool EnableLiveTrading = false; // false = signal-only/dry-run (default, per task scope)

RiskState g_state;
SymbolSpec g_spec1, g_spec2;
BreakoutRetestState g_br1, g_br2;
datetime g_lastM5_1 = 0, g_lastM5_2 = 0;
datetime g_lastH1_1 = 0, g_lastH1_2 = 0;

int OnInit()
  {
   if(!LoadSymbolSpec(Sym1(), g_spec1) || !LoadSymbolSpec(Sym2(), g_spec2))
     {
      Print("FTMO: FATAL -- could not load symbol specs, refusing to init");
      return INIT_FAILED;
     }
   if(!LoadRiskState(g_state))
     {
      Print("FTMO: FATAL -- risk state failed instance guard, refusing to init");
      return INIT_FAILED;
     }
   BR_Init(g_br1, Sym1());
   BR_Init(g_br2, Sym2());

   // Restart recovery: never trust "current balance" as midnight balance.
   // A real deployment must supply a verified reconstruction here; until
   // then entries stay blocked (historyReconciled=false) while protection
   // (existing SL/TP, the sticky total stop) remains fully active.
   if(g_state.currentFtmoDay == "")
      g_state.historyReconciled = false;

   if(!EnableLiveTrading)
      FtmoLog("INIT", "EnableLiveTrading=false -- running in signal-only/dry-run mode, no orders will be sent");

   SaveRiskState(g_state);
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   SaveRiskState(g_state);
  }

double AccountWideEquityIgnoringDoubleCount()
  {
   // AccountEquity() already reflects floating P/L from the broker directly
   // -- no manual re-derivation here, precisely to avoid the double-count
   // failure mode spec section 4 test 4 warns about.
   return AccountEquity();
  }

void ForceSessionCloseIfDue()
  {
   int londonHour = LondonHour(TimeGMT());
   if(londonHour < SessionCloseHourLondon) return;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderMagicNumber() != MagicNumber) continue;
      if(OrderType() != OP_BUY && OrderType() != OP_SELL) continue;
      if(!CloseOrderWithRetry(OrderTicket()))
         FtmoLog("SESSION", "failed to force-close ticket=" + IntegerToString(OrderTicket()) + " at session close -- will retry");
     }
  }

bool DetectNewClosedBar(string symbol, int timeframe, datetime &lastSeen)
  {
   datetime t = iTime(symbol, timeframe, 0);
   if(t == 0) return false; // no history yet
   if(t != lastSeen)
     {
      lastSeen = t;
      return true;
     }
   return false;
  }

void ProcessSymbolSignals(string symbol, SymbolSpec &spec, BreakoutRetestState &br,
                           datetime &lastM5, datetime &lastH1)
  {
   // H1 EMA update -- feed the newly closed H1 bar's close if one arrived.
   if(DetectNewClosedBar(symbol, PERIOD_H1, lastH1))
     {
      // iMA/iATR read the FULL history internally; no manual warmup needed
      // (unlike the Python engine, which has no indicator history to draw
      // on -- see the parity-test note in Signals_LondonBreakoutRetest.mqh).
     }
   bool h1Ready = (Bars(symbol, PERIOD_H1) >= EmaPeriodH1 + 5);
   double h1Close = iClose(symbol, PERIOD_H1, 1);
   double h1Ema   = iMA(symbol, PERIOD_H1, EmaPeriodH1, 0, MODE_EMA, PRICE_CLOSE, 1);

   if(!DetectNewClosedBar(symbol, PERIOD_M5, lastM5)) return;

   datetime openTime = iTime(symbol, PERIOD_M5, 1);
   double o = iOpen(symbol, PERIOD_M5, 1);
   double h = iHigh(symbol, PERIOD_M5, 1);
   double l = iLow(symbol, PERIOD_M5, 1);
   double c = iClose(symbol, PERIOD_M5, 1);
   bool atrReady = (Bars(symbol, PERIOD_M5) >= AtrPeriodM5 + 5);
   double atrVal = iATR(symbol, PERIOD_M5, AtrPeriodM5, 1);

   SignalEvent ev = BR_OnM5Candle(br, openTime, o, h, l, c, h1Close, h1Ema, h1Ready, atrVal, atrReady);
   if(!ev.valid) return;

   FtmoLog("SIGNAL", symbol + " confirmed " + (ev.direction == BR_DIR_BUY ? "BUY" : "SELL") +
           " sl=" + DoubleToString(ev.slPrice, spec.digits) + " tp=" + DoubleToString(ev.tpPrice, spec.digits));

   if(!CanOpenNewEntry(g_state, symbol))
     {
      FtmoLog("SIGNAL", symbol + " signal dropped -- entry not allowed (stop active, already used today, or unreconciled history)");
      return;
     }

   RefreshRates();
   double ask = MarketInfo(symbol, MODE_ASK);
   double bid = MarketInfo(symbol, MODE_BID);
   double transactedEntry = (ev.direction == BR_DIR_BUY) ? ask : bid;
   double slDistance = (ev.direction == BR_DIR_BUY) ? (transactedEntry - ev.slPrice) : (ev.slPrice - transactedEntry);
   if(slDistance <= 0)
     {
      FtmoLog("SIGNAL", symbol + " execution price already invalidates SL -- skipping");
      return;
     }

   double lots = LotsForRisk(RiskPerIdeaUSD, slDistance, spec);
   if(lots <= 0)
     {
      FtmoLog("SIGNAL", symbol + " min lot exceeds risk budget -- skipping");
      return;
     }
   double actualRisk = RiskUsdForLots(lots, slDistance, spec);

   double foreignUnknownRiskFlag = 0.0;
   double openRisk = ScanAccountWideRemainingRiskUsd(foreignUnknownRiskFlag);
   double floor = ApplicableRobotFloor(g_state.balanceAtMidnight);
   double equity = AccountWideEquityIgnoringDoubleCount();

   double unaccountedCosts = CommissionIsConfirmed() ? 0.0 : 0.0; // never fabricated; EXPLORATORY runs simply carry the label instead
   bool allowed = NewEntryAllowed(equity, floor, openRisk, foreignUnknownRiskFlag != 0.0,
                                  0.0, actualRisk, unaccountedCosts, ExecutionBufferUSD);
   if(!allowed)
     {
      FtmoLog("SIGNAL", symbol + " blocked by pre-trade projected-equity check");
      return;
     }
   // NOTE: the correlated-group cap (EURUSD+GBPUSD same-direction ideas
   // capped at CorrelatedGroupMaxRiskUSD) must additionally be checked here
   // against the OTHER managed symbol's open risk + direction before
   // sending -- omitted in this NOT_RUN skeleton for brevity; see
   // account_risk.py::new_idea_within_risk_caps for the exact rule to port.

   if(!EnableLiveTrading)
     {
      FtmoLog("DRYRUN", symbol + " would open " + DoubleToString(lots, 2) + " lots, risk=" + DoubleToString(actualRisk, 2));
      RegisterEntry(g_state, symbol);
      return;
     }

   int cmd = (ev.direction == BR_DIR_BUY) ? OP_BUY : OP_SELL;
   int ticket = OpenMarketOrderWithRetry(symbol, cmd, lots, ev.slPrice, ev.tpPrice, "FTMO-LRBR-v1");
   if(ticket >= 0) RegisterEntry(g_state, symbol);
  }

void OnTick()
  {
   string todayKey = FtmoTradingDayKey(TimeGMT());
   if(RolloverIfNeeded(g_state, todayKey, AccountBalance()))
      FtmoLog("ROLLOVER", "new FTMO day " + todayKey + " balance_at_midnight=" + DoubleToString(g_state.balanceAtMidnight, 2));

   double equity = AccountWideEquityIgnoringDoubleCount();
   bool wasStopped = StopActive(g_state);
   EvaluateRiskState(g_state, equity);
   if(StopActive(g_state) && !wasStopped)
     {
      SaveRiskState(g_state); // persist the stop BEFORE cancelling/closing, per spec section 4
      FtmoLog("RISK", "STOP TRIGGERED equity=" + DoubleToString(equity, 2) +
              " daily=" + (g_state.dailyStopActive ? "1" : "0") + " total=" + (g_state.totalStopActive ? "1" : "0"));
      if(EnableLiveTrading) CloseAllManagedPositionsAndPendings();
     }

   if(EnableLiveTrading) ForceSessionCloseIfDue();

   ProcessSymbolSignals(Sym1(), g_spec1, g_br1, g_lastM5_1, g_lastH1_1);
   ProcessSymbolSignals(Sym2(), g_spec2, g_br2, g_lastM5_2, g_lastH1_2);

   SaveRiskState(g_state);
  }

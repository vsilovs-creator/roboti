#property strict
#property copyright "FTMO 2-Step Swing prototype -- EXPLORATORY, NOT_RUN (never compiled/tested)"
// FTMO_Swing_EA_EmaCross.mq4 -- single account controller for EURUSD+GBPUSD
// running the EMA(20/50) H1 crossover, the CHOSEN strategy going forward
// (2026-09-18, account owner: smallest loss of three strategies compared on
// the only available ~2-month sample -- see
// python/reports/run_003_strategy_comparison/COMPARISON.md). No further
// historical data will be supplied, so this choice cannot be re-validated
// out-of-sample; see docs/UNKNOWNS.md and the main README.
//
// STATUS: NOT_RUN. This file has never been opened in MetaEditor or compiled
// -- no MT4/MetaEditor was available in this environment. It is a faithful,
// structurally complete translation of the tested Python
// strategy_ema_cross.py + simulator_ema_cross.py, offered for someone with
// MT4 access to compile, review, and test.
//
// Unlike FTMO_Swing_EA.mq4 (the London breakout, kept as reference only),
// this is a swing/trend design: it holds positions overnight and across the
// 16:00 London boundary by design, and has no session-window restriction --
// it can enter on any newly-closed H1 crossover.
//
// IMPORTANT: only ONE Expert Advisor from this project may be attached to a
// given account at a time. Persistence.mqh's risk-state file is keyed by
// account number only (by design, to enforce one controller per account
// per spec section 5) -- running this EA and FTMO_Swing_EA.mq4 on the same
// account simultaneously would have both processes racing to write the same
// state file. If both strategies are ever wanted at once, the persistence
// layer needs a shared/coordinated redesign first; that is out of scope
// here since only one strategy was chosen to carry forward.
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
#include "../Include/FTMO/Signals_EmaCross.mqh"
#include "../Include/FTMO/OrderExec.mqh"

input bool EnableLiveTrading = false; // false = signal-only/dry-run (default, per task scope)

RiskState g_state;
SymbolSpec g_spec1, g_spec2;
EmaCrossState g_ema1, g_ema2;

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
   EmaCross_Init(g_ema1, Sym1());
   EmaCross_Init(g_ema2, Sym2());

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
   return AccountEquity();
  }

bool DetectNewClosedBar(string symbol, int timeframe, datetime &lastSeen)
  {
   datetime t = iTime(symbol, timeframe, 0);
   if(t == 0) return false;
   if(t != lastSeen) { lastSeen = t; return true; }
   return false;
  }

void ProcessSymbolSignals(string symbol, SymbolSpec &spec, EmaCrossState &state)
  {
   if(!DetectNewClosedBar(symbol, PERIOD_H1, state.lastSeenH1Time)) return;
   if(Bars(symbol, PERIOD_H1) < EmaCrossSlowPeriodH1 + 5) return; // insufficient warmup -- "no signal", not a guess

   double closePrice = iClose(symbol, PERIOD_H1, 1);
   double fastEma = iMA(symbol, PERIOD_H1, EmaCrossFastPeriodH1, 0, MODE_EMA, PRICE_CLOSE, 1);
   double slowEma = iMA(symbol, PERIOD_H1, EmaCrossSlowPeriodH1, 0, MODE_EMA, PRICE_CLOSE, 1);
   double atrH1   = iATR(symbol, PERIOD_H1, EmaCrossAtrPeriodH1, 1);

   EmaCrossSignal ev = EmaCross_OnH1Candle(state, iTime(symbol, PERIOD_H1, 1), closePrice, fastEma, slowEma, atrH1);
   if(!ev.valid) return;

   FtmoLog("SIGNAL", symbol + " EMA cross " + (ev.direction == 1 ? "BUY" : "SELL") +
           " sl=" + DoubleToString(ev.slPrice, spec.digits) + " tp=" + DoubleToString(ev.tpPrice, spec.digits));

   if(!g_state.historyReconciled || StopActive(g_state))
     {
      FtmoLog("SIGNAL", symbol + " signal dropped -- entry not allowed (stop active or unreconciled history)");
      return;
     }
   if(HasOpenOrderForSymbol(symbol))
     {
      FtmoLog("SIGNAL", symbol + " signal dropped -- a position is already open for this symbol");
      return;
     }

   RefreshRates();
   double ask = MarketInfo(symbol, MODE_ASK);
   double bid = MarketInfo(symbol, MODE_BID);
   double transactedEntry = (ev.direction == 1) ? ask : bid;
   double slDistance = (ev.direction == 1) ? (transactedEntry - ev.slPrice) : (ev.slPrice - transactedEntry);
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
   bool allowed = NewEntryAllowed(equity, floor, openRisk, foreignUnknownRiskFlag != 0.0,
                                  0.0, actualRisk, 0.0, ExecutionBufferUSD);
   if(!allowed)
     {
      FtmoLog("SIGNAL", symbol + " blocked by pre-trade projected-equity check");
      return;
     }
   // NOTE: same correlated-group-cap gap as FTMO_Swing_EA.mq4 -- see that
   // file's matching comment and account_risk.py::new_idea_within_risk_caps.

   if(!EnableLiveTrading)
     {
      FtmoLog("DRYRUN", symbol + " would open " + DoubleToString(lots, 2) + " lots, risk=" + DoubleToString(actualRisk, 2));
      return;
     }

   int cmd = (ev.direction == 1) ? OP_BUY : OP_SELL;
   OpenMarketOrderWithRetry(symbol, cmd, lots, ev.slPrice, ev.tpPrice, "FTMO-EMACROSS-v1");
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

   // No forced session close here: this is a swing/trend strategy meant to
   // hold across the 16:00 London boundary (unlike FTMO_Swing_EA.mq4).

   ProcessSymbolSignals(Sym1(), g_spec1, g_ema1);
   ProcessSymbolSignals(Sym2(), g_spec2, g_ema2);

   SaveRiskState(g_state);
  }

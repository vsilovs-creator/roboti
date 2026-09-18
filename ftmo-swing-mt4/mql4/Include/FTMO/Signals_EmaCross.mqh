#property strict
// Signals_EmaCross.mqh -- EMA(20/50) H1 crossover, CHOSEN strategy going
// forward (2026-09-18, account owner: smallest loss of three strategies
// compared on the only available ~2-month sample; see
// python/reports/run_003_strategy_comparison/COMPARISON.md).
// NOT_RUN: never compiled/tested. Mirrors ../../python/ftmo_sim/strategy_ema_cross.py.
//
// Unlike the London breakout engine, this one uses MT4's own iMA/iATR
// directly (no manual EMA/ATR warmup state needed) since it only needs the
// two most recently closed H1 bars' fast/slow EMA values to detect a cross.

#ifndef FTMO_SIGNALS_EMACROSS_MQH
#define FTMO_SIGNALS_EMACROSS_MQH

#include "Config.mqh"

struct EmaCrossState
  {
   string   symbol;
   datetime lastSeenH1Time;
   bool     havePrev;
   double   prevFast;
   double   prevSlow;
  };

struct EmaCrossSignal
  {
   bool   valid;
   string symbol;
   int    direction; // reuse BR_DIR_BUY / BR_DIR_SELL constants from Signals_LondonBreakoutRetest.mqh
   double slPrice;
   double tpPrice;
  };

void EmaCross_Init(EmaCrossState &s, string symbol)
  {
   s.symbol = symbol;
   s.lastSeenH1Time = 0;
   s.havePrev = false;
   s.prevFast = 0;
   s.prevSlow = 0;
  }

// Call once per newly-CLOSED H1 candle (shift=1). Requires enough H1 history
// for both EMAs and the ATR to be meaningful (Bars() >= slow period + margin);
// the caller should skip calling this (or ignore its result) until then, the
// same way ProcessSymbolSignals in the EA checks Bars() before trusting
// iMA/iATR.
EmaCrossSignal EmaCross_OnH1Candle(
   EmaCrossState &s, datetime openTimeUtc, double closePrice,
   double fastEma, double slowEma, double atrH1)
  {
   EmaCrossSignal ev; ev.valid = false;

   if(s.havePrev)
     {
      bool crossedUp   = (s.prevFast <= s.prevSlow) && (fastEma > slowEma);
      bool crossedDown = (s.prevFast >= s.prevSlow) && (fastEma < slowEma);
      if(crossedUp || crossedDown)
        {
         double buffer = EmaCrossAtrSlMultiple * atrH1;
         double sl, tp;
         if(crossedUp)
           {
            sl = closePrice - buffer;
            tp = closePrice + EmaCrossTpRMultiple * buffer;
            ev.direction = 1; // BR_DIR_BUY
           }
         else
           {
            sl = closePrice + buffer;
            tp = closePrice - EmaCrossTpRMultiple * buffer;
            ev.direction = 2; // BR_DIR_SELL
           }
         ev.valid = true;
         ev.symbol = s.symbol;
         ev.slPrice = sl;
         ev.tpPrice = tp;
        }
     }

   s.prevFast = fastEma;
   s.prevSlow = slowEma;
   s.havePrev = true;
   return ev;
  }

#endif

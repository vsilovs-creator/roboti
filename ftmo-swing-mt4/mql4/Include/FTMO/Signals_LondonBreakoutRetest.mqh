#property strict
// Signals_LondonBreakoutRetest.mqh -- London Range Breakout + Retest v1,
// spec section 7, one instance of BreakoutRetestState per symbol.
// NOT_RUN: never compiled/tested. Mirrors ../../python/ftmo_sim/signals.py;
// keep both in sync if the rules change (see docs for the parity-test plan).
//
// Unlike the Python engine (which hand-rolls Wilder ATR / seeded EMA because
// it has no indicator history to draw on), this side uses MT4's own
// iATR/iMA so the *values* may differ slightly near warmup boundaries --
// exactly the parity gap spec section 8 requires testing before trusting
// both engines to agree bar-for-bar.

#ifndef FTMO_SIGNALS_MQH
#define FTMO_SIGNALS_MQH

#include "Config.mqh"
#include "TimeUtils.mqh"

#define BR_WAITING_RANGE     0
#define BR_WAITING_BREAKOUT  1
#define BR_AWAITING_RETEST   2
#define BR_DONE_FOR_DAY      3
#define BR_DAY_SKIPPED       4

#define BR_DIR_NONE 0
#define BR_DIR_BUY  1
#define BR_DIR_SELL 2

struct BreakoutRetestState
  {
   string   symbol;
   int      state;
   string   currentDay;
   double   rangeHigh;
   double   rangeLow;
   int      rangeCandleCount;
   double   prevM5Close;
   int      pendingDirection;
   int      pendingBarsWaited;
   datetime lastSeenM5Time;
  };

struct SignalEvent
  {
   bool     valid;
   string   symbol;
   int      direction;
   datetime retestCloseTimeUtc;
   double   rangeHigh;
   double   rangeLow;
   double   slPrice;
   double   tpPrice;
   double   atrAtRetest;
   double   emaH1AtRetest;
  };

void BR_Init(BreakoutRetestState &s, string symbol)
  {
   s.symbol = symbol;
   s.state = BR_WAITING_RANGE;
   s.currentDay = "";
   s.rangeHigh = 0; s.rangeLow = 0;
   s.rangeCandleCount = 0;
   s.prevM5Close = 0;
   s.pendingDirection = BR_DIR_NONE;
   s.pendingBarsWaited = 0;
   s.lastSeenM5Time = 0;
  }

void BR_StartNewDay(BreakoutRetestState &s, string dayKey)
  {
   s.currentDay = dayKey;
   s.state = BR_WAITING_RANGE;
   s.rangeHigh = 0; s.rangeLow = 0;
   s.rangeCandleCount = 0;
   s.pendingDirection = BR_DIR_NONE;
   s.pendingBarsWaited = 0;
  }

void BR_FinalizeRange(BreakoutRetestState &s, double minCoverageRatio, int expectedCandles)
  {
   if(s.rangeCandleCount == 0)
     {
      s.state = BR_DAY_SKIPPED;
      FtmoLog("SIGNAL", s.symbol + " " + s.currentDay + " NO_RANGE_DATA");
      return;
     }
   double coverage = (double)s.rangeCandleCount / (double)expectedCandles;
   if(coverage < minCoverageRatio)
     {
      s.state = BR_DAY_SKIPPED;
      FtmoLog("SIGNAL", s.symbol + " " + s.currentDay + " INSUFFICIENT_RANGE_COVERAGE " + DoubleToString(coverage, 2));
      return;
     }
   s.state = BR_WAITING_BREAKOUT;
  }

int BR_DetectBreakout(BreakoutRetestState &s, double close)
  {
   if(s.prevM5Close == 0) return BR_DIR_NONE;
   if(close > s.rangeHigh && s.prevM5Close <= s.rangeHigh) return BR_DIR_BUY;
   if(close < s.rangeLow && s.prevM5Close >= s.rangeLow) return BR_DIR_SELL;
   return BR_DIR_NONE;
  }

// Call once per newly-CLOSED M5 candle (shift=1 relative to the tick that
// detected the new bar). Requires FtmoLog (Logging.mqh) included by caller.
SignalEvent BR_OnM5Candle(
   BreakoutRetestState &s,
   datetime openTimeUtc, double o, double h, double l, double c,
   double lastClosedH1Close, double lastClosedH1Ema, bool h1Ready,
   double atrM5Value, bool atrReady)
  {
   SignalEvent ev; ev.valid = false;

   string dayKey = TimeToString(UtcToLondon(openTimeUtc), TIME_DATE);
   if(dayKey != s.currentDay) BR_StartNewDay(s, dayKey);

   if(s.state == BR_DAY_SKIPPED) { s.prevM5Close = c; return ev; }

   int londonHour = LondonHour(openTimeUtc);
   bool inRange  = (londonHour >= RangeStartHourLondon && londonHour < RangeEndHourLondon);
   bool inEntry  = (londonHour >= EntryStartHourLondon && londonHour < EntryEndHourLondon);

   if(inRange)
     {
      s.rangeCandleCount++;
      s.rangeHigh = (s.rangeCandleCount == 1) ? h : MathMax(s.rangeHigh, h);
      s.rangeLow  = (s.rangeCandleCount == 1) ? l : MathMin(s.rangeLow, l);
      s.prevM5Close = c;
      return ev;
     }

   if(s.state == BR_WAITING_RANGE)
     {
      int expected = (int)((RangeEndHourLondon - RangeStartHourLondon) * 60 / 5);
      BR_FinalizeRange(s, 0.85, expected);
     }

   if(s.state == BR_DONE_FOR_DAY || s.state == BR_DAY_SKIPPED) { s.prevM5Close = c; return ev; }

   if(s.state == BR_WAITING_BREAKOUT)
     {
      if(inEntry)
        {
         int dir = BR_DetectBreakout(s, c);
         if(dir != BR_DIR_NONE)
           {
            s.pendingDirection = dir;
            s.pendingBarsWaited = 0;
            s.state = BR_AWAITING_RETEST;
           }
        }
     }
   else if(s.state == BR_AWAITING_RETEST)
     {
      s.pendingBarsWaited++;
      bool confirmed = false;
      if(s.pendingDirection == BR_DIR_BUY)
        {
         if(l < s.rangeLow) { s.pendingDirection = BR_DIR_NONE; s.state = BR_WAITING_BREAKOUT; s.prevM5Close = c; return ev; }
         if(l <= s.rangeHigh && c > s.rangeHigh) confirmed = true;
        }
      else
        {
         if(h > s.rangeHigh) { s.pendingDirection = BR_DIR_NONE; s.state = BR_WAITING_BREAKOUT; s.prevM5Close = c; return ev; }
         if(h >= s.rangeLow && c < s.rangeLow) confirmed = true;
        }

      if(confirmed)
        {
         bool stillInEntryWindow = inEntry;
         bool filterOk = h1Ready &&
            ((s.pendingDirection == BR_DIR_BUY  && lastClosedH1Close > lastClosedH1Ema) ||
             (s.pendingDirection == BR_DIR_SELL && lastClosedH1Close < lastClosedH1Ema));

         if(!stillInEntryWindow || !atrReady || !filterOk)
           {
            s.pendingDirection = BR_DIR_NONE;
            s.state = BR_WAITING_BREAKOUT;
           }
         else
           {
            double buffer = SlAtrBufferMultiple * atrM5Value;
            double sl, tp, riskDist;
            if(s.pendingDirection == BR_DIR_BUY)
              {
               sl = l - buffer;
               riskDist = c - sl;
               tp = c + TpRMultiple * riskDist;
              }
            else
              {
               sl = h + buffer;
               riskDist = sl - c;
               tp = c - TpRMultiple * riskDist;
              }
            if(riskDist > 0)
              {
               ev.valid = true;
               ev.symbol = s.symbol;
               ev.direction = s.pendingDirection;
               ev.retestCloseTimeUtc = openTimeUtc;
               ev.rangeHigh = s.rangeHigh;
               ev.rangeLow = s.rangeLow;
               ev.slPrice = sl;
               ev.tpPrice = tp;
               ev.atrAtRetest = atrM5Value;
               ev.emaH1AtRetest = lastClosedH1Ema;
               s.state = BR_DONE_FOR_DAY;
              }
            s.pendingDirection = BR_DIR_NONE;
           }
        }
      else if(s.pendingBarsWaited >= RetestMaxBarsM5)
        {
         s.pendingDirection = BR_DIR_NONE;
         s.state = BR_WAITING_BREAKOUT;
        }
     }

   s.prevM5Close = c;
   return ev;
  }

#endif

#property strict
// OrderExec.mqh -- order send/close with bounded retry, requote/timeout/
// busy-context handling, and no duplicate-order risk on ambiguous OrderSend
// results. Mirrors ../../python/ftmo_sim/order_exec.py where the concepts
// overlap (execution-price SL validation, spread-once accounting); the
// retry/idempotency machinery here has no Python equivalent since the
// offline simulator never talks to a real broker connection.
// NOT_RUN: never compiled/tested.

#ifndef FTMO_ORDEREXEC_MQH
#define FTMO_ORDEREXEC_MQH

#include "Config.mqh"
#include "Logging.mqh"

#define MAX_ORDER_RETRIES 3
#define RETRY_SLEEP_MS    1500

// True if an order with this MagicNumber already exists on this symbol --
// used before resending after an ambiguous OrderSend result (timeout /
// unclear error) so a retry can never open a duplicate position.
bool HasOpenOrderForSymbol(string symbol)
  {
   for(int i = 0; i < OrdersTotal(); i++)
     {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderMagicNumber() == MagicNumber && OrderSymbol() == symbol
         && (OrderType() == OP_BUY || OrderType() == OP_SELL))
         return true;
     }
   return false;
  }

bool IsRetryableError(int err)
  {
   return err == ERR_REQUOTE || err == ERR_TRADE_TIMEOUT || err == ERR_BUSY ||
          err == ERR_TRADE_CONTEXT_BUSY || err == ERR_NO_CONNECTION ||
          err == ERR_SERVER_BUSY || err == ERR_TRADE_DISABLED;
  }

// Opens a market order with bounded retry. Re-validates the SL against the
// ACTUAL fill price after every attempt (spec section 4: "risku pārrēķina
// arī no faktiskās izpildes cenas") -- if the achieved price makes the
// intended SL invalid (already through it, or inside the broker's
// stops-level/freeze-level), the position is closed immediately and no
// further retry is attempted for that signal.
int OpenMarketOrderWithRetry(
   string symbol, int cmd, double lots, double sl, double tp, string comment)
  {
   if(HasOpenOrderForSymbol(symbol))
     {
      FtmoLog("EXEC", symbol + " already has an open order for this MagicNumber -- refusing duplicate entry");
      return -1;
     }

   for(int attempt = 1; attempt <= MAX_ORDER_RETRIES; attempt++)
     {
      RefreshRates();
      double price = (cmd == OP_BUY) ? MarketInfo(symbol, MODE_ASK) : MarketInfo(symbol, MODE_BID);
      int ticket = OrderSend(symbol, cmd, lots, price, 5, 0, 0, comment, MagicNumber, 0,
                              (cmd == OP_BUY) ? clrBlue : clrRed);
      if(ticket >= 0)
        {
         if(!OrderSelect(ticket, SELECT_BY_TICKET))
           {
            FtmoLog("EXEC", symbol + " OrderSend returned ticket but OrderSelect failed -- treating as UNKNOWN, do not retry blindly");
            return -1;
           }
         double actualPrice = OrderOpenPrice();
         double actualSlDist = (cmd == OP_BUY) ? (actualPrice - sl) : (sl - actualPrice);
         double stopsLevel = MarketInfo(symbol, MODE_STOPLEVEL) * MarketInfo(symbol, MODE_POINT);
         if(actualSlDist <= 0 || actualSlDist < stopsLevel)
           {
            FtmoLog("EXEC", symbol + " execution price invalidated SL (dist=" + DoubleToString(actualSlDist, 5) +
                    ") -- closing immediately and blocking further retries for this signal");
            CloseOrderWithRetry(ticket);
            return -1;
           }
         // FIXED 2026-09-18 (independent code audit): a failed OrderModify
         // here used to just log and return the ticket anyway, leaving the
         // position genuinely unprotected with nothing in the codebase that
         // actually retried it later despite the log message's claim. Now:
         // retry the SL/TP application a bounded number of times immediately,
         // and if it still hasn't succeeded, close the position rather than
         // hand back an unprotected one -- per spec section 4, a failed SL
         // must lead to a controlled retry OR closure, never silent exposure.
         bool protected_ = false;
         for(int protectAttempt = 1; protectAttempt <= MAX_ORDER_RETRIES; protectAttempt++)
           {
            if(OrderModify(ticket, actualPrice, sl, tp, 0, clrNONE)) { protected_ = true; break; }
            int modifyErr = GetLastError();
            FtmoLog("EXEC", symbol + " OrderModify(SL/TP) attempt " + IntegerToString(protectAttempt) +
                    " failed, errno=" + IntegerToString(modifyErr));
            if(!IsRetryableError(modifyErr)) break;
            Sleep(RETRY_SLEEP_MS);
           }
         if(!protected_)
           {
            FtmoLog("EXEC", symbol + " could not apply SL/TP after " + IntegerToString(MAX_ORDER_RETRIES) +
                    " attempts -- closing the position rather than leaving it unprotected");
            if(!CloseOrderWithRetry(ticket))
               FtmoLog("EXEC", symbol + " FAILED to close the unprotected ticket=" + IntegerToString(ticket) +
                       " -- risk controller's account-wide scan will still see its real (missing) SL and block new entries");
            return -1;
           }
         return ticket;
        }

      int err = GetLastError();
      FtmoLog("EXEC", symbol + " OrderSend failed attempt " + IntegerToString(attempt) + " errno=" + IntegerToString(err));
      if(!IsRetryableError(err)) return -1;
      if(HasOpenOrderForSymbol(symbol))
        {
         // The send may have actually succeeded server-side despite a
         // timeout/ambiguous client-side result -- never send a second one.
         FtmoLog("EXEC", symbol + " order appeared after an ambiguous result -- stopping retries, not duplicating");
         return -1;
        }
      Sleep(RETRY_SLEEP_MS * attempt);
     }
   return -1;
  }

bool CloseOrderWithRetry(int ticket)
  {
   for(int attempt = 1; attempt <= MAX_ORDER_RETRIES; attempt++)
     {
      if(!OrderSelect(ticket, SELECT_BY_TICKET)) return true; // already closed
      if(OrderCloseTime() != 0) return true;
      RefreshRates();
      double price = (OrderType() == OP_BUY) ? MarketInfo(OrderSymbol(), MODE_BID)
                                              : MarketInfo(OrderSymbol(), MODE_ASK);
      if(OrderClose(ticket, OrderLots(), price, 5, clrNONE)) return true;
      int err = GetLastError();
      FtmoLog("EXEC", "close ticket=" + IntegerToString(ticket) + " failed attempt " + IntegerToString(attempt) + " errno=" + IntegerToString(err));
      if(!IsRetryableError(err)) return false;
      Sleep(RETRY_SLEEP_MS * attempt);
     }
   return false;
  }

// Closes EVERY position and cancels EVERY pending order on the ACCOUNT --
// not filtered by MagicNumber -- used by the risk controller once a stop
// is persisted. Account-wide, not just-this-EA's-orders, on purpose: spec
// section 4 requires monitoring "the whole account, not just the EA's
// MagicNumber" and this design assumes a dedicated account; if a foreign
// (manual, or another EA's) position is what pushed equity into the stop,
// leaving it open while only closing this EA's own orders would defeat the
// entire point of the stop. CHANGED 2026-09-18 (independent code audit) --
// previously filtered by MagicNumber, which this reasoning does not
// support. Returns false if anything could not be closed/deleted so the
// caller can retry every tick (see FTMO_Swing_EA*.mq4's OnTick) rather than
// treating the stop as fully handled from a single attempt.
bool CloseAllPositionsAndPendingsAccountWide()
  {
   bool allDone = true;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderType() == OP_BUY || OrderType() == OP_SELL)
        {
         if(!CloseOrderWithRetry(OrderTicket()))
           {
            FtmoLog("RISK", "FAILED to close ticket=" + IntegerToString(OrderTicket()) + " -- will retry next tick");
            allDone = false;
           }
        }
      else
        {
         if(!OrderDelete(OrderTicket()))
           {
            FtmoLog("RISK", "FAILED to delete pending ticket=" + IntegerToString(OrderTicket()) + " -- will retry next tick");
            allDone = false;
           }
        }
     }
   return allDone;
  }

#endif

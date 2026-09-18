#property strict
// Persistence.mqh -- daily/total stop state, day rollover, restart
// recovery, and the single-controller instance guard, persisted to a file
// under MQL4/Files so it survives terminal/EA restarts (GlobalVariables
// alone do not survive a terminal reinstall/machine move, and are shared
// per-terminal rather than per-account, so a file keyed by account number
// is used instead).
// NOT_RUN: never compiled/tested. Mirrors ../../python/ftmo_sim/risk_state.py.
//
// FIXED 2026-09-18 (independent code audit): the previous version read the
// file back with `while(!FileIsEnding) raw += FileReadString(handle)` and
// then split the concatenated result on '\n' -- but FileReadString already
// strips the line terminator from each call's return value, so `raw` never
// contained a single '\n' and StringSplit always returned exactly one
// element. LoadRiskState therefore reported "corrupt state file" and
// returned false on EVERY read after the very first save, which (per
// FTMO_Swing_EA_EmaCross.mq4's OnInit) would have made the EA refuse to
// start on any restart. Also renamed away from the ".json" extension --
// this was never real JSON, only positional plain text, and naming it that
// was misleading. This has NOT been compiled or run (no MetaEditor/MT4
// available); the fix is a structural correction based on re-reading the
// FileReadString/FileWrite documentation, not a verified test run.

#ifndef FTMO_PERSISTENCE_MQH
#define FTMO_PERSISTENCE_MQH

#include "Config.mqh"
#include "AccountRisk.mqh"

#define FTMO_STATE_FIELD_SEP "|"     // between the 10 top-level fields
#define FTMO_STATE_LIST_SEP  ";"     // inside entriesUsedToday's symbol list

struct RiskState
  {
   long   accountNumber;
   string serverName;
   string configVersion;
   string currentFtmoDay;      // "YYYY.MM.DD" (Prague)
   double balanceAtMidnight;
   bool   dailyStopActive;
   bool   totalStopActive;
   string totalStopReason;
   bool   historyReconciled;
   string entriesUsedToday;    // FTMO_STATE_LIST_SEP-joined symbols, cleared on rollover
  };

string StateFilePath()
  {
   // Not JSON -- a single '|'-delimited line. ".state" avoids implying a
   // format this file never actually used.
   return "FTMO_RiskState_" + IntegerToString(AccountNumber()) + ".state";
  }

void InitFreshRiskState(RiskState &state)
  {
   state.accountNumber      = AccountNumber();
   state.serverName         = AccountServer();
   state.configVersion      = ConfigVersion;
   state.currentFtmoDay     = "";
   state.balanceAtMidnight  = 0.0;
   state.dailyStopActive    = false;
   state.totalStopActive    = false;
   state.totalStopReason    = "";
   state.historyReconciled  = false; // must be explicitly set true after a verified reconstruction
   state.entriesUsedToday   = "";
  }

bool LoadRiskState(RiskState &state)
  {
   int handle = FileOpen(StateFilePath(), FILE_READ | FILE_TXT);
   if(handle == INVALID_HANDLE)
     {
      InitFreshRiskState(state);
      return true; // fresh state, not an error
     }
   // The whole persisted state is ONE line -- a single FileReadString call
   // reads exactly that line (up to the line break) regardless of any
   // comma/delimiter ambiguity between MQL4 file modes, which is precisely
   // why a multi-line, multi-call read (the previous, broken version) is
   // avoided here.
   string line = FileReadString(handle);
   FileClose(handle);

   string parts[];
   int n = StringSplit(line, StringGetCharacter(FTMO_STATE_FIELD_SEP, 0), parts);
   if(n < 9)
     {
      Print("FTMO: corrupt or empty state file (", n, " fields), refusing to trust it");
      return false;
     }
   state.accountNumber     = StrToInteger(parts[0]);
   state.serverName        = parts[1];
   state.configVersion     = parts[2];
   state.currentFtmoDay    = parts[3];
   state.balanceAtMidnight = StrToDouble(parts[4]);
   state.dailyStopActive   = (parts[5] == "1");
   state.totalStopActive   = (parts[6] == "1");
   state.totalStopReason   = parts[7];
   state.historyReconciled = (parts[8] == "1");
   state.entriesUsedToday  = (n > 9) ? parts[9] : "";

   if(state.accountNumber != AccountNumber() || state.serverName != AccountServer())
     {
      Print("FTMO: FATAL -- persisted state bound to account=", state.accountNumber,
            " server=", state.serverName, "; refusing to bind account=", AccountNumber(),
            " server=", AccountServer(), " (second controller instance?)");
      return false;
     }
   return true;
  }

bool SaveRiskState(const RiskState &state)
  {
   // NOTE: not an atomic write (no temp-file-then-rename here) -- a crash
   // mid-write could leave a truncated/corrupt line, which LoadRiskState
   // detects (n<9) and refuses rather than silently trusting. Accepted,
   // documented limitation; a fully atomic write needs verifying MQL4's
   // FileMove semantics against a real terminal, which this environment
   // cannot do.
   int handle = FileOpen(StateFilePath(), FILE_WRITE | FILE_TXT);
   if(handle == INVALID_HANDLE) { Print("FTMO: cannot write state file, errno=", GetLastError()); return false; }
   string line = IntegerToString(state.accountNumber) + FTMO_STATE_FIELD_SEP +
                 state.serverName + FTMO_STATE_FIELD_SEP +
                 state.configVersion + FTMO_STATE_FIELD_SEP +
                 state.currentFtmoDay + FTMO_STATE_FIELD_SEP +
                 DoubleToString(state.balanceAtMidnight, 2) + FTMO_STATE_FIELD_SEP +
                 (state.dailyStopActive ? "1" : "0") + FTMO_STATE_FIELD_SEP +
                 (state.totalStopActive ? "1" : "0") + FTMO_STATE_FIELD_SEP +
                 state.totalStopReason + FTMO_STATE_FIELD_SEP +
                 (state.historyReconciled ? "1" : "0") + FTMO_STATE_FIELD_SEP +
                 state.entriesUsedToday;
   FileWrite(handle, line);
   FileClose(handle);
   return true;
  }

// Call once per tick with today's FTMO day key. On first observation of a
// new day, snapshot balance and clear the daily stop only -- never the
// total stop.
bool RolloverIfNeeded(RiskState &state, string ftmoDayToday, double balanceNow)
  {
   if(state.currentFtmoDay == ftmoDayToday) return false;
   state.currentFtmoDay    = ftmoDayToday;
   state.balanceAtMidnight = balanceNow;
   state.dailyStopActive   = false;
   state.entriesUsedToday  = "";
   return true;
  }

// Independent dual-threshold check -- see account_risk.py / risk_state.py
// for why the static total floor must be checked directly rather than only
// via max(daily, total).
void EvaluateRiskState(RiskState &state, double equity)
  {
   double dailyFloor = RobotDailyWorkingFloor(state.balanceAtMidnight);
   if(IsFloorBreached(equity, dailyFloor)) state.dailyStopActive = true;
   if(IsFloorBreached(equity, RobotTotalFloorUSD))
     {
      state.totalStopActive = true;
      if(state.totalStopReason == "")
         state.totalStopReason = StringFormat("equity %.2f <= total floor %.2f on %s",
                                               equity, RobotTotalFloorUSD, state.currentFtmoDay);
     }
  }

bool StopActive(const RiskState &state)
  {
   return state.dailyStopActive || state.totalStopActive;
  }

bool SymbolUsedToday(const RiskState &state, string symbol)
  {
   return (StringFind(state.entriesUsedToday, symbol) >= 0);
  }

void RegisterEntry(RiskState &state, string symbol)
  {
   if(!SymbolUsedToday(state, symbol))
      state.entriesUsedToday = state.entriesUsedToday + symbol + FTMO_STATE_LIST_SEP;
  }

bool CanOpenNewEntry(const RiskState &state, string symbol)
  {
   if(!state.historyReconciled) return false;
   if(StopActive(state)) return false;
   return !SymbolUsedToday(state, symbol);
  }

#endif

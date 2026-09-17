#property strict
// Persistence.mqh -- daily/total stop state, day rollover, restart
// recovery, and the single-controller instance guard, persisted to a file
// under MQL4/Files so it survives terminal/EA restarts (GlobalVariables
// alone do not survive a terminal reinstall/machine move, and are shared
// per-terminal rather than per-account, so a file keyed by account number
// is used instead).
// NOT_RUN: never compiled/tested. Mirrors ../../python/ftmo_sim/risk_state.py.

#ifndef FTMO_PERSISTENCE_MQH
#define FTMO_PERSISTENCE_MQH

#include "Config.mqh"
#include "AccountRisk.mqh"

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
   string entriesUsedToday;    // comma-separated symbols, cleared on rollover
  };

string StateFilePath()
  {
   return "FTMO_RiskState_" + IntegerToString(AccountNumber()) + ".json";
  }

bool LoadRiskState(RiskState &state)
  {
   int handle = FileOpen(StateFilePath(), FILE_READ | FILE_TXT);
   if(handle == INVALID_HANDLE)
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
      return true; // fresh state, not an error
     }
   string raw = "";
   while(!FileIsEnding(handle)) raw += FileReadString(handle);
   FileClose(handle);
   // Minimal hand-rolled parse (no JSON library in stock MQL4): fields are
   // written one per line by SaveRiskState() in a fixed order.
   string lines[];
   int n = StringSplit(raw, '\n', lines);
   if(n < 9) { Print("FTMO: corrupt state file, refusing to trust it"); return false; }
   state.accountNumber     = StrToInteger(lines[0]);
   state.serverName        = lines[1];
   state.configVersion     = lines[2];
   state.currentFtmoDay    = lines[3];
   state.balanceAtMidnight = StrToDouble(lines[4]);
   state.dailyStopActive   = (lines[5] == "1");
   state.totalStopActive   = (lines[6] == "1");
   state.totalStopReason   = lines[7];
   state.historyReconciled = (lines[8] == "1");
   state.entriesUsedToday  = (n > 9) ? lines[9] : "";

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
   int handle = FileOpen(StateFilePath(), FILE_WRITE | FILE_TXT);
   if(handle == INVALID_HANDLE) { Print("FTMO: cannot write state file, errno=", GetLastError()); return false; }
   FileWrite(handle, state.accountNumber);
   FileWrite(handle, state.serverName);
   FileWrite(handle, state.configVersion);
   FileWrite(handle, state.currentFtmoDay);
   FileWrite(handle, DoubleToString(state.balanceAtMidnight, 2));
   FileWrite(handle, state.dailyStopActive ? "1" : "0");
   FileWrite(handle, state.totalStopActive ? "1" : "0");
   FileWrite(handle, state.totalStopReason);
   FileWrite(handle, state.historyReconciled ? "1" : "0");
   FileWrite(handle, state.entriesUsedToday);
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
      state.entriesUsedToday = state.entriesUsedToday + symbol + ",";
  }

bool CanOpenNewEntry(const RiskState &state, string symbol)
  {
   if(!state.historyReconciled) return false;
   if(StopActive(state)) return false;
   return !SymbolUsedToday(state, symbol);
  }

#endif

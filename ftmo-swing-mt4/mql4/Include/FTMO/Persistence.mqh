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
   // ADDED 2026-09-18 (follow-up audit, section 4.4): if a position is sent
   // but neither SL/TP application NOR an immediate close succeeds, the
   // position sits on the broker unprotected. The old behaviour only logged
   // a warning and relied on the generic account-wide "unknown risk" scan
   // to block NEW entries -- it never kept retrying to actually fix THIS
   // position, and would lose track of it entirely across a restart (the
   // ticket number was never persisted). These three fields turn that into
   // an explicit, persisted emergency state: ticket=0 means "nothing
   // unprotected"; a non-zero ticket is retried every tick (see
   // OrderExec.mqh::ReconcileUnprotectedPosition) using the ORIGINALLY
   // INTENDED sl/tp (also persisted, since a restart cannot recover intent
   // that was only ever held in a local variable) until the real broker-side
   // order is confirmed protected or confirmed closed -- independent of
   // whether any daily/total floor has been breached.
   long   unprotectedTicket;
   double unprotectedIntendedSl;
   double unprotectedIntendedTp;
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
   state.unprotectedTicket    = 0;
   state.unprotectedIntendedSl = 0.0;
   state.unprotectedIntendedTp = 0.0;
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
   // Fields 10-12 are newer (2026-09-18 follow-up audit) -- default to "no
   // unprotected position" when reading a state file saved before this fix
   // existed, so an upgrade never fails to load, it just starts clean.
   state.unprotectedTicket     = (n > 10) ? StrToInteger(parts[10]) : 0;
   state.unprotectedIntendedSl = (n > 11) ? StrToDouble(parts[11]) : 0.0;
   state.unprotectedIntendedTp = (n > 12) ? StrToDouble(parts[12]) : 0.0;

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
                 state.entriesUsedToday + FTMO_STATE_FIELD_SEP +
                 IntegerToString(state.unprotectedTicket) + FTMO_STATE_FIELD_SEP +
                 DoubleToString(state.unprotectedIntendedSl, 8) + FTMO_STATE_FIELD_SEP +
                 DoubleToString(state.unprotectedIntendedTp, 8);
   FileWrite(handle, line);
   FileClose(handle);
   return true;
  }

// Records that `ticket` could not be protected/closed at open time so the
// per-tick reconciliation loop retries it from here on, including after a
// restart (the ticket number and originally intended sl/tp are what gets
// persisted -- a restart cannot recover intent held only in a local
// variable). Call SaveRiskState immediately after this so a crash right
// after cannot lose the record.
void MarkUnprotected(RiskState &state, long ticket, double intendedSl, double intendedTp)
  {
   state.unprotectedTicket     = ticket;
   state.unprotectedIntendedSl = intendedSl;
   state.unprotectedIntendedTp = intendedTp;
  }

void ClearUnprotected(RiskState &state)
  {
   state.unprotectedTicket     = 0;
   state.unprotectedIntendedSl = 0.0;
   state.unprotectedIntendedTp = 0.0;
  }

bool HasUnprotectedPosition(const RiskState &state)
  {
   return state.unprotectedTicket != 0;
  }

// ADDED 2026-09-18 (follow-up audit, section 4.6): the account/server
// identity comparison in LoadRiskState is a DATA-INTEGRITY check ("is this
// state file even the right one for this account"), not an exclusive
// instance lock -- it does nothing to stop two EA instances from both
// passing that check and then racing to read-modify-write the same state
// file on the same tick. This lock file is a genuine (if still limited)
// mechanism: FileOpen with NEITHER FILE_SHARE_READ NOR FILE_SHARE_WRITE
// requests exclusive access, so a second OnInit's FileOpen call on the same
// path fails for as long as the first EA keeps its handle open (held for
// the EA's entire lifetime, released only in OnDeinit).
//
// Documented limitation (still real -- read before relying on this):
// exclusivity is enforced by the terminal PROCESS holding the handle, so it
// blocks a second EA instance within the SAME terminal / same MQL4/Files
// directory (e.g. two charts, or this EA + the other strategy's EA,
// attached to the same account in the same terminal). It does NOT block a
// second MT4 TERMINAL INSTALLATION (a different data folder, e.g. after
// copying the whole terminal to another machine or a second portable
// install) from independently acquiring its OWN lock in ITS OWN
// MQL4/Files directory and trading the same broker account unopposed --
// that would require a server-side or broker-side control this prototype
// has no access to, and remains an open item; see docs/UNKNOWNS.md.
int g_ftmoLockHandle = INVALID_HANDLE;

string LockFilePath()
  {
   return "FTMO_InstanceLock_" + IntegerToString(AccountNumber()) + ".lock";
  }

bool AcquireInstanceLock()
  {
   g_ftmoLockHandle = FileOpen(LockFilePath(), FILE_WRITE | FILE_BIN); // no FILE_SHARE_* -> exclusive
   if(g_ftmoLockHandle == INVALID_HANDLE)
     {
      Print("FTMO: FATAL -- could not acquire instance lock '", LockFilePath(),
            "' (errno=", GetLastError(), ") -- another EA instance from this project may already be ",
            "running against this account in this terminal; refusing to init rather than race it");
      return false;
     }
   FileWriteInteger(g_ftmoLockHandle, (int)TimeLocal()); // arbitrary content -- only holding the handle matters
   FileFlush(g_ftmoLockHandle);
   return true;
  }

void ReleaseInstanceLock()
  {
   if(g_ftmoLockHandle != INVALID_HANDLE)
     {
      FileClose(g_ftmoLockHandle);
      g_ftmoLockHandle = INVALID_HANDLE;
     }
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
   if(HasUnprotectedPosition(state)) return false; // section 4.4: an unresolved unprotected position blocks all new entries, not just the account-wide unknown-risk scan
   return !SymbolUsedToday(state, symbol);
  }

#endif

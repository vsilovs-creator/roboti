#property strict
// Logging.mqh -- append-only per-account log file plus terminal Print().
// NOT_RUN: never compiled/tested.

#ifndef FTMO_LOGGING_MQH
#define FTMO_LOGGING_MQH

string LogFilePath()
  {
   return "FTMO_Log_" + IntegerToString(AccountNumber()) + ".csv";
  }

void FtmoLog(string category, string message)
  {
   string line = TimeToString(TimeGMT(), TIME_DATE | TIME_SECONDS) + "," + category + "," + message;
   Print("FTMO[", category, "] ", message);
   int handle = FileOpen(LogFilePath(), FILE_READ | FILE_WRITE | FILE_TXT);
   if(handle == INVALID_HANDLE) return;
   FileSeek(handle, 0, SEEK_END);
   FileWrite(handle, line);
   FileClose(handle);
  }

#endif

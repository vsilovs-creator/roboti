#property strict
// TimeUtils.mqh -- FTMO day boundary (Europe/Prague) and London session
// windows, built on TimeGMT() plus an explicit, swappable server-clock
// model, since MQL4 has no IANA timezone database.
// NOT_RUN: never compiled/tested. Mirrors ../../python/ftmo_sim/time_utils.py.
//
// IMPORTANT: ServerUTCOffsetHours / ServerObservesEUDST (Config.mqh) are
// UNVERIFIED. Every function here is only as correct as that input.

#ifndef FTMO_TIMEUTILS_MQH
#define FTMO_TIMEUTILS_MQH

#include "Config.mqh"

// EU DST: last Sunday of March 01:00 UTC -> last Sunday of October 01:00 UTC.
bool IsEUDstActive(datetime utcTime)
  {
   int y = TimeYear(utcTime);
   datetime marchLastSunday = D'2000.01.01'; // placeholder, computed below
   int d;
   // find last Sunday of March
   for(d = 31; d >= 25; d--)
     {
      datetime cand = StringToTime(StringFormat("%d.03.%02d 01:00", y, d));
      if(TimeDayOfWeek(cand) == 0) { marchLastSunday = cand; break; }
     }
   datetime octLastSunday = D'2000.01.01';
   for(d = 31; d >= 25; d--)
     {
      datetime cand = StringToTime(StringFormat("%d.10.%02d 01:00", y, d));
      if(TimeDayOfWeek(cand) == 0) { octLastSunday = cand; break; }
     }
   return (utcTime >= marchLastSunday && utcTime < octLastSunday);
  }

datetime ServerTimeToUTC(datetime serverTime)
  {
   double offset = ServerUTCOffsetHours;
   if(ServerObservesEUDST)
     {
      // Approximate: apply DST test using the offset-adjusted instant.
      datetime approxUtc = serverTime - (datetime)(offset * 3600);
      if(IsEUDstActive(approxUtc)) offset += 1.0;
     }
   return serverTime - (datetime)(offset * 3600);
  }

// Europe/Prague is UTC+1 (CET) / UTC+2 (CEST), same EU DST rule as above.
datetime UtcToPrague(datetime utcTime)
  {
   double offset = 1.0;
   if(IsEUDstActive(utcTime)) offset = 2.0;
   return utcTime + (datetime)(offset * 3600);
  }

// Europe/London is UTC+0 (GMT) / UTC+1 (BST), same EU DST rule (post-1996).
datetime UtcToLondon(datetime utcTime)
  {
   double offset = 0.0;
   if(IsEUDstActive(utcTime)) offset = 1.0;
   return utcTime + (datetime)(offset * 3600);
  }

// Calendar date string (Prague) this UTC instant belongs to -- used as the
// FTMO trading-day key.
string FtmoTradingDayKey(datetime utcTime)
  {
   datetime pragueTime = UtcToPrague(utcTime);
   return TimeToString(pragueTime, TIME_DATE);
  }

int LondonHour(datetime utcTime)   { return TimeHour(UtcToLondon(utcTime)); }
int LondonMinute(datetime utcTime) { return TimeMin(UtcToLondon(utcTime)); }

bool InLondonHourWindow(datetime utcTime, int startHour, int endHour)
  {
   int h = LondonHour(utcTime);
   return (h >= startHour && h < endHour);
  }

#endif

#property strict
// Config.mqh -- EA inputs and the config struct built from them.
// NOT_RUN: never compiled/tested against MetaEditor/MT4 in this environment.
// Mirrors ../../python/ftmo_sim/config.py + account_risk.FtmoLimitsConfig.

#ifndef FTMO_CONFIG_MQH
#define FTMO_CONFIG_MQH

input string  Sym1_Name                = "EURUSD";
input string  Sym2_Name                = "GBPUSD";
input string  BrokerSuffix             = "";        // e.g. ".m", "-ECN" -- confirm per broker

input double  InitialBalanceUSD        = 10000.0;

input double  FtmoDailyFloorOffsetUSD  = 500.0;
input double  FtmoTotalFloorUSD        = 9000.0;
input double  RobotDailyBufferUSD      = 300.0;
input double  RobotTotalFloorUSD       = 9200.0;

input double  RiskPerIdeaUSD           = 25.0;
input double  MaxConcurrentRiskUSD     = 100.0;
input double  CorrelatedGroupMaxRiskUSD= 50.0;
input double  ExecutionBufferUSD       = 5.0;

// CONFIRMED 2026-09-18 (account owner): GMT+2 winter / GMT+3 summer (DST),
// same transition dates as the EU. Re-verify against the live terminal
// (TimeCurrent() vs TimeGMT()) before trusting this on a real account --
// see docs/UNKNOWNS.md item 1.
input double  ServerUTCOffsetHours     = 2.0;   // broker server time minus UTC in winter/standard time
input bool    ServerObservesEUDST      = true;  // true: add +1h on top of the above during EU DST (last Sun Mar - last Sun Oct)

// CONFIRMED 2026-09-18 (account owner): 5 USD per lot. Taken as ROUND-TURN
// (not per side) -- double-check against the broker's actual fee schedule.
input double  CommissionPerLotRoundTurnUSD = 5.0; // -1 would mean "unconfirmed"
input double  SpreadPointsHypothetical_S1  = 10;
input double  SpreadPointsHypothetical_S2  = 15;

input int     RangeStartHourLondon     = 0;
input int     RangeEndHourLondon       = 7;
input int     EntryStartHourLondon     = 8;
input int     EntryEndHourLondon       = 11;
input int     SessionCloseHourLondon   = 16;
input int     RetestMaxBarsM5          = 6;
input double  SlAtrBufferMultiple      = 0.10;
input int     AtrPeriodM5              = 14;
input int     EmaPeriodH1              = 200;
input double  TpRMultiple              = 2.0;

input string  ConfigVersion            = "0.1.0-exploratory";
input int     MagicNumber              = 20260917;

string Sym1() { return Sym1_Name + BrokerSuffix; }
string Sym2() { return Sym2_Name + BrokerSuffix; }

bool CommissionIsConfirmed() { return CommissionPerLotRoundTurnUSD >= 0.0; }

#endif

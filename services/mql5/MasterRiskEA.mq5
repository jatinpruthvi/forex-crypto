//+------------------------------------------------------------------+
//|                                                MasterRiskEA.mq5  |
//|                               AMATS Master Risk & Kill Switch EA |
//+------------------------------------------------------------------+
#property copyright "AMATS Trading System"
#property link      "https://github.com/jatinpruthvi/forex-crypto"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
#include "Include\RiskManager.mqh"

input double InpMaxDailyLossPct   = 2.0;    // Max Daily Loss % (Prop challenge guard)
input double InpMaxTotalExposure  = 5.0;    // Max Open Exposure %
input double InpMaxTotalDrawdown  = 8.0;    // Emergency Kill Switch DD %
input int    InpTimerIntervalSec  = 10;     // Assessment Interval (Seconds)
input bool   InpEnforceWeekendClose = true; // Auto-close all positions on Friday before market close
input int    InpFridayCloseHourGMT  = 20;   // Friday liquidation hour (GMT)
input int    InpFridayCloseMinGMT   = 30;   // Friday liquidation minute (GMT)
input bool   InpFilterAsianSession  = true; // Block entries during illiquid Asian hours (00:00-06:00 GMT)

double initialDayBalance = 0.0;
datetime lastResetDay = 0;

int OnInit()
{
   datetime currentDay = TimeCurrent() / 86400;
   if(GlobalVariableCheck("LAST_RESET_DAY") && (datetime)GlobalVariableGet("LAST_RESET_DAY") == currentDay && GlobalVariableCheck("DAY_BASELINE_BALANCE"))
   {
      initialDayBalance = GlobalVariableGet("DAY_BASELINE_BALANCE");
      lastResetDay = currentDay;
   }
   else
   {
      initialDayBalance = AccountInfoDouble(ACCOUNT_BALANCE);
      lastResetDay = currentDay;
      GlobalVariableSet("DAY_BASELINE_BALANCE", initialDayBalance);
      GlobalVariableSet("LAST_RESET_DAY", (double)currentDay);
   }

   // Initialize GlobalVariables for Slave EAs
   GlobalVariableSet("MAX_DAILY_LOSS", InpMaxDailyLossPct);
   GlobalVariableSet("MAX_TOTAL_EXPOSURE", InpMaxTotalExposure);
   GlobalVariableSet("CURRENT_DAILY_PNL", 0.0);
   GlobalVariableSet("ALLOW_NEW_TRADES", 1.0);
   GlobalVariableSet("SIZE_MULT", 1.0);

   EventSetTimer(InpTimerIntervalSec);
   Print("MasterRiskEA initialized. Daily Loss Guard: ", InpMaxDailyLossPct, "%");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void OnTimer()
{
   datetime currentDay = TimeCurrent() / 86400;
   if(currentDay > lastResetDay)
   {
      // Reset at midnight server time
      initialDayBalance = AccountInfoDouble(ACCOUNT_BALANCE);
      lastResetDay = currentDay;
      GlobalVariableSet("DAY_BASELINE_BALANCE", initialDayBalance);
      GlobalVariableSet("LAST_RESET_DAY", (double)currentDay);
      GlobalVariableSet("ALLOW_NEW_TRADES", 1.0);
      GlobalVariableSet("CURRENT_DAILY_PNL", 0.0);
      GlobalVariableSet("SIZE_MULT", 1.0);
      Print("MasterRiskEA: Day counters reset. New Day Baseline Balance: ", initialDayBalance);
   }

   double currentEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   double dailyLossAmount = initialDayBalance - currentEquity;
   double dailyLossPct = (dailyLossAmount / initialDayBalance) * 100.0;

   GlobalVariableSet("CURRENT_DAILY_PNL", -dailyLossPct);

   // True TOTAL drawdown from peak equity (the kill switch used to measure the
   // DAY baseline only, so a slow multi-day bleed could never trip it).
   double peakEquity = GlobalVariableCheck("PEAK_EQUITY") ? GlobalVariableGet("PEAK_EQUITY") : currentEquity;
   if(currentEquity > peakEquity)
   {
      peakEquity = currentEquity;
   }
   GlobalVariableSet("PEAK_EQUITY", peakEquity);
   double totalDDPct = peakEquity > 0.0 ? ((peakEquity - currentEquity) / peakEquity) * 100.0 : 0.0;

   // 1. Hard Kill Switch: TOTAL Drawdown breached (>8% from peak)
   if(totalDDPct >= InpMaxTotalDrawdown)
   {
      Print("KILL-SWITCH ACTIVE: Total Drawdown breached ", totalDDPct, "%. Liquidating all!");
      GlobalVariableSet("ALLOW_NEW_TRADES", 0.0);
      CRiskManager::CloseAllPositions(777123); // Closes all AMATS slave EA positions
      return;
   }

   // 2. Daily Loss Limit Enforcer
   if(dailyLossPct >= InpMaxDailyLossPct)
   {
      Print("DAILY LOSS BREACHED: ", dailyLossPct, "%. Halting new entries.");
      GlobalVariableSet("ALLOW_NEW_TRADES", 0.0);
      return;
   }

   // 3. Escalation sizing tiers (size only — never toggles the entry gate)
   if(dailyLossPct >= InpMaxDailyLossPct * 0.75)
   {
      GlobalVariableSet("SIZE_MULT", 0.25);
   }
   else if(dailyLossPct >= InpMaxDailyLossPct * 0.50)
   {
      GlobalVariableSet("SIZE_MULT", 0.50);
   }
   else
   {
      GlobalVariableSet("SIZE_MULT", 1.0);
   }

   // 4. Weekend Liquidity & Spread Blowout Guard (Friday 20:30 GMT)
   MqlDateTime dt;
   TimeGMT(dt);

   if(InpEnforceWeekendClose && dt.day_of_week == 5) // Friday
   {
      if(dt.hour > InpFridayCloseHourGMT || (dt.hour == InpFridayCloseHourGMT && dt.min >= InpFridayCloseMinGMT))
      {
         Print("WEEKEND GUARD ACTIVE: Friday market close imminent. Halting trades and closing positions.");
         GlobalVariableSet("ALLOW_NEW_TRADES", 0.0);
         CRiskManager::CloseAllPositions(777123); // Closes all AMATS slave EA positions
         return;
      }
   }

   // 5. Illiquid Asian Session Filter (00:00 - 06:00 GMT)
   // Entry gate state is computed ONCE here. (The old code set ALLOW=0 in the
   // session filter, then the sizing `else` branch force-set ALLOW=1 on the
   // next 10s tick — the Asian filter never actually stuck.)
   bool sessionBlocked = false;
   if(InpFilterAsianSession && dt.hour >= 0 && dt.hour < 6)
   {
      sessionBlocked = true;
   }
   GlobalVariableSet("ALLOW_NEW_TRADES", sessionBlocked ? 0.0 : 1.0);
}

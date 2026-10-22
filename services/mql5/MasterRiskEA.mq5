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
   initialDayBalance = AccountInfoDouble(ACCOUNT_BALANCE);
   lastResetDay = TimeCurrent() / 86400;

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
      GlobalVariableSet("ALLOW_NEW_TRADES", 1.0);
      GlobalVariableSet("CURRENT_DAILY_PNL", 0.0);
      GlobalVariableSet("SIZE_MULT", 1.0);
      Print("MasterRiskEA: Day counters reset. New Day Baseline Balance: ", initialDayBalance);
   }

   double currentEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   double dailyLossAmount = initialDayBalance - currentEquity;
   double dailyLossPct = (dailyLossAmount / initialDayBalance) * 100.0;

   GlobalVariableSet("CURRENT_DAILY_PNL", -dailyLossPct);

   // 1. Hard Kill Switch: Max Drawdown breached (>8%)
   if(dailyLossPct >= InpMaxTotalDrawdown)
   {
      Print("KILL-SWITCH ACTIVE: Total Drawdown breached ", dailyLossPct, "%. Liquidating all!");
      GlobalVariableSet("ALLOW_NEW_TRADES", 0.0);
      CRiskManager::CloseAllPositions(0);
      return;
   }

   // 2. Daily Loss Limit Enforcer
   if(dailyLossPct >= InpMaxDailyLossPct)
   {
      Print("DAILY LOSS BREACHED: ", dailyLossPct, "%. Halting new entries.");
      GlobalVariableSet("ALLOW_NEW_TRADES", 0.0);
      return;
   }

   // 3. Escalation sizing tiers
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
      GlobalVariableSet("ALLOW_NEW_TRADES", 1.0);
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
         CRiskManager::CloseAllPositions(0);
         return;
      }
   }

   // 5. Illiquid Asian Session Filter (00:00 - 06:00 GMT)
   if(InpFilterAsianSession)
   {
      if(dt.hour >= 0 && dt.hour < 6)
      {
         GlobalVariableSet("ALLOW_NEW_TRADES", 0.0);
      }
   }
}

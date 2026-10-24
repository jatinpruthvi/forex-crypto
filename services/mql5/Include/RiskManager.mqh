//+------------------------------------------------------------------+
//|                                                  RiskManager.mqh |
//|                                     AMATS Shared Risk Guard      |
//+------------------------------------------------------------------+
#property copyright "AMATS Trading System"
#property strict

#include <Trade\Trade.mqh>

class CRiskManager
{
public:
   CRiskManager() {}
   ~CRiskManager() {}

   static bool CanOpenTrade(double riskPercent)
   {
      if(GlobalVariableCheck("ALLOW_NEW_TRADES"))
      {
         if(GlobalVariableGet("ALLOW_NEW_TRADES") < 1.0)
            return false;
      }
      return true;
   }

   static void CloseAllPositions(int magicNumber = 0)
   {
      CTrade trade;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);
         if(ticket > 0)
         {
            if(magicNumber == 0 || PositionGetInteger(POSITION_MAGIC) == magicNumber)
            {
               trade.PositionClose(ticket);
            }
         }
      }
   }

   static double GetTotalOpenRiskPercent()
   {
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      if(equity <= 0) return 0.0;
      double totalRiskUSD = 0.0;

      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);
         if(ticket > 0)
         {
            double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
            double sl = PositionGetDouble(POSITION_SL);
            double volume = PositionGetDouble(POSITION_VOLUME);
            string sym = PositionGetString(POSITION_SYMBOL);

            if(sl > 0)
            {
               double lossDistance = MathAbs(openPrice - sl);
               // Simple approximation in account currency
               totalRiskUSD += lossDistance * volume * 100000;
            }
         }
      }
      return (totalRiskUSD / equity) * 100.0;
   }
};

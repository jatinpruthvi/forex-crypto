//+------------------------------------------------------------------+
//|                                               PythonBrainEA.mq5  |
//|                              AMATS Slave EA (Calls FastAPI Brain)|
//+------------------------------------------------------------------+
#property copyright "AMATS Trading System"
#property link      "https://github.com/jatinpruthvi/forex-crypto"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
#include "Include\BrainClient.mqh"
#include "Include\RiskManager.mqh"

input string InpBrainApiUrl      = "http://127.0.0.1:8000"; // Python FastAPI URL
input int    InpRequestTimeout   = 5000;                     // Request Timeout (ms)
input double InpRiskPercent      = 0.5;                      // Risk % per trade
input int    InpMagicNumber      = 777123;                   // Magic Number
input int    InpMaxOpenTrades    = 3;                        // Max open positions
input int    InpCandleBars       = 100;                      // Bars to send to Brain
input int    InpMaxSpreadPoints  = 25;                       // Max allowed spread (points) to avoid rollover slippage
input bool   InpUseLimitOrders   = true;                     // Use post-only limit orders instead of market execution

CBrainClient brainClient;
CTrade       trade;
datetime     lastCandleTime = 0;
uint         lastSuccessfulPing = 0;

int OnInit()
{
   brainClient.SetConfig(InpBrainApiUrl, InpRequestTimeout);
   trade.SetExpertMagicNumber(InpMagicNumber);

   if(!brainClient.CheckHealth())
   {
      Print("Warning: Brain API unreachable at ", InpBrainApiUrl, ". EA will retry on new bar.");
   }
   else
   {
      Print("Connected successfully to AMATS Brain API.");
      lastSuccessfulPing = GetTickCount();
   }

   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
}

// Robust JSON string and number parsers handling whitespace around keys and colons
string ExtractJsonString(string json, string key)
{
   int keyPos = StringFind(json, "\"" + key + "\"");
   if(keyPos < 0) return "";
   int colonPos = StringFind(json, ":", keyPos);
   if(colonPos < 0) return "";
   int startPos = StringFind(json, "\"", colonPos);
   if(startPos < 0) return "";
   int endPos = StringFind(json, "\"", startPos + 1);
   if(endPos < 0) return "";
   return StringSubstr(json, startPos + 1, endPos - startPos - 1);
}

double ExtractJsonDouble(string json, string key)
{
   int keyPos = StringFind(json, "\"" + key + "\"");
   if(keyPos < 0) return 0.0;
   int colonPos = StringFind(json, ":", keyPos);
   if(colonPos < 0) return 0.0;
   int commaPos = StringFind(json, ",", colonPos);
   int bracePos = StringFind(json, "}", colonPos);
   int endPos = commaPos;
   if(commaPos < 0 || (bracePos > 0 && bracePos < commaPos)) endPos = bracePos;
   if(endPos < 0) endPos = StringLen(json);
   string valStr = StringSubstr(json, colonPos + 1, endPos - colonPos - 1);
   StringTrimLeft(valStr);
   StringTrimRight(valStr);
   // Remove quotes if parsed as string representation
   StringReplace(valStr, "\"", "");
   return StringToDouble(valStr);
}

void OnTick()
{
   // 1. Only execute once per new bar
   datetime currentBarTime = iTime(_Symbol, _Period, 0);
   if(currentBarTime == lastCandleTime) return;
   lastCandleTime = currentBarTime;

   // 2. Risk check: Master EA allows new trades?
   if(!CRiskManager::CanOpenTrade(InpRiskPercent))
   {
      Print("MasterRiskEA has blocked new trades.");
      return;
   }

   // 3. Fallback kill-switch: Brain unreachable > 10 min
   if(lastSuccessfulPing > 0 && (GetTickCount() - lastSuccessfulPing > 600000))
   {
      Print("KILL-SWITCH TRIGGERED: Python Brain unreachable > 10 min. Closing positions!");
      CRiskManager::CloseAllPositions(InpMagicNumber);
      return;
   }

   // 4. Build OHLCV JSON payload
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(_Symbol, _Period, 1, InpCandleBars, rates);
   if(copied < 30) return;

   string ohlcvJson = "[";
   for(int i = copied - 1; i >= 0; i--)
   {
      ohlcvJson += StringFormat("[%I64d,%.5f,%.5f,%.5f,%.5f,%I64d]",
         rates[i].time, rates[i].open, rates[i].high, rates[i].low, rates[i].close, rates[i].tick_volume
      );
      if(i > 0) ohlcvJson += ",";
   }
   ohlcvJson += "]";

   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);

   string payload = StringFormat(
      "{\"symbol\":\"%s\",\"timeframe\":\"%s\",\"ohlcv\":%s,\"account_equity\":%.2f,\"account_balance\":%.2f,\"open_positions\":[]}",
      _Symbol, EnumToString(_Period), ohlcvJson, equity, balance
   );

   // 5. Send POST to Brain
   string response = "";
   int httpCode = brainClient.PostSignalRequest(payload, response);
   if(httpCode != 200)
   {
      Print("Failed to get signal from Brain. HTTP: ", httpCode);
      return;
   }
   lastSuccessfulPing = GetTickCount();

   // 6. Parse response and apply MasterRiskEA dynamic size multiplier sync
   string action = ExtractJsonString(response, "action");
   double lots   = ExtractJsonDouble(response, "lots");
   double sl     = ExtractJsonDouble(response, "sl");
   double tp     = ExtractJsonDouble(response, "tp");

   if(GlobalVariableCheck("SIZE_MULT"))
   {
      double sizeMult = GlobalVariableGet("SIZE_MULT");
      lots = NormalizeDouble(lots * sizeMult, 2);
   }

   if(action == "CLOSE_ALL")
   {
      CRiskManager::CloseAllPositions(InpMagicNumber);
      return;
   }

   // Check Max Open Trades limit
   int openCount = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0 && PositionGetInteger(POSITION_MAGIC) == InpMagicNumber)
      {
         openCount++;
      }
   }
   if(openCount >= InpMaxOpenTrades)
   {
      return;
   }

   // 7. Check Broker Spread Filter (Rollover / High Slippage Guard)
   long currentSpread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(currentSpread > InpMaxSpreadPoints)
   {
      PrintFormat("Trade blocked by Spread Filter: Current %d points > Max %d points (avoiding rollover slippage)", currentSpread, InpMaxSpreadPoints);
      return;
   }

   double limitPrice = ExtractJsonDouble(response, "limit_price");

   if(action == "BUY" && lots >= 0.01)
   {
      if(InpUseLimitOrders && limitPrice > 0.0)
      {
         trade.BuyLimit(lots, limitPrice, _Symbol, sl, tp, ORDER_TIME_GTC, 0, "AMATS Brain Maker Limit");
      }
      else
      {
         trade.Buy(lots, _Symbol, 0, sl, tp, "AMATS Brain Signal");
      }
   }
   else if(action == "SELL" && lots >= 0.01)
   {
      if(InpUseLimitOrders && limitPrice > 0.0)
      {
         trade.SellLimit(lots, limitPrice, _Symbol, sl, tp, ORDER_TIME_GTC, 0, "AMATS Brain Maker Limit");
      }
      else
      {
         trade.Sell(lots, _Symbol, 0, sl, tp, "AMATS Brain Signal");
      }
   }
}

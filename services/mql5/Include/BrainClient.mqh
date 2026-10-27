//+------------------------------------------------------------------+
//|                                                  BrainClient.mqh |
//|                                  AMATS Python Brain REST Client  |
//+------------------------------------------------------------------+
#property copyright "AMATS Trading System"
#property link      "https://github.com/jatinpruthvi/forex-crypto"
#property strict

class CBrainClient
{
private:
   string m_base_url;
   int    m_timeout;

public:
   CBrainClient() : m_base_url("http://127.0.0.1:8000"), m_timeout(5000) {}
   ~CBrainClient() {}

   void SetConfig(string base_url, int timeout_ms)
   {
      m_base_url = base_url;
      m_timeout  = timeout_ms;
   }

   bool CheckHealth()
   {
      string url = m_base_url + "/health";
      char post_data[];
      char result[];
      string result_headers;
      
      int res = WebRequest("GET", url, NULL, NULL, m_timeout, post_data, 0, result, result_headers);
      if(res == 200) return true;
      Print("CBrainClient::CheckHealth failed, HTTP code: ", res);
      return false;
   }

   int PostSignalRequest(string payload_json, string &response_json)
   {
      string url = m_base_url + "/signal";
      string headers = "Content-Type: application/json\r\n";
      char post_data[];
      char result[];
      string result_headers;

      StringToCharArray(payload_json, post_data, 0, WHOLE_ARRAY, CP_UTF8);
      int res = WebRequest("POST", url, headers, m_timeout, post_data, ArraySize(post_data) - 1, result, result_headers);

      if(res == 200)
      {
         response_json = CharArrayToString(result);
         return 200;
      }
      Print("CBrainClient::PostSignalRequest failed, HTTP code: ", res, " Error: ", GetLastError());
      return res;
   }
};

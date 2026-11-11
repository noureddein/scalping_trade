//+------------------------------------------------------------------+
//| ExecutionConnector.mq5 — Architecture C execution EA (TCP server)|
//|                                                                  |
//| Listens on a local TCP port for commands from the Python          |
//| Mt5ExecutionAdapter. Handles:                                    |
//|   order_send    — submit a market order via OrderSend            |
//|   close_position — close a position via OrderSend (close)        |
//|   query_order   — query deal/order state from history            |
//|   get_positions — list open positions for a symbol               |
//|                                                                  |
//| Wire protocol: length-prefixed JSON (same as ReadOnlyConnector)  |
//|   [4-byte big-endian uint32 length][UTF-8 JSON payload]          |
//|                                                                  |
//| Request envelope:                                                |
//|   {"type":"request","data":{"request":"<cmd>",...}}              |
//| Response envelope:                                               |
//|   {"type":"response","data":{"request":"<cmd>",...}}             |
//|                                                                  |
//| EXECUTION DISABLED BY DEFAULT. Input InpExecutionEnabled must be |
//| set to true AND the EA must be attached to a chart with algo     |
//| trading allowed before any OrderSend call is made. Both gates    |
//| are checked per request.                                         |
//|                                                                  |
//| Terminal setup required:                                         |
//|   Tools → Options → Expert Advisors:                             |
//|   1. Check "Allow Algo Trading".                                 |
//|   2. Add 127.0.0.1 to the allowed-address list.                 |
//|                                                                  |
//| Safety constraints:                                              |
//|   - Loopback only: binds to 127.0.0.1.                          |
//|   - Single client: one connection at a time.                     |
//|   - Execution disabled by default.                               |
//|   - Does not change terminal, chart, or system settings.         |
//|                                                                  |
//| Disabled-gate scope:                                             |
//|   When InpExecutionEnabled=false or algo trading is not allowed, |
//|   BOTH order_send AND close_position are blocked. The disabled   |
//|   gate is a structural safety stop for ALL broker-mutating ops.  |
//|   Risk-reducing closes are blocked alongside new entries. This   |
//|   is the approved Phase 5 policy. If a future policy requires    |
//|   close-only permission (risk reduction while entries blocked),  |
//|   add a separate InpCloseEnabled gate — the entry gate must      |
//|   never implicitly grant close permission or vice versa.         |
//|                                                                  |
//| NOT YET COMPILED OR TESTED.                                      |
//+------------------------------------------------------------------+
#property copyright "Scalping System"
#property version   "1.000"
#property strict

#include <Trade\Trade.mqh>

//--- Input parameters
input int    InpListenPort         = 9101;   // TCP listen port
input bool   InpExecutionEnabled   = false;  // Enable order execution (DISABLED by default)
input int    InpRecvTimeoutMs      = 50;     // Socket read timeout per poll (ms)

//--- State
int    g_serverSocket  = INVALID_HANDLE;
int    g_clientSocket  = INVALID_HANDLE;
bool   g_clientConnected = false;

//--- Receive buffer for incremental frame reading
uchar  g_recvBuf[];
int    g_recvLen = 0;

//+------------------------------------------------------------------+
//| Escape a string for safe embedding in JSON                       |
//+------------------------------------------------------------------+
string JsonEscape(string s)
  {
   string out = "";
   int len = StringLen(s);
   for(int i = 0; i < len; i++)
     {
      ushort ch = StringGetCharacter(s, i);
      if(ch == '\\')       out += "\\\\";
      else if(ch == '"')   out += "\\\"";
      else if(ch == '\n')  out += "\\n";
      else if(ch == '\r')  out += "\\r";
      else if(ch == '\t')  out += "\\t";
      else if(ch < 0x20)   out += StringFormat("\\u%04x", ch);
      else                 out += ShortToString(ch);
     }
   return out;
  }

//+------------------------------------------------------------------+
//| Send a length-prefixed JSON frame                                |
//+------------------------------------------------------------------+
bool SendFrame(int sock, string json)
  {
   uchar payload[];
   int len = StringToCharArray(json, payload, 0, WHOLE_ARRAY, CP_UTF8) - 1;
   if(len <= 0)
      return false;

   uchar frame[];
   ArrayResize(frame, 4 + len);
   frame[0] = (uchar)((len >> 24) & 0xFF);
   frame[1] = (uchar)((len >> 16) & 0xFF);
   frame[2] = (uchar)((len >> 8)  & 0xFF);
   frame[3] = (uchar)(len & 0xFF);
   ArrayCopy(frame, payload, 4, 0, len);

   int sent = SocketSend(sock, frame, ArraySize(frame));
   return (sent == ArraySize(frame));
  }

//+------------------------------------------------------------------+
//| Simple JSON string value extractor (no nested objects)           |
//| Finds "key":"value" and returns value. Returns "" if not found.  |
//+------------------------------------------------------------------+
string JsonGetString(const string &json, string key)
  {
   string search = "\"" + key + "\":\"";
   int pos = StringFind(json, search);
   if(pos < 0) return "";
   int start = pos + StringLen(search);
   int end = StringFind(json, "\"", start);
   if(end < 0) return "";
   return StringSubstr(json, start, end - start);
  }

//+------------------------------------------------------------------+
//| Simple JSON numeric value extractor                              |
//| Finds "key":value (number) and returns as string. "" if missing. |
//+------------------------------------------------------------------+
string JsonGetNumber(const string &json, string key)
  {
   string search = "\"" + key + "\":";
   int pos = StringFind(json, search);
   if(pos < 0) return "";
   int start = pos + StringLen(search);
   // Skip whitespace
   while(start < StringLen(json) && StringGetCharacter(json, start) == ' ')
      start++;
   // Read until comma, brace, or end
   string result = "";
   for(int i = start; i < StringLen(json); i++)
     {
      ushort ch = StringGetCharacter(json, i);
      if(ch == ',' || ch == '}' || ch == ']' || ch == ' ')
         break;
      result += ShortToString(ch);
     }
   return result;
  }

//+------------------------------------------------------------------+
//| Map MT5 retcode to order state string for the Python adapter     |
//+------------------------------------------------------------------+
string RetcodeToState(uint retcode)
  {
   switch(retcode)
     {
      case TRADE_RETCODE_DONE:         return "FILLED";
      case TRADE_RETCODE_DONE_PARTIAL: return "FILLED";
      case TRADE_RETCODE_PLACED:       return "SUBMITTED";
      case TRADE_RETCODE_REJECT:       return "REJECTED";
      case TRADE_RETCODE_CANCEL:       return "REJECTED";
      case TRADE_RETCODE_INVALID:      return "REJECTED";
      case TRADE_RETCODE_NO_MONEY:     return "REJECTED";
      case TRADE_RETCODE_MARKET_CLOSED:return "REJECTED";
      case TRADE_RETCODE_TRADE_DISABLED: return "REJECTED";
      case TRADE_RETCODE_PRICE_OFF:    return "REJECTED";
      case TRADE_RETCODE_REQUOTE:      return "REJECTED";
      case TRADE_RETCODE_TIMEOUT:      return "UNKNOWN";
      case TRADE_RETCODE_CONNECTION:   return "UNKNOWN";
      default:                         return "UNKNOWN";
     }
  }

//+------------------------------------------------------------------+
//| Build response JSON envelope                                     |
//+------------------------------------------------------------------+
string MakeResponse(string requestType, string dataJson)
  {
   return "{\"type\":\"response\",\"data\":{\"request\":\"" +
          requestType + "\"," + dataJson + "}}";
  }

//+------------------------------------------------------------------+
//| Handle order_send request                                        |
//+------------------------------------------------------------------+
void HandleOrderSend(const string &json)
  {
   // Check both gates: input flag AND terminal algo trading
   if(!InpExecutionEnabled)
     {
      string resp = MakeResponse("order_send",
         "\"state\":\"FAILED\",\"reject_reason\":\"execution_disabled_in_ea\"");
      SendFrame(g_clientSocket, resp);
      return;
     }
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
     {
      string resp = MakeResponse("order_send",
         "\"state\":\"FAILED\",\"reject_reason\":\"algo_trading_not_allowed\"");
      SendFrame(g_clientSocket, resp);
      return;
     }

   // Parse request fields
   string symbol  = JsonGetString(json, "symbol");
   string action  = JsonGetString(json, "action");
   string volume  = JsonGetString(json, "volume");
   string sl      = JsonGetString(json, "sl");
   string tp      = JsonGetString(json, "tp");
   string comment = JsonGetString(json, "comment");

   if(symbol == "" || action == "" || volume == "")
     {
      string resp = MakeResponse("order_send",
         "\"state\":\"REJECTED\",\"reject_reason\":\"missing_required_fields\"");
      SendFrame(g_clientSocket, resp);
      return;
     }

   ENUM_ORDER_TYPE orderType;
   if(action == "ORDER_TYPE_BUY")
      orderType = ORDER_TYPE_BUY;
   else if(action == "ORDER_TYPE_SELL")
      orderType = ORDER_TYPE_SELL;
   else
     {
      string resp = MakeResponse("order_send",
         "\"state\":\"REJECTED\",\"reject_reason\":\"invalid_action\"");
      SendFrame(g_clientSocket, resp);
      return;
     }

   double lots = StringToDouble(volume);
   double slPrice = (sl != "") ? StringToDouble(sl) : 0.0;
   double tpPrice = (tp != "") ? StringToDouble(tp) : 0.0;

   // Build and send the trade request
   MqlTradeRequest request = {};
   MqlTradeResult  result  = {};

   request.action    = TRADE_ACTION_DEAL;
   request.symbol    = symbol;
   request.volume    = lots;
   request.type      = orderType;
   request.sl        = slPrice;
   request.tp        = tpPrice;
   request.comment   = comment;  // idempotency_key[:31] from Python
   request.deviation = 10;
   // Fill price from current market
   request.price = (orderType == ORDER_TYPE_BUY)
                   ? SymbolInfoDouble(symbol, SYMBOL_ASK)
                   : SymbolInfoDouble(symbol, SYMBOL_BID);

   if(!OrderSend(request, result))
     {
      // OrderSend returned false — but retcode tells us more
      string state = RetcodeToState(result.retcode);
      string resp = MakeResponse("order_send",
         StringFormat("\"state\":\"%s\",\"broker_retcode\":%u,"
                      "\"reject_reason\":\"%s\","
                      "\"broker_ticket\":%I64d",
                      state, result.retcode,
                      JsonEscape(RetcodeDescription(result.retcode)),
                      result.order));
      SendFrame(g_clientSocket, resp);
      return;
     }

   // OrderSend succeeded — map the result
   string state = RetcodeToState(result.retcode);
   string fillPrice = (result.price != 0.0)
                      ? StringFormat("\"%.10g\"", result.price) : "null";
   string fillVol   = (result.volume != 0.0)
                      ? StringFormat("\"%.10g\"", result.volume) : "null";

   // Retrieve deal info for fill_time if available
   string fillTime = "null";
   if(result.deal > 0)
     {
      if(HistoryDealSelect(result.deal))
        {
         long dealTime = (long)HistoryDealGetInteger(result.deal, DEAL_TIME_MSC);
         fillTime = StringFormat("%I64d", dealTime);
        }
     }

   // Read back the raw comment from the deal to detect truncation
   string rawComment = "";
   if(result.deal > 0 && HistoryDealSelect(result.deal))
      rawComment = HistoryDealGetString(result.deal, DEAL_COMMENT);

   string resp = MakeResponse("order_send",
      StringFormat("\"state\":\"%s\",\"broker_ticket\":%I64d,"
                   "\"fill_price\":%s,\"fill_volume\":%s,"
                   "\"fill_time_ms\":%s,\"broker_retcode\":%u,"
                   "\"raw_comment\":\"%s\"",
                   state, result.order,
                   fillPrice, fillVol, fillTime,
                   result.retcode,
                   JsonEscape(rawComment)));
   SendFrame(g_clientSocket, resp);
  }

//+------------------------------------------------------------------+
//| Handle close_position request                                    |
//+------------------------------------------------------------------+
void HandleClosePosition(const string &json)
  {
   if(!InpExecutionEnabled)
     {
      string resp = MakeResponse("close_position",
         "\"state\":\"FAILED\",\"reject_reason\":\"execution_disabled_in_ea\"");
      SendFrame(g_clientSocket, resp);
      return;
     }
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
     {
      string resp = MakeResponse("close_position",
         "\"state\":\"FAILED\",\"reject_reason\":\"algo_trading_not_allowed\"");
      SendFrame(g_clientSocket, resp);
      return;
     }

   string ticketStr = JsonGetNumber(json, "ticket");
   string volume    = JsonGetString(json, "volume");
   if(ticketStr == "")
     {
      string resp = MakeResponse("close_position",
         "\"state\":\"REJECTED\",\"reject_reason\":\"missing_ticket\"");
      SendFrame(g_clientSocket, resp);
      return;
     }

   long ticket = StringToInteger(ticketStr);
   double lots = (volume != "") ? StringToDouble(volume) : 0.0;

   // Select the position to get its details
   if(!PositionSelectByTicket(ticket))
     {
      string resp = MakeResponse("close_position",
         StringFormat("\"state\":\"REJECTED\",\"broker_ticket\":%I64d,"
                      "\"reject_reason\":\"position_not_found\"", ticket));
      SendFrame(g_clientSocket, resp);
      return;
     }

   string symbol = PositionGetString(POSITION_SYMBOL);
   ENUM_POSITION_TYPE posType = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);

   MqlTradeRequest request = {};
   MqlTradeResult  result  = {};

   request.action   = TRADE_ACTION_DEAL;
   request.position = ticket;
   request.symbol   = symbol;
   request.volume   = (lots > 0) ? lots : PositionGetDouble(POSITION_VOLUME);
   // Close: opposite direction
   request.type     = (posType == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
   request.price    = (request.type == ORDER_TYPE_BUY)
                      ? SymbolInfoDouble(symbol, SYMBOL_ASK)
                      : SymbolInfoDouble(symbol, SYMBOL_BID);
   request.deviation = 10;

   if(!OrderSend(request, result))
     {
      string state = RetcodeToState(result.retcode);
      string resp = MakeResponse("close_position",
         StringFormat("\"state\":\"%s\",\"broker_ticket\":%I64d,"
                      "\"broker_retcode\":%u,"
                      "\"reject_reason\":\"%s\"",
                      state, ticket, result.retcode,
                      JsonEscape(RetcodeDescription(result.retcode))));
      SendFrame(g_clientSocket, resp);
      return;
     }

   string state = RetcodeToState(result.retcode);
   string resp = MakeResponse("close_position",
      StringFormat("\"state\":\"%s\",\"broker_ticket\":%I64d,"
                   "\"broker_retcode\":%u",
                   state, ticket, result.retcode));
   SendFrame(g_clientSocket, resp);
  }

//+------------------------------------------------------------------+
//| Handle query_order — look up deal/order state from history       |
//+------------------------------------------------------------------+
void HandleQueryOrder(const string &json)
  {
   string ticketStr = JsonGetNumber(json, "ticket");
   if(ticketStr == "")
     {
      string resp = MakeResponse("query_order",
         "\"state\":\"UNKNOWN\",\"reject_reason\":\"missing_ticket\"");
      SendFrame(g_clientSocket, resp);
      return;
     }

   long ticket = StringToInteger(ticketStr);

   // Check if it's a live order
   if(OrderSelect(ticket))
     {
      ENUM_ORDER_STATE oState = (ENUM_ORDER_STATE)OrderGetInteger(ORDER_STATE);
      string state = "UNKNOWN";
      if(oState == ORDER_STATE_FILLED)                 state = "FILLED";
      else if(oState == ORDER_STATE_CANCELED)           state = "REJECTED";
      else if(oState == ORDER_STATE_REJECTED)           state = "REJECTED";
      else if(oState == ORDER_STATE_EXPIRED)            state = "EXPIRED";
      else if(oState == ORDER_STATE_PLACED)             state = "SUBMITTED";
      else if(oState == ORDER_STATE_STARTED)            state = "SUBMITTED";
      else if(oState == ORDER_STATE_PARTIAL)            state = "SUBMITTED";
      else if(oState == ORDER_STATE_REQUEST_ADD ||
              oState == ORDER_STATE_REQUEST_MODIFY ||
              oState == ORDER_STATE_REQUEST_CANCEL)     state = "SUBMITTED";

      string rawComment = OrderGetString(ORDER_COMMENT);
      string resp = MakeResponse("query_order",
         StringFormat("\"state\":\"%s\",\"broker_ticket\":%I64d,"
                      "\"raw_comment\":\"%s\"",
                      state, ticket, JsonEscape(rawComment)));
      SendFrame(g_clientSocket, resp);
      return;
     }

   // Check history (terminal-wide, last 30 days)
   datetime from = TimeCurrent() - 30 * 86400;
   datetime to   = TimeCurrent() + 86400;
   if(HistoryOrderSelect(ticket))
     {
      ENUM_ORDER_STATE oState = (ENUM_ORDER_STATE)HistoryOrderGetInteger(ticket, ORDER_STATE);
      string state = "UNKNOWN";
      if(oState == ORDER_STATE_FILLED)       state = "FILLED";
      else if(oState == ORDER_STATE_CANCELED) state = "REJECTED";
      else if(oState == ORDER_STATE_REJECTED) state = "REJECTED";
      else if(oState == ORDER_STATE_EXPIRED)  state = "EXPIRED";

      // Get fill details from associated deals
      string fillPrice = "null";
      string fillVol = "null";
      string fillTime = "null";
      string rawComment = HistoryOrderGetString(ticket, ORDER_COMMENT);

      if(HistorySelect(from, to))
        {
         int totalDeals = HistoryDealsTotal();
         for(int i = 0; i < totalDeals; i++)
           {
            ulong dealTicket = HistoryDealGetTicket(i);
            if(dealTicket > 0 && HistoryDealGetInteger(dealTicket, DEAL_ORDER) == ticket)
              {
               double dp = HistoryDealGetDouble(dealTicket, DEAL_PRICE);
               double dv = HistoryDealGetDouble(dealTicket, DEAL_VOLUME);
               long   dt = (long)HistoryDealGetInteger(dealTicket, DEAL_TIME_MSC);
               fillPrice = StringFormat("\"%.10g\"", dp);
               fillVol   = StringFormat("\"%.10g\"", dv);
               fillTime  = StringFormat("%I64d", dt);
               rawComment = HistoryDealGetString(dealTicket, DEAL_COMMENT);
               break;
              }
           }
        }

      string resp = MakeResponse("query_order",
         StringFormat("\"state\":\"%s\",\"broker_ticket\":%I64d,"
                      "\"fill_price\":%s,\"fill_volume\":%s,"
                      "\"fill_time_ms\":%s,\"raw_comment\":\"%s\"",
                      state, ticket,
                      fillPrice, fillVol, fillTime,
                      JsonEscape(rawComment)));
      SendFrame(g_clientSocket, resp);
      return;
     }

   // Not found anywhere
   string resp = MakeResponse("query_order",
      StringFormat("\"state\":\"UNKNOWN\",\"broker_ticket\":%I64d,"
                   "\"reject_reason\":\"order_not_found\"", ticket));
   SendFrame(g_clientSocket, resp);
  }

//+------------------------------------------------------------------+
//| Handle get_positions — list open positions for a symbol          |
//+------------------------------------------------------------------+
void HandleGetPositions(const string &json)
  {
   string pair = JsonGetString(json, "pair");

   string positions = "[";
   int total = PositionsTotal();
   bool first = true;
   for(int i = 0; i < total; i++)
     {
      string symbol = PositionGetSymbol(i);
      if(symbol == "") continue;
      // Filter by pair if specified
      if(pair != "" && symbol != pair) continue;

      if(!first) positions += ",";
      first = false;

      long posTicket = (long)PositionGetInteger(POSITION_TICKET);
      ENUM_POSITION_TYPE posType = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      string side = (posType == POSITION_TYPE_BUY) ? "BUY" : "SELL";

      positions += StringFormat(
         "{\"ticket\":%I64d,\"pair\":\"%s\",\"symbol\":\"%s\","
         "\"side\":\"%s\",\"volume\":\"%.10g\","
         "\"open_price\":\"%.10g\",\"current_price\":\"%.10g\","
         "\"stop_loss\":\"%.10g\",\"take_profit\":\"%.10g\","
         "\"floating_pnl\":\"%.2f\","
         "\"open_time_ms\":%I64d,"
         "\"swap\":\"%.2f\",\"commission\":\"%.2f\"}",
         posTicket,
         JsonEscape(symbol), JsonEscape(symbol),
         side,
         PositionGetDouble(POSITION_VOLUME),
         PositionGetDouble(POSITION_PRICE_OPEN),
         PositionGetDouble(POSITION_PRICE_CURRENT),
         PositionGetDouble(POSITION_SL),
         PositionGetDouble(POSITION_TP),
         PositionGetDouble(POSITION_PROFIT),
         (long)PositionGetInteger(POSITION_TIME_MSC),
         PositionGetDouble(POSITION_SWAP),
         PositionGetDouble(POSITION_COMMISSION));
     }
   positions += "]";

   string resp = MakeResponse("get_positions",
      "\"positions\":" + positions);
   SendFrame(g_clientSocket, resp);
  }

//+------------------------------------------------------------------+
//| Dispatch a parsed request to the appropriate handler             |
//+------------------------------------------------------------------+
void DispatchRequest(const string &json)
  {
   // Extract request type via substring match
   if(StringFind(json, "\"order_send\"") >= 0)
      HandleOrderSend(json);
   else if(StringFind(json, "\"close_position\"") >= 0)
      HandleClosePosition(json);
   else if(StringFind(json, "\"query_order\"") >= 0)
      HandleQueryOrder(json);
   else if(StringFind(json, "\"get_positions\"") >= 0)
      HandleGetPositions(json);
   else
     {
      PrintFormat("ExecutionConnector: unknown request type in: %.80s", json);
     }
  }

//+------------------------------------------------------------------+
//| Read available bytes and process complete frames                 |
//+------------------------------------------------------------------+
void ReadClientRequests()
  {
   if(g_clientSocket == INVALID_HANDLE)
      return;

   uint avail = SocketIsReadable(g_clientSocket);
   if(avail > 0)
     {
      uchar chunk[];
      int toRead = (int)MathMin(avail, 8192);
      int got = SocketRead(g_clientSocket, chunk, toRead, InpRecvTimeoutMs);
      if(got > 0)
        {
         int oldLen = g_recvLen;
         g_recvLen += got;
         ArrayResize(g_recvBuf, g_recvLen);
         ArrayCopy(g_recvBuf, chunk, oldLen, 0, got);
        }
      else if(got < 0)
        {
         PrintFormat("ExecutionConnector: client read error, disconnecting");
         CloseClient();
         return;
        }
     }

   // Process complete frames
   while(g_recvLen >= 4)
     {
      int msgLen = (g_recvBuf[0] << 24) | (g_recvBuf[1] << 16)
                 | (g_recvBuf[2] << 8)  |  g_recvBuf[3];
      if(msgLen <= 0 || msgLen > 1048576)
        {
         g_recvLen = 0;
         ArrayResize(g_recvBuf, 0);
         return;
        }
      int frameLen = 4 + msgLen;
      if(g_recvLen < frameLen)
         return;

      string json = CharArrayToString(g_recvBuf, 4, msgLen, CP_UTF8);

      // Shift remaining bytes
      int remaining = g_recvLen - frameLen;
      if(remaining > 0)
        {
         uchar tmp[];
         ArrayResize(tmp, remaining);
         ArrayCopy(tmp, g_recvBuf, 0, frameLen, remaining);
         ArrayResize(g_recvBuf, remaining);
         ArrayCopy(g_recvBuf, tmp, 0, 0, remaining);
        }
      else
        {
         ArrayResize(g_recvBuf, 0);
        }
      g_recvLen = remaining;

      DispatchRequest(json);
     }
  }

//+------------------------------------------------------------------+
//| Close client connection                                          |
//+------------------------------------------------------------------+
void CloseClient()
  {
   if(g_clientSocket != INVALID_HANDLE)
     {
      SocketClose(g_clientSocket);
      g_clientSocket = INVALID_HANDLE;
     }
   g_clientConnected = false;
   g_recvLen = 0;
   ArrayResize(g_recvBuf, 0);
  }

//+------------------------------------------------------------------+
//| Accept a new client (non-blocking via SocketIsReadable)          |
//+------------------------------------------------------------------+
void AcceptClient()
  {
   if(g_clientConnected)
      return;
   // SocketAccept with 0ms timeout — non-blocking
   int client = SocketAccept(g_serverSocket, 0);
   if(client != INVALID_HANDLE)
     {
      g_clientSocket = client;
      g_clientConnected = true;
      PrintFormat("ExecutionConnector: client connected");
     }
  }

//+------------------------------------------------------------------+
//| Expert initialization                                            |
//+------------------------------------------------------------------+
int OnInit()
  {
   g_serverSocket = SocketCreate();
   if(g_serverSocket == INVALID_HANDLE)
     {
      PrintFormat("ExecutionConnector: SocketCreate failed, error %d", GetLastError());
      return INIT_FAILED;
     }

   if(!SocketBind(g_serverSocket, "127.0.0.1", InpListenPort))
     {
      PrintFormat("ExecutionConnector: SocketBind to 127.0.0.1:%d failed, error %d",
                  InpListenPort, GetLastError());
      SocketClose(g_serverSocket);
      g_serverSocket = INVALID_HANDLE;
      return INIT_FAILED;
     }

   if(!SocketListen(g_serverSocket, 1))
     {
      PrintFormat("ExecutionConnector: SocketListen failed, error %d", GetLastError());
      SocketClose(g_serverSocket);
      g_serverSocket = INVALID_HANDLE;
      return INIT_FAILED;
     }

   PrintFormat("ExecutionConnector: listening on 127.0.0.1:%d, execution_enabled=%s",
               InpListenPort, InpExecutionEnabled ? "true" : "false");
   if(!InpExecutionEnabled)
      Print("ExecutionConnector: ORDER EXECUTION IS DISABLED. "
            "Read-only queries (query_order, get_positions) will work.");

   EventSetMillisecondTimer(50);
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
//| Expert deinitialization                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   CloseClient();
   if(g_serverSocket != INVALID_HANDLE)
     {
      SocketClose(g_serverSocket);
      g_serverSocket = INVALID_HANDLE;
     }
  }

//+------------------------------------------------------------------+
//| Timer handler — accept clients, read/dispatch requests           |
//+------------------------------------------------------------------+
void OnTimer()
  {
   if(!g_clientConnected)
      AcceptClient();

   if(g_clientConnected)
      ReadClientRequests();
  }
//+------------------------------------------------------------------+

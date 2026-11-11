//+------------------------------------------------------------------+
//| ReadOnlyConnector.mq5 — Architecture C read-only EA client       |
//|                                                                  |
//| Connects to the Python backend over TCP 127.0.0.1 and pushes    |
//| read-only data: heartbeat, account info, symbol list, contract   |
//| specs, and tick data (bid/ask) for the chart symbol.             |
//| No order submission, modification, or closing.                   |
//|                                                                  |
//| Tick capture is best-effort. MQL5 serializes event handlers on   |
//| a single thread — OnTick cannot fire while OnTimer (or another   |
//| OnTick) is executing. Ticks arriving during a handler call are   |
//| queued by the terminal but may be coalesced or dropped before    |
//| OnTick sees them. The ring buffer further drops the oldest ticks |
//| when full. Do not treat captured data as lossless or use         |
//| unmeasured sampled data as proof of live spread accuracy or      |
//| entry safety.                                                    |
//|                                                                  |
//| Wire protocol: length-prefixed JSON                              |
//|   [4-byte big-endian uint32 length][UTF-8 JSON payload]          |
//|                                                                  |
//| Terminal setup required:                                         |
//|   Tools → Options → Expert Advisors:                             |
//|   1. Check "Allow Algo Trading".                                 |
//|   2. Add 127.0.0.1 to the allowed-address list.                 |
//|   The allowed-address list governs both WebRequest (HTTP) and    |
//|   SocketConnect (raw TCP). This EA uses raw TCP, not WebRequest. |
//|                                                                  |
//| Safety constraints:                                              |
//|   - Read-only: does not call OrderSend, OrderModify, etc.        |
//|   - Socket connect/read/send in OnTimer; SocketClose in OnDeinit.|
//|   - No socket I/O in OnInit or OnTick.                           |
//|   - Loopback only: connects to 127.0.0.1.                       |
//|   - Fail-closed: stops sending if socket write fails.            |
//|   - Does not change terminal, chart, or system settings.         |
//|                                                                  |
//| NOT YET COMPILED OR TESTED.                                      |
//| Local dev: native Windows MT5 + Python backend in WSL.           |
//| Deployment: Ubuntu server with MT5 under Wine.                   |
//+------------------------------------------------------------------+
#property copyright "Scalping System"
#property version   "1.000"
#property strict

#include <Trade\SymbolInfo.mqh>

//--- Input parameters
input string InpHost             = "127.0.0.1";  // Backend host (loopback only)
input int    InpPort             = 9100;          // Backend TCP port
input int    InpHeartbeatSec     = 3;             // Heartbeat interval (seconds)
input int    InpDiscoverySec     = 15;            // Symbol/account push interval (seconds)
input int    InpTickBufCapacity  = 128;           // Tick ring buffer capacity (provisional)
input int    InpFlushIntervalMs  = 500;           // Tick batch flush interval ms (provisional)

//--- State
int    g_socket       = INVALID_HANDLE;
bool   g_connected    = false;

//--- Receive buffer for incremental frame reading
uchar  g_recvBuf[];
int    g_recvLen      = 0;

//--- Time-based cadence tracking (ms via GetTickCount64)
ulong  g_lastHeartbeatMs = 0;
ulong  g_lastDiscoveryMs = 0;
ulong  g_lastFlushMs     = 0;

//--- Tick ring buffer: OnTick writes, OnTimer batch-sends, then clears.
//    MQL5 is single-threaded (OnTick and OnTimer never overlap), so
//    no lock needed. When the buffer is full, the oldest tick is
//    overwritten (ring overflow). Overflow count is reported per batch.
//    Capture is best-effort — see header comment.
//
//    Drop counters measure TWO DISTINCT loss mechanisms:
//      g_overwrittenFlush — ticks overwritten in the ring buffer because
//          the buffer was full before OnTimer could flush. This counts
//          loss WITHIN the EA, observable by the EA. Reset per batch.
//      (invisible) — the MQL5 terminal may coalesce or skip NewTick
//          events while another handler (OnTimer, OnTick) is executing.
//          These missed events never reach OnTick and are NOT counted
//          by any EA-side counter. They are invisible to user code.
//    Neither counter captures network-layer loss (partial sends, dropped
//    connections). On send failure the ring is preserved (not cleared)
//    and the batch is re-attempted on the next successful connection
//    with the same (ea_run_id, batch_seq) pair so the Python backend
//    can deduplicate.
MqlTick g_tickRing[];
int     g_ringHead          = 0;   // next write position
int     g_ringCount         = 0;   // ticks currently in buffer
long    g_overwrittenFlush  = 0;   // ring overwrites since last successful flush
long    g_overwrittenTotal  = 0;   // ring overwrites lifetime (for periodic log)
long    g_batchesSent       = 0;
long    g_totalTicksIn      = 0;   // total OnTick calls that wrote to ring

//--- EA identity and batch sequencing for dedup across reconnects.
//
//    terminal_instance_id (string): TerminalInfoString(TERMINAL_DATA_PATH).
//    Unique per MT5 installation — the path contains a per-install hash.
//    Distinguishes two terminals running on the same machine.
//
//    ea_instance_id (string): Symbol + "_" + ChartID(). Stable per chart
//    within a terminal — survives EA restarts, timeframe changes, and
//    recompilation. Changes only when the chart window is closed/reopened.
//
//    ea_run_id (ulong): persistent per-instance counter stored in
//    MQL5/Files/ReadOnlyConnector/<sanitized_ea_instance_id>.run_counter.
//    Incremented on every OnInit — guaranteed unique even for sub-ms
//    EA restarts on the same chart. File is per-instance so no
//    contention between EAs on different charts. If the counter file
//    cannot be read, validated, incremented, written (exactly 8 bytes),
//    and flushed, OnInit returns INIT_FAILED — the EA does not connect
//    or emit tick batches. No fallback ID source.
//    Set once in OnInit, unchanged across reconnects within that run,
//    so retried batches keep the same identity.
//
//    batch_seq (long): monotonic counter within a run, incremented only
//    on successful send. On send failure the ring is preserved and the
//    same (terminal_instance_id, ea_instance_id, ea_run_id, batch_seq)
//    is re-sent on the next flush. The Python backend rejects
//    seq <= last accepted for the same stream, resets tracking on new
//    run_id, and counts gaps without treating them as proof of lossless
//    capture.
string g_terminalInstanceId = "";
string g_eaInstanceId = "";
ulong  g_eaRunId      = 0;
long   g_batchSeq     = 0;

//+------------------------------------------------------------------+
//| Sanitize an EA instance ID for use as a filename component.      |
//| Replaces characters illegal in Windows/MQL5 filenames with '_'.  |
//+------------------------------------------------------------------+
string SanitizeFilename(string s)
  {
   string out = "";
   int len = StringLen(s);
   for(int i = 0; i < len; i++)
     {
      ushort ch = StringGetCharacter(s, i);
      if(ch == '\\' || ch == '/' || ch == ':' || ch == '*' ||
         ch == '?'  || ch == '"' || ch == '<' || ch == '>' ||
         ch == '|'  || ch < 0x20)
         out += "_";
      else
         out += ShortToString(ch);
     }
   return out;
  }

//+------------------------------------------------------------------+
//| Generate a persistent, collision-resistant run ID.                |
//| Reads and increments a per-instance counter file in MQL5/Files.  |
//| Guarantees uniqueness even for sub-ms EA restarts on the same    |
//| chart. Returns false if the counter cannot be reliably persisted. |
//|                                                                  |
//| Counter file location:                                           |
//|   FileOpen paths are relative to the terminal's sandbox:         |
//|     <terminal_data_path>\MQL5\Files\                             |
//|   So the full physical path is:                                  |
//|     <terminal_data_path>\MQL5\Files\ReadOnlyConnector\           |
//|         <sanitized_ea_instance_id>.run_counter                   |
//|   The terminal_data_path contains a per-install hash, e.g.:     |
//|     C:\Users\<user>\AppData\Roaming\MetaQuotes\Terminal\<hash>   |
//+------------------------------------------------------------------+
bool GenerateRunId(string instanceId, ulong &runIdOut)
  {
   string dir = "ReadOnlyConnector";
   string safeId = SanitizeFilename(instanceId);
   string filename = dir + "\\" + safeId + ".run_counter";

   if(!FolderCreate(dir))
     {
      // FolderCreate returns false both when the folder already exists
      // (not an error) and on actual failure. Proceed — FileOpen will
      // surface a real permissions problem.
     }

   //--- Probe whether the counter file exists
   int hProbe = FileOpen(filename, FILE_READ | FILE_BIN | FILE_SHARE_READ);
   bool fileExists = (hProbe != INVALID_HANDLE);

   if(fileExists)
     {
      ulong fsize = FileSize(hProbe);
      FileClose(hProbe);

      if(fsize != 8)
        {
         PrintFormat("ReadOnlyConnector: ERROR — counter file %s exists but has size %I64u "
                     "(expected exactly 8). File is corrupt; delete it and restart the EA.",
                     filename, fsize);
         return false;
        }

      //--- Existing file: read, validate, increment, seek-to-0, overwrite, flush, verify
      int h = FileOpen(filename, FILE_READ | FILE_WRITE | FILE_BIN);
      if(h == INVALID_HANDLE)
        {
         PrintFormat("ReadOnlyConnector: ERROR — cannot open counter file %s for read/write, error %d",
                     filename, GetLastError());
         return false;
        }

      ResetLastError();
      long counter = FileReadLong(h);
      if(GetLastError() != 0)
        {
         PrintFormat("ReadOnlyConnector: ERROR — FileReadLong failed for %s, error %d",
                     filename, GetLastError());
         FileClose(h);
         return false;
        }
      if(counter < 0)
        {
         PrintFormat("ReadOnlyConnector: ERROR — counter file %s contains invalid value %I64d",
                     filename, counter);
         FileClose(h);
         return false;
        }

      counter++;

      if(!FileSeek(h, 0, SEEK_SET))
        {
         PrintFormat("ReadOnlyConnector: ERROR — FileSeek to 0 failed for %s, error %d",
                     filename, GetLastError());
         FileClose(h);
         return false;
        }

      uint written = FileWriteLong(h, counter);
      if(written != 8)
        {
         PrintFormat("ReadOnlyConnector: ERROR — FileWriteLong wrote %u bytes (expected 8) to %s",
                     written, filename);
         FileClose(h);
         return false;
        }

      FileFlush(h);

      ulong finalSize = FileSize(h);
      if(finalSize != 8)
        {
         PrintFormat("ReadOnlyConnector: ERROR — counter file %s is %I64u bytes after write (expected 8)",
                     filename, finalSize);
         FileClose(h);
         return false;
        }

      FileClose(h);
      runIdOut = (ulong)counter;
      PrintFormat("ReadOnlyConnector: run counter %I64u persisted to MQL5\\Files\\%s",
                  runIdOut, filename);
      return true;
     }

   //--- Probe returned INVALID_HANDLE — distinguish "absent" from "unreadable".
   if(FileIsExist(filename))
     {
      PrintFormat("ReadOnlyConnector: ERROR — counter file %s exists but cannot be opened "
                  "for reading (error %d). Will not overwrite; fix permissions and restart.",
                  filename, GetLastError());
      return false;
     }

   //--- First run: file confirmed absent. Create it with counter = 1.
   int h = FileOpen(filename, FILE_WRITE | FILE_BIN);
   if(h == INVALID_HANDLE)
     {
      PrintFormat("ReadOnlyConnector: ERROR — cannot create counter file %s, error %d",
                  filename, GetLastError());
      return false;
     }

   long counter = 1;
   uint written = FileWriteLong(h, counter);
   if(written != 8)
     {
      PrintFormat("ReadOnlyConnector: ERROR — FileWriteLong wrote %u bytes (expected 8) to %s",
                  written, filename);
      FileClose(h);
      return false;
     }

   FileFlush(h);

   ulong finalSize = FileSize(h);
   if(finalSize != 8)
     {
      PrintFormat("ReadOnlyConnector: ERROR — new counter file %s is %I64u bytes after write (expected 8)",
                  filename, finalSize);
      FileClose(h);
      return false;
     }

   FileClose(h);
   runIdOut = (ulong)counter;
   PrintFormat("ReadOnlyConnector: first run — counter 1 persisted to MQL5\\Files\\%s",
               runIdOut, filename);
   return true;
  }

//+------------------------------------------------------------------+
//| Framing: 4-byte big-endian length + UTF-8 JSON                   |
//+------------------------------------------------------------------+
bool SendFrame(int sock, string json)
  {
   uchar payload[];
   int len = StringToCharArray(json, payload, 0, WHOLE_ARRAY, CP_UTF8) - 1;
   if(len <= 0)
      return false;

   uchar frame[];
   ArrayResize(frame, 4 + len);
   // Big-endian uint32 length
   frame[0] = (uchar)((len >> 24) & 0xFF);
   frame[1] = (uchar)((len >> 16) & 0xFF);
   frame[2] = (uchar)((len >> 8)  & 0xFF);
   frame[3] = (uchar)(len & 0xFF);
   ArrayCopy(frame, payload, 4, 0, len);

   int sent = SocketSend(sock, frame, ArraySize(frame));
   return (sent == ArraySize(frame));
  }

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
      else if(ch == 0x08)  out += "\\b";
      else if(ch == 0x0C)  out += "\\f";
      else if(ch < 0x20)   out += StringFormat("\\u%04x", ch);
      else                 out += ShortToString(ch);
     }
   return out;
  }

//+------------------------------------------------------------------+
//| Build JSON message string                                        |
//+------------------------------------------------------------------+
string MakeMessage(string msgType, string dataJson)
  {
   return "{\"type\":\"" + msgType + "\",\"data\":" + dataJson + "}";
  }

//+------------------------------------------------------------------+
//| Connect to the Python backend                                    |
//+------------------------------------------------------------------+
bool ConnectToBackend()
  {
   if(g_socket != INVALID_HANDLE)
     {
      SocketClose(g_socket);
      g_socket = INVALID_HANDLE;
     }

   g_socket = SocketCreate();
   if(g_socket == INVALID_HANDLE)
     {
      PrintFormat("ReadOnlyConnector: SocketCreate failed, error %d", GetLastError());
      return false;
     }

   if(!SocketConnect(g_socket, InpHost, InpPort, 3000))
     {
      int err = GetLastError();
      PrintFormat("ReadOnlyConnector: SocketConnect to %s:%d failed, error %d. "
                  "Check: (1) %s is in the allowed-address list "
                  "(Tools → Options → Expert Advisors), "
                  "(2) the Python backend is running on port %d, "
                  "(3) no firewall is blocking loopback.",
                  InpHost, InpPort, err, InpHost, InpPort);
      SocketClose(g_socket);
      g_socket = INVALID_HANDLE;
      return false;
     }

   g_connected = true;
   g_lastHeartbeatMs = GetTickCount64();
   PrintFormat("ReadOnlyConnector: connected to %s:%d", InpHost, InpPort);
   return true;
  }

//+------------------------------------------------------------------+
//| Disconnect                                                       |
//+------------------------------------------------------------------+
void DisconnectFromBackend()
  {
   if(g_socket != INVALID_HANDLE)
     {
      SocketClose(g_socket);
      g_socket = INVALID_HANDLE;
     }
   g_connected = false;
   g_recvLen = 0;
   ArrayResize(g_recvBuf, 0);
  }

//+------------------------------------------------------------------+
//| Send heartbeat                                                   |
//+------------------------------------------------------------------+
void SendHeartbeat()
  {
   string msg = MakeMessage("heartbeat", "{}");
   if(!SendFrame(g_socket, msg))
     {
      Print("ReadOnlyConnector: heartbeat send failed, disconnecting");
      DisconnectFromBackend();
     }
  }

//+------------------------------------------------------------------+
//| Send account info                                                |
//+------------------------------------------------------------------+
void SendAccountInfo()
  {
   long login = AccountInfoInteger(ACCOUNT_LOGIN);
   long leverage = AccountInfoInteger(ACCOUNT_LEVERAGE);
   string data = StringFormat(
      "{\"login\":%I64d,\"server\":\"%s\",\"currency\":\"%s\","
      "\"balance\":\"%.2f\",\"equity\":\"%.2f\",\"margin_free\":\"%.2f\","
      "\"account_type\":\"%s\",\"leverage\":%I64d,\"company\":\"%s\"}",
      login,
      JsonEscape(AccountInfoString(ACCOUNT_SERVER)),
      JsonEscape(AccountInfoString(ACCOUNT_CURRENCY)),
      AccountInfoDouble(ACCOUNT_BALANCE),
      AccountInfoDouble(ACCOUNT_EQUITY),
      AccountInfoDouble(ACCOUNT_MARGIN_FREE),
      (AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_DEMO) ? "demo" : "live",
      leverage,
      JsonEscape(AccountInfoString(ACCOUNT_COMPANY)));

   string msg = MakeMessage("account_info", data);
   if(!SendFrame(g_socket, msg))
     {
      Print("ReadOnlyConnector: account_info send failed, disconnecting");
      DisconnectFromBackend();
     }
  }

//+------------------------------------------------------------------+
//| Send symbol list                                                 |
//+------------------------------------------------------------------+
void SendSymbolList()
  {
   int total = SymbolsTotal(true);  // only symbols in Market Watch
   string symbols = "[";
   for(int i = 0; i < total; i++)
     {
      if(i > 0) symbols += ",";
      symbols += "\"" + JsonEscape(SymbolName(i, true)) + "\"";
     }
   symbols += "]";

   string msg = MakeMessage("symbol_list", "{\"symbols\":" + symbols + "}");
   if(!SendFrame(g_socket, msg))
     {
      Print("ReadOnlyConnector: symbol_list send failed, disconnecting");
      DisconnectFromBackend();
     }
  }

//+------------------------------------------------------------------+
//| Send contract spec for one symbol                                |
//+------------------------------------------------------------------+
void SendContractSpec(string symbol)
  {
   CSymbolInfo si;
   if(!si.Name(symbol) || !si.RefreshRates())
      return;

   // margin_initial: MT5 returns 0.0 when not set — send null for consistency
   // with commission_per_lot (Python parser treats null as None).
   string marginInit = (si.MarginInitial() != 0.0)
      ? StringFormat("\"%.10g\"", si.MarginInitial()) : "null";
   string swapLong   = "\"" + StringFormat("%.10g", si.SwapLong()) + "\"";
   string swapShort  = "\"" + StringFormat("%.10g", si.SwapShort()) + "\"";

   string data = StringFormat(
      "{\"broker_symbol\":\"%s\",\"digits\":%d,"
      "\"point\":\"%.10g\",\"tick_size\":\"%.10g\",\"tick_value\":\"%.10g\","
      "\"contract_size\":\"%.10g\","
      "\"volume_min\":\"%.10g\",\"volume_max\":\"%.10g\",\"volume_step\":\"%.10g\","
      "\"min_stop_distance\":\"%.10g\",\"trade_allowed\":%s,"
      "\"margin_initial\":%s,"
      "\"commission_per_lot\":null,\"swap_long\":%s,\"swap_short\":%s}",
      JsonEscape(symbol),
      si.Digits(),
      si.Point(),
      si.TickSize(),
      si.TickValue(),
      si.ContractSize(),
      si.LotsMin(),
      si.LotsMax(),
      si.LotsStep(),
      (double)si.StopsLevel() * si.Point(),
      si.TradeMode() != SYMBOL_TRADE_MODE_DISABLED ? "true" : "false",
      marginInit,
      swapLong,
      swapShort);

   string msg = MakeMessage("contract_spec", data);
   if(!SendFrame(g_socket, msg))
     {
      PrintFormat("ReadOnlyConnector: contract_spec send failed for %s, disconnecting", symbol);
      DisconnectFromBackend();
     }
  }

//+------------------------------------------------------------------+
//| Send contract specs for all Market Watch symbols                 |
//+------------------------------------------------------------------+
void SendAllContractSpecs()
  {
   int total = SymbolsTotal(true);
   for(int i = 0; i < total && g_connected; i++)
      SendContractSpec(SymbolName(i, true));
  }

//+------------------------------------------------------------------+
//| Read available bytes into g_recvBuf without blocking OnTimer.    |
//| Processes complete frames; retains partial data for next tick.   |
//+------------------------------------------------------------------+
void ReadBackendRequests()
  {
   if(g_socket == INVALID_HANDLE)
      return;

   // Drain available bytes into g_recvBuf (non-blocking via SocketIsReadable)
   uint avail = SocketIsReadable(g_socket);
   if(avail > 0)
     {
      uchar chunk[];
      int toRead = (int)MathMin(avail, 8192);
      int got = SocketRead(g_socket, chunk, toRead, 50);
      if(got > 0)
        {
         int oldLen = g_recvLen;
         g_recvLen += got;
         ArrayResize(g_recvBuf, g_recvLen);
         ArrayCopy(g_recvBuf, chunk, oldLen, 0, got);
        }
     }

   // Process complete frames from g_recvBuf
   while(g_recvLen >= 4)
     {
      int msgLen = (g_recvBuf[0] << 24) | (g_recvBuf[1] << 16)
                 | (g_recvBuf[2] << 8)  |  g_recvBuf[3];
      if(msgLen <= 0 || msgLen > 1048576)
        {
         // Protocol error — discard buffer
         g_recvLen = 0;
         ArrayResize(g_recvBuf, 0);
         return;
        }
      int frameLen = 4 + msgLen;
      if(g_recvLen < frameLen)
         return;  // incomplete frame — wait for more data

      string json = CharArrayToString(g_recvBuf, 4, msgLen, CP_UTF8);

      // Shift remaining bytes to front of buffer
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

      // Dispatch — ponytail: substring match, 3 request types, no overlap
      if(StringFind(json, "\"get_symbols\"") >= 0)
         SendSymbolList();
      else if(StringFind(json, "\"get_account\"") >= 0)
         SendAccountInfo();
      else if(StringFind(json, "\"get_contracts\"") >= 0)
         SendAllContractSpecs();
     }
  }

//+------------------------------------------------------------------+
//| Expert initialization                                            |
//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpHost != "127.0.0.1" && InpHost != "localhost")
     {
      Print("ReadOnlyConnector: REJECTED — host must be 127.0.0.1 or localhost (loopback only)");
      return INIT_FAILED;
     }

   int cap = MathMax(InpTickBufCapacity, 1);
   ArrayResize(g_tickRing, cap);

   g_terminalInstanceId = TerminalInfoString(TERMINAL_DATA_PATH);
   g_eaInstanceId       = _Symbol + "_" + IntegerToString(ChartID());
   g_batchSeq           = 0;

   if(!GenerateRunId(g_eaInstanceId, g_eaRunId))
     {
      Print("ReadOnlyConnector: FATAL — run ID generation failed, EA will not initialize. "
            "Check MQL5\\Files\\ReadOnlyConnector\\ directory permissions and file integrity.");
      return INIT_FAILED;
     }

   Print("ReadOnlyConnector: requires 127.0.0.1 in Tools → Options → Expert Advisors → allowed-address list");
   PrintFormat("ReadOnlyConnector: terminal=%s, instance=%s, run_id=%I64u, tick buffer=%d, flush interval=%d ms (best-effort capture)",
               g_terminalInstanceId, g_eaInstanceId, g_eaRunId, cap, InpFlushIntervalMs);

   ulong now = GetTickCount64();
   g_lastHeartbeatMs = now;
   g_lastDiscoveryMs = now;
   g_lastFlushMs     = now;

   EventSetMillisecondTimer(MathMax(InpFlushIntervalMs, 10));
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
//| Expert deinitialization — SocketClose cleanup                    |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   DisconnectFromBackend();
  }

//+------------------------------------------------------------------+
//| Timer handler — connect/read/send happen here (not OnInit/OnTick)|
//+------------------------------------------------------------------+
void OnTimer()
  {
   ulong now = GetTickCount64();
   ulong heartbeatMs  = (ulong)InpHeartbeatSec * 1000;
   ulong discoveryMs  = (ulong)InpDiscoverySec * 1000;
   ulong flushMs      = (ulong)MathMax(InpFlushIntervalMs, 10);

   // Connect/reconnect if disconnected
   if(!g_connected)
     {
      if(now - g_lastHeartbeatMs >= heartbeatMs)
        {
         g_lastHeartbeatMs = now;
         if(ConnectToBackend())
           {
            SendHeartbeat();
            if(g_connected) SendAccountInfo();
            if(g_connected) SendSymbolList();
            if(g_connected) SendAllContractSpecs();
            g_lastDiscoveryMs = now;
           }
        }
      return;
     }

   // Read any pending backend requests
   ReadBackendRequests();

   // Flush buffered ticks as a batch
   if(now - g_lastFlushMs >= flushMs)
     {
      g_lastFlushMs = now;
      FlushTickBuffer();
     }

   // Heartbeat
   if(now - g_lastHeartbeatMs >= heartbeatMs)
     {
      g_lastHeartbeatMs = now;
      SendHeartbeat();
     }

   // Periodic discovery push
   if(g_connected && now - g_lastDiscoveryMs >= discoveryMs)
     {
      g_lastDiscoveryMs = now;
      SendAccountInfo();
      if(g_connected) SendSymbolList();
      if(g_connected) SendAllContractSpecs();
     }
  }

//+------------------------------------------------------------------+
//| OnTick — buffer tick into ring buffer for the chart symbol.      |
//| No socket I/O here. OnTimer batch-sends the buffer.              |
//| Multi-symbol: attach one EA per chart. Each EA captures its own  |
//| chart symbol only. Multi-symbol from a single EA is deferred.    |
//+------------------------------------------------------------------+
void OnTick()
  {
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
      return;

   int cap = ArraySize(g_tickRing);
   g_totalTicksIn++;

   if(g_ringCount >= cap)
     {
      g_overwrittenFlush++;
      g_overwrittenTotal++;
     }
   else
      g_ringCount++;

   g_tickRing[g_ringHead] = tick;
   g_ringHead = (g_ringHead + 1) % cap;
  }

//+------------------------------------------------------------------+
//| Batch-send buffered ticks over TCP. Called from OnTimer only.     |
//| Wire format: {"type":"tick_batch","data":{...}} with ticks array |
//| ordered oldest-to-newest. newest_index marks the current quote.  |
//|                                                                  |
//| Send failure: ring and counters are NOT cleared. The same         |
//| (ea_run_id, batch_seq) will be re-sent on the next successful    |
//| flush. DisconnectFromBackend tears down the socket, discarding   |
//| any partial frame in the kernel buffer. The Python backend        |
//| deduplicates by (ea_run_id, batch_seq).                          |
//|                                                                  |
//| Send success: ring, per-flush overwrite counter, and batch_seq   |
//| are advanced only after SendFrame returns true.                   |
//+------------------------------------------------------------------+
void FlushTickBuffer()
  {
   if(g_ringCount == 0 || !g_connected || g_socket == INVALID_HANDLE)
      return;

   int cap   = ArraySize(g_tickRing);
   int count = g_ringCount;
   // oldest entry in the ring
   int start = (g_ringHead - count + cap) % cap;

   string ticksArr = "[";
   for(int i = 0; i < count; i++)
     {
      int idx = (start + i) % cap;
      if(i > 0) ticksArr += ",";
      ticksArr += StringFormat(
         "{\"bid\":\"%.10g\",\"ask\":\"%.10g\",\"server_time_ms\":%I64d}",
         g_tickRing[idx].bid,
         g_tickRing[idx].ask,
         g_tickRing[idx].time_msc);
     }
   ticksArr += "]";

   long dropped = g_overwrittenFlush;
   string data = StringFormat(
      "{\"broker_symbol\":\"%s\",\"ticks\":%s,"
      "\"newest_index\":%d,\"dropped\":%I64d,\"batch_size\":%d,"
      "\"terminal_instance_id\":\"%s\","
      "\"ea_instance_id\":\"%s\",\"ea_run_id\":%I64u,\"batch_seq\":%I64d}",
      JsonEscape(_Symbol),
      ticksArr,
      count - 1,
      dropped,
      count,
      JsonEscape(g_terminalInstanceId),
      JsonEscape(g_eaInstanceId),
      g_eaRunId,
      g_batchSeq);

   string msg = MakeMessage("tick_batch", data);
   if(!SendFrame(g_socket, msg))
     {
      // Ring, g_overwrittenFlush, and g_batchSeq are intentionally NOT
      // reset here. The same batch will be re-sent after reconnect.
      PrintFormat("ReadOnlyConnector: tick_batch send failed for %s (seq=%I64d), disconnecting",
                  _Symbol, g_batchSeq);
      DisconnectFromBackend();
      return;
     }

   // --- success path only below this line ---
   g_batchSeq++;
   g_batchesSent++;

   if(dropped > 0)
      PrintFormat("ReadOnlyConnector: batch #%I64d sent %d ticks, %I64d overwritten (total overwritten: %I64d)",
                  g_batchesSent, count, dropped, g_overwrittenTotal);

   g_ringHead         = 0;
   g_ringCount        = 0;
   g_overwrittenFlush = 0;
  }
//+------------------------------------------------------------------+

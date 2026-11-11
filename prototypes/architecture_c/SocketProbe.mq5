#property strict
#property version   "1.02"
#property description "Non-trading socket timing probe. Contains no order or position operations."

enum ENUM_PROBE_MODE
  {
   PROBE_BASELINE=0,
   PROBE_SOCKET_IDLE=1,
   PROBE_SOCKET_IN_TICK=2
  };

input ENUM_PROBE_MODE InpMode=PROBE_BASELINE;
input string InpServerAddress="127.0.0.1";
input uint InpServerPort=47070;
input uint InpTimerPeriodMs=100;
input uint InpConnectTimeoutMs=250;
input uint InpSendTimeoutMs=1;
input uint InpReceiveTimeoutMs=1;
input uint InpReadTimeoutMs=1;
input int InpMaxSamples=100000;

int g_socket=INVALID_HANDLE;
bool g_connected=false;
bool g_init_ok=false;
ulong g_run_id=0;
ulong g_connect_attempts=0;
ulong g_connect_successes=0;
ulong g_connect_failures=0;
ulong g_last_connect_us=0;
ulong g_max_connect_us=0;
ulong g_socket_errors=0;
ulong g_disconnects=0;
int g_sample_count=0;
long g_previous_tick_time_msc=0;

ulong g_elapsed_us[];
ulong g_socket_call_us[];
long g_tick_time_msc[];
long g_tick_delta_msc[];
ulong g_errors_at_sample[];
bool g_connected_at_sample[];

int OnInit()
  {
   g_run_id=0;
   g_init_ok=false;
   g_socket=INVALID_HANDLE;
   g_connected=false;
   g_connect_attempts=0;
   g_connect_successes=0;
   g_connect_failures=0;
   g_last_connect_us=0;
   g_max_connect_us=0;
   g_socket_errors=0;
   g_disconnects=0;
   g_sample_count=0;
   g_previous_tick_time_msc=0;

   if(InpMaxSamples<1 || InpTimerPeriodMs<1 || InpServerPort<1 ||
      InpConnectTimeoutMs<1 || InpSendTimeoutMs<1 ||
      InpReceiveTimeoutMs<1 || InpReadTimeoutMs<1)
      return(INIT_PARAMETERS_INCORRECT);

   if(ArrayResize(g_elapsed_us,InpMaxSamples)<InpMaxSamples ||
      ArrayResize(g_socket_call_us,InpMaxSamples)<InpMaxSamples ||
      ArrayResize(g_tick_time_msc,InpMaxSamples)<InpMaxSamples ||
      ArrayResize(g_tick_delta_msc,InpMaxSamples)<InpMaxSamples ||
      ArrayResize(g_errors_at_sample,InpMaxSamples)<InpMaxSamples ||
      ArrayResize(g_connected_at_sample,InpMaxSamples)<InpMaxSamples)
      return(INIT_FAILED);
   g_run_id=GetTickCount64();

   if(InpMode!=PROBE_BASELINE && !EventSetMillisecondTimer((int)InpTimerPeriodMs))
      return(INIT_FAILED);

   g_init_ok=true;
   PrintFormat("SocketProbe init: run_id=%I64u mode=%d symbol=%s period=%d "
               "server=%s:%u timer_ms=%u connect_timeout_ms=%u "
               "send_timeout_ms=%u recv_timeout_ms=%u read_timeout_ms=%u "
               "max_samples=%d; no trading operations.",
               g_run_id,(int)InpMode,_Symbol,Period(),
               InpServerAddress,InpServerPort,InpTimerPeriodMs,
               InpConnectTimeoutMs,InpSendTimeoutMs,InpReceiveTimeoutMs,
               InpReadTimeoutMs,InpMaxSamples);
   return(INIT_SUCCEEDED);
  }

void CloseSocketAfterDisconnect()
  {
   if(g_socket!=INVALID_HANDLE)
      SocketClose(g_socket);
   g_socket=INVALID_HANDLE;
   g_connected=false;
  }

void OnTimer()
  {
   if(InpMode==PROBE_BASELINE)
      return;
   if(g_connected)
     {
      if(SocketIsConnected(g_socket))
         return;
      g_disconnects++;
      CloseSocketAfterDisconnect();
     }

   ulong started=GetMicrosecondCount();
   g_connect_attempts++;

   int candidate=SocketCreate();
   if(candidate==INVALID_HANDLE)
     {
      g_connect_failures++;
      g_last_connect_us=GetMicrosecondCount()-started;
      if(g_last_connect_us>g_max_connect_us) g_max_connect_us=g_last_connect_us;
      return;
     }

   if(!SocketTimeouts(candidate,InpSendTimeoutMs,InpReceiveTimeoutMs))
     {
      g_connect_failures++;
      SocketClose(candidate);
      g_last_connect_us=GetMicrosecondCount()-started;
      if(g_last_connect_us>g_max_connect_us) g_max_connect_us=g_last_connect_us;
      return;
     }

   if(!SocketConnect(candidate,InpServerAddress,InpServerPort,InpConnectTimeoutMs))
     {
      g_connect_failures++;
      SocketClose(candidate);
      g_last_connect_us=GetMicrosecondCount()-started;
      if(g_last_connect_us>g_max_connect_us) g_max_connect_us=g_last_connect_us;
      return;
     }

   g_socket=candidate;
   g_connected=true;
   g_connect_successes++;
   g_last_connect_us=GetMicrosecondCount()-started;
   if(g_last_connect_us>g_max_connect_us) g_max_connect_us=g_last_connect_us;
  }

void OnTick()
  {
   ulong started=GetMicrosecondCount();
   long tick_msc=0;
   long tick_delta=0;

   MqlTick tick;
   if(SymbolInfoTick(_Symbol,tick))
     {
      tick_msc=(long)tick.time_msc;
      if(g_previous_tick_time_msc>0 && tick_msc>=g_previous_tick_time_msc)
         tick_delta=tick_msc-g_previous_tick_time_msc;
      if(tick_msc>0)
         g_previous_tick_time_msc=tick_msc;
     }

   ulong socket_started=GetMicrosecondCount();
   if(InpMode==PROBE_SOCKET_IN_TICK && g_connected)
     {
      if(!SocketIsConnected(g_socket))
        {
         g_disconnects++;
         CloseSocketAfterDisconnect();
        }
      else
        {
         if(SocketIsWritable(g_socket))
           {
            uchar request[];
            int request_size=StringToCharArray("PING\n",request,0,WHOLE_ARRAY,CP_UTF8);
            if(request_size>0)
              {
               request_size--;
               int sent=SocketSend(g_socket,request,(uint)request_size);
               if(sent<0 || sent!=request_size)
                 {
                  g_socket_errors++;
                  g_disconnects++;
                  CloseSocketAfterDisconnect();
                 }
              }
           }

         if(g_connected)
           {
            uint available=SocketIsReadable(g_socket);
            if(available>0)
              {
               uint read_size=(uint)MathMin((double)available,64.0);
               uchar response[];
               int received=SocketRead(g_socket,response,read_size,InpReadTimeoutMs);
               if(received<0)
                 {
                  g_socket_errors++;
                  g_disconnects++;
                  CloseSocketAfterDisconnect();
                 }
              }
           }
        }
     }
   ulong socket_elapsed=GetMicrosecondCount()-socket_started;
   ulong elapsed=GetMicrosecondCount()-started;

   if(g_sample_count<InpMaxSamples)
     {
      int index=g_sample_count++;
      g_elapsed_us[index]=elapsed;
      g_socket_call_us[index]=socket_elapsed;
      g_tick_time_msc[index]=tick_msc;
      g_tick_delta_msc[index]=tick_delta;
      g_errors_at_sample[index]=g_socket_errors;
      g_connected_at_sample[index]=g_connected;
     }
  }

string ModeToString(ENUM_PROBE_MODE mode)
  {
   switch(mode)
     {
      case PROBE_BASELINE:       return "BASELINE";
      case PROBE_SOCKET_IDLE:    return "SOCKET_IDLE";
      case PROBE_SOCKET_IN_TICK: return "SOCKET_IN_TICK";
      default:                   return "UNKNOWN";
     }
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   if(g_socket!=INVALID_HANDLE)
     {
      SocketClose(g_socket);
      g_socket=INVALID_HANDLE;
     }

   if(!g_init_ok || reason==REASON_INITFAILED)
     {
      PrintFormat("SocketProbe deinit: CSV skipped — initialization incomplete. "
                  "run_id=%I64u deinit_reason=%d",g_run_id,reason);
      return;
     }

   string file_name="architecture_c_socket_probe_"+IntegerToString((long)g_run_id)+".csv";
   int file=FileOpen(file_name,FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI,';');
   if(file==INVALID_HANDLE)
     {
      PrintFormat("SocketProbe deinit: run_id=%I64u file=%s OPEN_FAILED error=%d",
                  g_run_id,file_name,GetLastError());
      return;
     }

   bool ok=true;
   ok=ok && FileWrite(file,"#meta_key","meta_value")>0;
   ok=ok && FileWrite(file,"run_id",IntegerToString((long)g_run_id))>0;
   ok=ok && FileWrite(file,"probe_mode",ModeToString(InpMode))>0;
   ok=ok && FileWrite(file,"symbol",_Symbol)>0;
   ok=ok && FileWrite(file,"period",IntegerToString(Period()))>0;
   ok=ok && FileWrite(file,"server_address",InpServerAddress)>0;
   ok=ok && FileWrite(file,"server_port",IntegerToString(InpServerPort))>0;
   ok=ok && FileWrite(file,"timer_period_ms",IntegerToString(InpTimerPeriodMs))>0;
   ok=ok && FileWrite(file,"connect_timeout_ms",IntegerToString(InpConnectTimeoutMs))>0;
   ok=ok && FileWrite(file,"send_timeout_ms",IntegerToString(InpSendTimeoutMs))>0;
   ok=ok && FileWrite(file,"receive_timeout_ms",IntegerToString(InpReceiveTimeoutMs))>0;
   ok=ok && FileWrite(file,"read_timeout_ms",IntegerToString(InpReadTimeoutMs))>0;
   ok=ok && FileWrite(file,"max_samples",IntegerToString(InpMaxSamples))>0;
   ok=ok && FileWrite(file,"sample_count",IntegerToString(g_sample_count))>0;
   ok=ok && FileWrite(file,"connect_attempts",IntegerToString((long)g_connect_attempts))>0;
   ok=ok && FileWrite(file,"connect_successes",IntegerToString((long)g_connect_successes))>0;
   ok=ok && FileWrite(file,"connect_failures",IntegerToString((long)g_connect_failures))>0;
   ok=ok && FileWrite(file,"disconnects",IntegerToString((long)g_disconnects))>0;
   ok=ok && FileWrite(file,"max_connect_us",IntegerToString((long)g_max_connect_us))>0;
   ok=ok && FileWrite(file,"socket_errors",IntegerToString((long)g_socket_errors))>0;
   ok=ok && FileWrite(file,"deinit_reason",IntegerToString(reason))>0;
   ok=ok && FileWrite(file,"terminal_build",IntegerToString(TerminalInfoInteger(TERMINAL_BUILD)))>0;
   ok=ok && FileWrite(file,"#end_meta","")>0;
   ok=ok && FileWrite(file,"sample","handler_us","socket_calls_us","tick_time_msc",
                      "tick_delta_msc","connected","socket_errors")>0;
   for(int i=0;i<g_sample_count && ok;i++)
      ok=ok && FileWrite(file,i,g_elapsed_us[i],g_socket_call_us[i],g_tick_time_msc[i],
                         g_tick_delta_msc[i],g_connected_at_sample[i],g_errors_at_sample[i])>0;
   if(ok)
      ok=FileWrite(file,"#csv_complete","")>0;
   FileClose(file);

   PrintFormat("SocketProbe deinit: run_id=%I64u mode=%s samples=%d "
               "connect_attempts=%I64u successes=%I64u failures=%I64u "
               "disconnects=%I64u max_connect_us=%I64u socket_errors=%I64u "
               "deinit_reason=%d file=%s",
               g_run_id,ModeToString(InpMode),g_sample_count,
               g_connect_attempts,g_connect_successes,g_connect_failures,
               g_disconnects,g_max_connect_us,g_socket_errors,reason,
               (ok ? file_name : file_name+" WRITE_FAILED"));
  }

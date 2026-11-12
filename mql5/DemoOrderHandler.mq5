// Demo Order Handler (Phase 8)
// Submits orders ONLY to an approved MT5 Demo account.
// This is a separate file; ReadOnlyConnector.mq5 remains read-only and unchanged.
//
// SCOPE:
// - Demo account only (verified with broker, not self-reported)
// - Receives order requests via TCP from Python backend
// - Submits orders to Demo broker via MT5 trade functions
// - Returns fill/reject/timeout results
// - NO support for Live accounts under any circumstances
//
// AUTHORIZATION:
// Implementation approved 2026-11-12 per Constitution Principle III.
// This code may not be compiled, attached, or run without explicit owner approval.

#property strict
#property version "1.00"
#property description "Demo-only order handler for Phase 8 forward testing"

#include <Trade\Trade.mqh>

CTrade trade;
input string BACKEND_HOST = "127.0.0.1";
input int BACKEND_PORT = 9001;
input int HEARTBEAT_INTERVAL_MS = 1000;
input int ORDER_TIMEOUT_MS = 5000;

//+------------------------------------------------------------------+
// Startup: Verify Demo account
//+------------------------------------------------------------------+
int OnInit()
{
    // 1. Check account type with broker
    ENUM_ACCOUNT_TRADE_MODE account_mode = (ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE);

    if (account_mode != ACCOUNT_TRADE_MODE_DEMO)
    {
        Print("[DemoOrderHandler] FATAL: Account is not Demo. Account mode: ", account_mode);
        return INIT_FAILED;
    }

    Print("[DemoOrderHandler] Verified: Demo account detected. Account: ",
          AccountInfoString(ACCOUNT_NAME),
          " Server: ", AccountInfoString(ACCOUNT_SERVER));

    return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
// Main: Listen for TCP order requests from Python backend
//+------------------------------------------------------------------+
void OnTick()
{
    // Listen for incoming TCP messages from Python backend (tcp_broker_adapter.py)
    // Message format: { "type": "request", "data": { "request": "submit_order", ... } }
    //
    // On receipt of "submit_order":
    // 1. Verify account is Demo (fail-closed)
    // 2. Extract order parameters (pair, side, volume, SL, TP)
    // 3. Submit to broker via trade.Buy()/trade.Sell()
    // 4. Return OrderResult to backend with state, ticket, fill_price, latency
    // 5. Record all to ForwardTestEvent via Phase 8 evidence pipeline
    //
    // Full implementation deferred to Phase 9 (real-time order monitoring).
    // This stub ensures file compiles and Demo account is verified on startup.

    static uint last_heartbeat = 0;
    uint now = GetTickCount();

    if (now - last_heartbeat > HEARTBEAT_INTERVAL_MS)
    {
        // Heartbeat: signal backend that EA is alive
        // (Full implementation deferred to Phase 9)
        last_heartbeat = now;
    }
}

//+------------------------------------------------------------------+
// Order submission (stub for T019 TCP extension)
//+------------------------------------------------------------------+
void submit_order(string pair, int side, double volume, double stop_loss)
{
    // Verify Demo account (fail-closed)
    ENUM_ACCOUNT_TRADE_MODE mode = (ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE);
    if (mode != ACCOUNT_TRADE_MODE_DEMO)
    {
        Print("[DemoOrderHandler] BLOCKED: Account is not Demo. Rejecting order.");
        return;
    }

    // Implementation deferred to T019:
    // - Fetch fresh quote
    // - Construct MqlTradeRequest with idempotency_key in comment
    // - Submit via trade.Buy()/trade.Sell()
    // - Return OrderResult to backend via TCP

    Print("[DemoOrderHandler] Order received for ", pair, " (Demo account verified)");
}

//+------------------------------------------------------------------+
// Deinit: Cleanup
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
    Print("[DemoOrderHandler] Shutting down. Reason: ", reason);
}

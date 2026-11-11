# Architecture C Socket Probe

This directory contains a non-trading MQL5 probe and loopback responders (Python and PowerShell).

## Safety

- The EA source contains no order, position, pending-order, account-control, or trade-library calls.
- Both responders bind only to 127.0.0.1 (loopback).
- This tool measures EA timing and socket behavior only. It does not authorize entries.
- Use the existing MetaQuotes Demo terminal only. Do not attach it to a live account.
- Do not change terminal allowlists, firewall rules, or other security settings as part of this source preparation.

## Build

Compile SocketProbe.mq5 with the installed MetaEditor. Keep the generated EX5 with this prototype; do not copy it into the live trading configuration.

## Responders

### Python (WSL or any Python 3.8+ host)

    python3 prototypes/architecture_c/local_socket_probe.py --mode immediate

### PowerShell (Windows host, no admin required)

    powershell -ExecutionPolicy Bypass -File prototypes\architecture_c\LoopbackResponder.ps1
    powershell -ExecutionPolicy Bypass -File prototypes\architecture_c\LoopbackResponder.ps1 -Mode delayed -DelayMs 100
    powershell -ExecutionPolicy Bypass -File prototypes\architecture_c\LoopbackResponder.ps1 -Port 47071 -Mode silent

Both responders support the same five modes: immediate, delayed, silent, slow, and disconnect. Default port is 47070. The PowerShell responder runs on the Windows host where MT5 runs, avoiding the WSL-to-Windows networking dependency.

## CSV format (v1.02+)

The CSV written by the EA on detach contains a metadata block, a sample-data block, and a completion sentinel:

1. **Metadata block** — the first row is the #meta_key;meta_value header, followed by key/value rows including run_id, probe_mode, symbol, period, server address/port, configured timeouts, sample count, connection statistics, deinit reason, and terminal build. The block ends with the #end_meta; row.
2. **Sample data** — the next row is the header: sample, handler_us, socket_calls_us, tick_time_msc, tick_delta_msc, connected, socket_errors. Sample rows follow it.
3. **Completion sentinel** — a final #csv_complete; row is written only after all preceding FileWrite calls report nonzero bytes written.

Parse metadata through the exact #end_meta; sentinel. Parse sample rows after the sample header until the exact #csv_complete; sentinel, and require that sentinel to accept the capture. Do not treat the completion sentinel as a sample row. A missing metadata sentinel, sample header, or completion sentinel means the capture is incomplete or invalid.

The completion sentinel indicates that the EA's FileWrite calls reported success; it does not guarantee durable storage after an abrupt terminal or system failure.

## Manual non-trading measurement sequence

### Prerequisites

1. Open the CFI1 MT5 terminal. Verify the title bar shows **MetaQuotes-Demo** (or another demo account). Do not proceed on a live account.
2. Confirm 127.0.0.1 is in the terminal's allowed-address list (Tools → Options → Expert Advisors). Do not change the allowlist without owner approval.
3. Confirm algorithmic trading is enabled in the same settings panel.

### Step 1 — Baseline (no responder needed)

The Baseline mode does not use sockets. It measures only OnTick handler duration and tick-timestamp deltas. Baseline data cannot establish any socket behavior.

1. Attach SocketProbe to a demo chart (e.g. XAUUSD,M1).
2. Set mode to **PROBE_BASELINE**. Leave server address/port at defaults.
3. Let it run for at least 60 seconds to collect a meaningful sample.
4. Remove the EA from the chart. Check the Experts tab for the deinit summary and the Common Files directory for the CSV.

### Step 2 — Connected idle (PROBE_SOCKET_IDLE)

This mode establishes a TCP connection via OnTimer but does not send or read data in OnTick. It measures whether holding an idle socket affects tick-handler duration.

1. Start the responder on the **Windows host** (the same machine running MT5):

       powershell -ExecutionPolicy Bypass -File prototypes\architecture_c\LoopbackResponder.ps1 -Mode immediate

2. Attach SocketProbe to the same demo chart.
3. Set mode to **PROBE_SOCKET_IDLE**, address 127.0.0.1, port 47070.
4. Verify the responder shows no requests (idle mode sends nothing in OnTick).
5. Let it run for at least 60 seconds. Remove the EA. Check the CSV metadata for connect_successes > 0.
6. Stop the responder with Ctrl+C.

### Step 3 — Socket in tick (PROBE_SOCKET_IN_TICK)

This mode sends PING and reads PONG inside OnTick. Run it with each responder mode to measure the effect of different server behaviors on tick-handler duration.

**Immediate response:**

1. Start: `LoopbackResponder.ps1 -Mode immediate`
2. Attach with PROBE_SOCKET_IN_TICK. Run ≥60s. Remove EA. Save CSV.

**Silent (no response):**

1. Start: `LoopbackResponder.ps1 -Mode silent`
2. Attach with PROBE_SOCKET_IN_TICK. Run ≥60s. Remove EA. Save CSV.
3. Expect SocketIsReadable to return 0 and the read path to be skipped.

**Delayed response:**

1. Start: `LoopbackResponder.ps1 -Mode delayed -DelayMs 50`
2. Attach with PROBE_SOCKET_IN_TICK. Run ≥60s. Remove EA. Save CSV.

**Slow/trickled response:**

1. Start: `LoopbackResponder.ps1 -Mode slow -DelayMs 10`
2. Attach with PROBE_SOCKET_IN_TICK. Run ≥60s. Remove EA. Save CSV.

**Disconnect on first message:**

1. Start: `LoopbackResponder.ps1 -Mode disconnect`
2. Attach with PROBE_SOCKET_IN_TICK. Run ≥60s. Remove EA. Save CSV.
3. Expect reconnect attempts in the deinit summary and rising disconnect counts in the CSV.

### After each run

- Check the Experts tab for the one-line init and one-line deinit log entries.
- Compare the CSV metadata block's run_id, mode, and connection statistics to identify each capture.
- Do not submit demo orders, use the Strategy Tester, or change terminal settings between runs.

## Output

On EA removal, it writes a CSV to the MetaTrader Common Files directory. It records per-tick handler duration, socket-call duration, the broker tick timestamp and observed tick-time delta, connection state, and socket errors. These deltas cannot by themselves distinguish a missed event from a market-data gap. Report sample counts and distributions; do not invent acceptance thresholds.

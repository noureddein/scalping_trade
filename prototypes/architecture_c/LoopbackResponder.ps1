<#
.SYNOPSIS
    Loopback-only TCP responder for the non-trading Architecture C socket probe.
.DESCRIPTION
    Binds strictly to 127.0.0.1 (IPAddress.Loopback). Runs in the foreground;
    stop with Ctrl+C. Does not install services, change firewall rules, or bind
    to wildcard/non-loopback addresses.

    Modes:
      immediate  - reply PONG\n to every PING\n immediately (default)
      delayed    - reply after -DelayMs milliseconds
      silent     - accept connections, read data, never reply
      slow       - trickle PONG\n one byte at a time with -DelayMs between bytes
      disconnect - accept connection, read first line, then close
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File LoopbackResponder.ps1
    powershell -ExecutionPolicy Bypass -File LoopbackResponder.ps1 -Mode delayed -DelayMs 100
    powershell -ExecutionPolicy Bypass -File LoopbackResponder.ps1 -Port 47071 -Mode silent
#>
param(
    [int]$Port = 47070,
    [ValidateSet("immediate","delayed","silent","slow","disconnect")]
    [string]$Mode = "immediate",
    [int]$DelayMs = 50
)

if ($Port -lt 1 -or $Port -gt 65535) {
    Write-Error "Port must be between 1 and 65535."
    exit 1
}
if ($DelayMs -lt 0) {
    Write-Error "DelayMs must be non-negative."
    exit 1
}

$listener = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback, $Port
)
$listener.Start()
Write-Host "Loopback-only probe responder listening on 127.0.0.1:$Port; mode=$Mode; Ctrl+C to stop."

$requestCount = 0

try {
    while ($true) {
        $client = $listener.AcceptTcpClient()
        $stream = $client.GetStream()
        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8)

        try {
            while ($client.Connected -and -not $reader.EndOfStream) {
                $line = $reader.ReadLine()
                if ($null -eq $line) { break }
                $requestCount++
                Write-Host "request=$requestCount bytes=$($line.Length) mode=$Mode"

                switch ($Mode) {
                    "disconnect" {
                        $client.Close()
                        break
                    }
                    "silent" {
                        # read but never reply
                    }
                    "delayed" {
                        Start-Sleep -Milliseconds $DelayMs
                        $bytes = [System.Text.Encoding]::UTF8.GetBytes("PONG`n")
                        $stream.Write($bytes, 0, $bytes.Length)
                        $stream.Flush()
                    }
                    "slow" {
                        foreach ($b in [System.Text.Encoding]::UTF8.GetBytes("PONG`n")) {
                            $stream.WriteByte($b)
                            $stream.Flush()
                            Start-Sleep -Milliseconds $DelayMs
                        }
                    }
                    default {
                        # immediate
                        $bytes = [System.Text.Encoding]::UTF8.GetBytes("PONG`n")
                        $stream.Write($bytes, 0, $bytes.Length)
                        $stream.Flush()
                    }
                }
            }
        } catch {
            # client disconnected or stream error — continue listening
        } finally {
            $reader.Dispose()
            $stream.Dispose()
            $client.Dispose()
        }
    }
} finally {
    $listener.Stop()
    Write-Host "`nStopped. Total requests handled: $requestCount"
}

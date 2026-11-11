#!/usr/bin/env python3
"""Loopback-only responder for the non-trading Architecture C socket probe."""

from __future__ import annotations

import argparse
import socketserver
import sys
import time


class ProbeHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        server = self.server
        while True:
            line = self.rfile.readline(256)
            if not line:
                return
            server.requests += 1
            print("request={} bytes={} mode={}".format(
                server.requests, len(line), server.mode), flush=True)

            if server.mode == "disconnect":
                return
            if server.mode == "silent":
                continue
            if server.mode == "delayed":
                time.sleep(server.delay_ms / 1000)
                self.wfile.write(b"PONG\n")
                self.wfile.flush()
                continue
            if server.mode == "slow":
                for byte in b"PONG\n":
                    self.wfile.write(bytes((byte,)))
                    self.wfile.flush()
                    time.sleep(server.delay_ms / 1000)
                continue

            self.wfile.write(b"PONG\n")
            self.wfile.flush()


class ProbeServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, port: int, mode: str, delay_ms: int) -> None:
        self.mode = mode
        self.delay_ms = delay_ms
        self.requests = 0
        super().__init__(("127.0.0.1", port), ProbeHandler)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=47070)
    parser.add_argument(
        "--mode",
        choices=("immediate", "delayed", "silent", "slow", "disconnect"),
        default="immediate",
    )
    parser.add_argument("--delay-ms", type=int, default=50)
    args = parser.parse_args()

    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.delay_ms < 0:
        parser.error("--delay-ms must be non-negative")

    server = ProbeServer(args.port, args.mode, args.delay_ms)
    host, port = server.server_address
    print(
        "Loopback-only probe server listening on {}:{}; mode={}; Ctrl+C to stop."
        .format(host, port, args.mode),
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        print("\nStopping loopback probe server.", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

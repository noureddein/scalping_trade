# Forex Scalping System

Standalone Forex scalping project. The canonical specification, phase status, approved decisions, and required test backlog are maintained in [FOREX_SCALPING_MASTER_PLAN.md](FOREX_SCALPING_MASTER_PLAN.md).

## Current working environment

- Python 3.12 backend runs in WSL.
- Native MetaTrader 5 runs on Windows.
- The local connector uses TCP loopback (`127.0.0.1`).
- PostgreSQL is the planned durable state store; Redis is not used initially.

The current MT5 connector is read-only. The project is not approved for broker order submission or live trading.

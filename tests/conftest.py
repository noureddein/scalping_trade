import os

os.environ.setdefault("SCALPING_DATABASE_URL", "postgresql://postgres:00100@localhost:5432/forex_scalping_test")
os.environ.setdefault("SCALPING_DISPOSABLE_DATABASE_URL", "postgresql://postgres:00100@localhost:5432/forex_scalping_disposable_test")

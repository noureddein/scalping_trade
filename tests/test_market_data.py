"""Tests for market_data module — tick validation, normalization, feed health."""
from decimal import Decimal
from datetime import datetime, timezone

from scalping_core.broker_types import Tick
from scalping_core.fake_broker import make_contract, make_tick
from scalping_core.market_data import (
    PairFeed,
    TickRejectReason,
    pip_size,
    spread_in_pips,
    MarketDataProcessor,
    MarketStatus,
)
from scalping_core.broker_types import TickActivityLevel, TickValidationStatus


def _feed() -> PairFeed:
    return PairFeed(make_contract("EURUSD"), max_tick_age_s=10.0)


def test_pip_size_5_digit():
    c = make_contract("EURUSD", digits=5, point="0.00001")
    assert pip_size(c) == Decimal("0.0001")


def test_pip_size_3_digit():
    c = make_contract("USDJPY", digits=3, point="0.001")
    assert pip_size(c) == Decimal("0.01")


def test_pip_size_4_digit():
    c = make_contract("EURUSD", digits=4, point="0.0001")
    assert pip_size(c) == Decimal("0.0001")


def test_spread_in_pips_basic():
    c = make_contract("EURUSD", digits=5, point="0.00001")
    t = make_tick(bid="1.10000", ask="1.10020")
    assert spread_in_pips(t, c) == Decimal("2.0")


def test_spread_in_pips_jpy():
    c = make_contract("USDJPY", digits=3, point="0.001")
    t = make_tick(broker_symbol="USDJPY", bid="150.100", ask="150.120")
    assert spread_in_pips(t, c) == Decimal("2.0")


def test_accept_valid_tick():
    feed = _feed()
    result = feed.process_tick(make_tick(recv_time_mono=1.0))
    assert result.accepted
    assert result.spread_pips is not None
    assert feed.accept_count == 1


def test_reject_zero_bid():
    feed = _feed()
    result = feed.process_tick(make_tick(bid="0", recv_time_mono=1.0))
    assert not result.accepted
    assert result.reject_reason == TickRejectReason.INVALID_BID


def test_reject_negative_ask():
    feed = _feed()
    result = feed.process_tick(make_tick(ask="-1.0", recv_time_mono=1.0))
    assert not result.accepted
    assert result.reject_reason == TickRejectReason.INVALID_ASK


def test_reject_inverted_spread():
    feed = _feed()
    result = feed.process_tick(make_tick(bid="1.10020", ask="1.10000", recv_time_mono=1.0))
    assert not result.accepted
    assert result.reject_reason == TickRejectReason.INVERTED_SPREAD


def test_reject_duplicate():
    feed = _feed()
    t = make_tick(recv_time_mono=1.0)
    feed.process_tick(t)
    result = feed.process_tick(make_tick(recv_time_mono=2.0))
    assert not result.accepted
    assert result.reject_reason == TickRejectReason.DUPLICATE


def test_reject_out_of_order():
    feed = _feed()
    feed.process_tick(make_tick(server_time_ms=2000, recv_time_mono=1.0))
    result = feed.process_tick(make_tick(server_time_ms=1000, recv_time_mono=2.0))
    assert not result.accepted
    assert result.reject_reason == TickRejectReason.OUT_OF_ORDER


def test_is_fresh():
    feed = _feed()
    assert not feed.is_fresh(now_mono=0.0)
    feed.process_tick(make_tick(recv_time_mono=1.0))
    assert feed.is_fresh(now_mono=2.0)
    assert not feed.is_fresh(now_mono=100.0)


def test_pair_feed_fails_closed_without_owner_approved_freshness_threshold():
    feed = PairFeed(make_contract("EURUSD"))
    feed.process_tick(make_tick(recv_time_mono=1.0))
    assert not feed.is_fresh(now_mono=1.0)


def _phase3_tick(ts_ms=1_700_000_000_000, receipt=10.0, bid="1.1", ask="1.1001"):
    return Tick(broker_symbol="EURUSD", pair="EURUSD", bid=Decimal(bid),
                ask=Decimal(ask), server_time_ms=ts_ms, recv_time_mono=receipt,
                local_receipt_time=receipt)


def test_phase3_processor_rejects_crossed_duplicate_reordered_and_stale():
    processor = MarketDataProcessor()
    processor.register_pair("EURUSD", "EURUSD", staleness_threshold_s=2)
    assert processor.process_tick(_phase3_tick(), now_mono=10).accepted
    assert processor.process_tick(_phase3_tick(ts_ms=1_700_000_000_001, ask="1.0"), now_mono=10).reject_reason == TickRejectReason.CROSSED
    assert processor.process_tick(_phase3_tick(), now_mono=10).reject_reason == TickRejectReason.DUPLICATE
    assert processor.process_tick(_phase3_tick(ts_ms=1_699_999_999_999), now_mono=10).reject_reason == TickRejectReason.REORDERED
    assert processor.process_tick(_phase3_tick(ts_ms=1_700_000_000_002, receipt=1), now_mono=10).reject_reason == TickRejectReason.STALE


def test_missing_tick_fields_are_malformed_and_only_valid_ticks_are_delivered():
    from dataclasses import replace
    delivered = []
    processor = MarketDataProcessor(delivered.append)
    processor.register_pair("EURUSD", "EURUSD", staleness_threshold_s=2)
    malformed = replace(_phase3_tick(), broker_timestamp=None, server_time_ms=0)
    assert processor.process_tick(malformed, now_mono=10).tick.validation_status is TickValidationStatus.MALFORMED
    invalid = _phase3_tick(ts_ms=1_700_000_000_001, ask="1.0")
    valid = _phase3_tick(ts_ms=1_700_000_000_002)
    result = processor.process_batch("EURUSD", 0, 1, [invalid, valid], now_mono=10)
    assert len(result.accepted_ticks) == len(delivered) == 1
    assert result.accepted_ticks[0].validation_status is TickValidationStatus.VALID
    assert result.rejected_ticks[0].tick.validation_status is TickValidationStatus.CROSSED


def test_duplicate_ticks_inside_one_batch_are_discarded():
    processor = MarketDataProcessor()
    processor.register_pair("EURUSD", "EURUSD", staleness_threshold_s=5)
    result = processor.process_batch("EURUSD", 0, 1,
                                     [_phase3_tick(), _phase3_tick()], now_mono=10)
    assert len(result.accepted_ticks) == 1
    assert len(result.rejected_ticks) == 1
    assert result.rejected_ticks[0].tick.validation_status is TickValidationStatus.DUPLICATE


def test_phase3_processor_fail_closed_without_staleness_config_and_for_unknown_pair():
    processor = MarketDataProcessor()
    state = processor.register_pair("EURUSD", "EURUSD")
    assert processor.process_tick(_phase3_tick(), now_mono=10).accepted
    assert processor.check_staleness("EURUSD", now_mono=100)
    assert state.is_entry_blocked
    assert processor.process_tick(_phase3_tick(), pair="GBPUSD", now_mono=10).reject_reason == TickRejectReason.MALFORMED


def test_phase3_batch_gaps_boundaries_and_duplicates_do_not_synthesize_ticks():
    delivered = []
    boundaries = []
    processor = MarketDataProcessor(delivered.append, boundaries.append)
    processor.register_pair("EURUSD", "EURUSD", staleness_threshold_s=5,
                            normal_min_ticks_per_second=0.1, low_min_ticks_per_second=0.01,
                            none_after_s=30, baseline_window_s=10)
    first = processor.process_batch("EURUSD", 1, 1, [_phase3_tick()], now_mono=10)
    gap = processor.process_batch("EURUSD", 4, 1, [_phase3_tick(ts_ms=1_700_000_000_001)], now_mono=11)
    dup = processor.process_batch("EURUSD", 4, 1, [_phase3_tick(ts_ms=1_700_000_000_002)], now_mono=12)
    restart = processor.process_batch("EURUSD", 0, 2, [_phase3_tick(ts_ms=1_700_000_000_003)], now_mono=13)
    assert len(first.accepted_ticks) == len(gap.accepted_ticks) == len(restart.accepted_ticks) == 1
    assert gap.batch.has_gap and restart.batch.is_run_boundary
    assert dup.deduplicated_count == 1
    assert len(delivered) == 3
    assert boundaries == ["EURUSD"]
    assert processor.degraded_intervals == (("EURUSD", 2, 3),)


def test_single_tick_processing_under_100ms_synthetic_benchmark():
    import time
    processor = MarketDataProcessor()
    processor.register_pair("EURUSD", "EURUSD", staleness_threshold_s=2)
    start = time.perf_counter()
    processor.process_tick(_phase3_tick(), now_mono=10)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.1


def test_activity_levels_and_market_closed_status_block_entries():
    processor = MarketDataProcessor()
    state = processor.register_pair(
        "EURUSD", "EURUSD", staleness_threshold_s=60,
        normal_min_ticks_per_second=0.3, low_min_ticks_per_second=0.05,
        none_after_s=5, baseline_window_s=10,
    )
    processor.process_tick(_phase3_tick(receipt=10), now_mono=10)
    assert state.tick_activity_level is TickActivityLevel.LOW
    assert state.is_entry_blocked
    processor.process_tick(_phase3_tick(ts_ms=1_700_000_000_001, receipt=11), now_mono=11)
    assert state.tick_activity_level is TickActivityLevel.LOW
    assert not processor.check_staleness("EURUSD", now_mono=20)
    assert state.tick_activity_level is TickActivityLevel.NONE
    processor.update_market_status(MarketStatus("EURUSD", False, datetime.now(timezone.utc)))
    assert state.is_market_open is False
    assert state.is_entry_blocked


def test_reopening_after_none_is_unstable_until_stability_is_acknowledged():
    processor = MarketDataProcessor()
    state = processor.register_pair("EURUSD", "EURUSD", staleness_threshold_s=60,
                                    normal_min_ticks_per_second=0.1,
                                    low_min_ticks_per_second=0.01,
                                    none_after_s=5, baseline_window_s=10)
    processor.process_tick(_phase3_tick(), now_mono=10)
    processor.acknowledge_stability("EURUSD")
    processor.check_staleness("EURUSD", now_mono=20)
    processor.process_tick(_phase3_tick(ts_ms=1_700_000_000_001, receipt=21), now_mono=21)
    assert state.reopened_unstable
    assert state.is_entry_blocked
    processor.acknowledge_stability("EURUSD")
    assert not state.reopened_unstable


def test_dropped_ring_ticks_mark_degraded_interval_without_synthetic_ticks():
    delivered = []
    processor = MarketDataProcessor(delivered.append)
    processor.register_pair("EURUSD", "EURUSD", staleness_threshold_s=5)
    result = processor.process_batch("EURUSD", 2, 1, [_phase3_tick()], now_mono=10, dropped_count=3)
    assert result.batch.has_gap
    assert processor.degraded_intervals == (("EURUSD", 2, 2),)
    assert len(delivered) == 1

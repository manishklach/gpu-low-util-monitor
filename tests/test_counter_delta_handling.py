from gpu_low_util_monitor.models import DeviceCapabilities, DeviceIdentity, DeviceSample
from gpu_low_util_monitor.rolling_window import RollingWindow


def sample(ts_ns: int, counter_ns: int | None) -> DeviceSample:
    return DeviceSample(
        identity=DeviceIdentity(index=0, uuid="GPU-0", name="GPU"),
        monotonic_ns=ts_ns,
        wall_time_iso="2026-04-03T00:00:00+00:00",
        gpu_util_pct=0.0,
        sm_clock_mhz=0.0,
        mem_clock_mhz=0.0,
        power_w=0.0,
        power_cap_w=700.0,
        total_energy_joules=float(ts_ns / 1_000_000_000),
        idle_reason_active=True,
        thermal_limit_active=False,
        power_limit_active=False,
        low_util_counter_ns=counter_ns,
        capabilities=DeviceCapabilities(low_util_counter=counter_ns is not None),
    )


def test_counter_reset_is_treated_as_zero_delta() -> None:
    window = RollingWindow(max_window_seconds=300)
    window.append(sample(0, 0))
    window.append(sample(10_000_000_000, 8_000_000_000))
    window.append(sample(20_000_000_000, 1_000_000_000))

    summary = window.summarize(window_seconds=20)

    assert summary.low_util_pct_window == 40.0


def test_missing_counter_yields_null_low_util_pct() -> None:
    window = RollingWindow(max_window_seconds=300)
    window.append(sample(0, None))
    window.append(sample(10_000_000_000, None))

    summary = window.summarize(window_seconds=10)

    assert summary.low_util_pct_window is None


def test_negative_counter_delta_contributes_zero() -> None:
    assert RollingWindow._safe_counter_delta(9_000_000_000, 4_000_000_000, 10_000_000_000) == 0


def test_zero_or_negative_elapsed_counter_delta_contributes_zero() -> None:
    assert RollingWindow._safe_counter_delta(1_000_000_000, 2_000_000_000, 0) == 0
    assert RollingWindow._safe_counter_delta(1_000_000_000, 2_000_000_000, -1) == 0


def test_counter_delta_is_clamped_to_elapsed_time() -> None:
    assert RollingWindow._safe_counter_delta(0, 50_000_000_000, 10_000_000_000) == 10_000_000_000


def test_non_monotonic_timestamp_resets_window_baseline() -> None:
    window = RollingWindow(max_window_seconds=300)
    window.append(sample(10_000_000_000, 1_000_000_000))
    window.append(sample(20_000_000_000, 9_000_000_000))
    window.append(sample(15_000_000_000, 2_000_000_000))
    window.append(sample(25_000_000_000, 5_000_000_000))

    summary = window.summarize(window_seconds=300)

    assert summary.low_util_pct_window == 30.0

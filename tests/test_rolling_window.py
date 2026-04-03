from gpu_low_util_monitor.models import DeviceCapabilities, DeviceIdentity, DeviceSample
from gpu_low_util_monitor.rolling_window import RollingWindow


def make_sample(
    ts_ns: int,
    gpu_util: float,
    low_util_counter_ns: int,
    idle: bool | None = False,
) -> DeviceSample:
    return DeviceSample(
        identity=DeviceIdentity(index=0, uuid="GPU-0", name="GPU"),
        monotonic_ns=ts_ns,
        wall_time_iso="2026-04-03T00:00:00+00:00",
        gpu_util_pct=gpu_util,
        sm_clock_mhz=1000.0,
        mem_clock_mhz=1500.0,
        power_w=200.0,
        idle_reason_active=idle,
        low_util_counter_ns=low_util_counter_ns,
        capabilities=DeviceCapabilities(),
    )


def test_time_weighted_rolling_window_with_uneven_intervals() -> None:
    window = RollingWindow(max_window_seconds=600)
    window.append(make_sample(0, 0.0, 0))
    window.append(make_sample(10_000_000_000, 20.0, 7_000_000_000))
    window.append(make_sample(40_000_000_000, 80.0, 10_000_000_000))

    summary = window.summarize(window_seconds=40)

    assert summary.sample_count == 3
    assert summary.low_util_pct_window == 25.0
    assert summary.avg_gpu_util_window == 65.0
    assert summary.avg_sm_clock_mhz_window == 1000.0


def test_window_eviction_preserves_recent_samples() -> None:
    window = RollingWindow(max_window_seconds=20)
    for second in range(0, 31, 10):
        window.append(make_sample(second * 1_000_000_000, 50.0, second * 500_000_000))

    summary = window.summarize(window_seconds=10)

    assert summary.sample_count == 2
    assert summary.avg_gpu_util_window == 50.0

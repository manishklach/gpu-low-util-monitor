from gpu_low_util_monitor.models import DeviceCapabilities, DeviceIdentity, DeviceSample
from gpu_low_util_monitor.rolling_window import RollingWindow


def _sample(ts_ns: int, counter_ns: int, idle: bool) -> DeviceSample:
    return DeviceSample(
        identity=DeviceIdentity(index=0, uuid="GPU-0", name="GPU"),
        monotonic_ns=ts_ns,
        wall_time_iso="2026-04-03T00:00:00+00:00",
        gpu_util_pct=25.0,
        sm_clock_mhz=1000.0,
        mem_clock_mhz=1500.0,
        power_w=200.0,
        power_cap_w=700.0,
        total_energy_joules=float(ts_ns / 1_000_000_000) * 200.0,
        idle_reason_active=idle,
        low_util_counter_ns=counter_ns,
        capabilities=DeviceCapabilities(),
    )


def test_configurable_short_and_long_windows_diverge_as_expected() -> None:
    window = RollingWindow(max_window_seconds=1000)
    window.append(_sample(0, 0, False))
    window.append(_sample(100_000_000_000, 100_000_000_000, True))
    window.append(_sample(150_000_000_000, 100_000_000_000, False))

    short_summary = window.summarize(window_seconds=60)
    long_summary = window.summarize(window_seconds=180)

    assert short_summary.low_util_pct_window == 16.667
    assert long_summary.low_util_pct_window == 66.667
    assert short_summary.idle_reason_pct_window == 50.0
    assert long_summary.idle_reason_pct_window == 33.333

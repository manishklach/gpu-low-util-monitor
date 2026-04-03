from gpu_low_util_monitor.models import DeviceCapabilities, DeviceIdentity, DeviceSample
from gpu_low_util_monitor.rolling_window import RollingWindow


def _sample(ts_ns: int, thermal: bool | None, power_limit: bool | None) -> DeviceSample:
    return DeviceSample(
        identity=DeviceIdentity(index=0, uuid="GPU-0", name="GPU"),
        monotonic_ns=ts_ns,
        wall_time_iso="2026-04-03T00:00:00+00:00",
        gpu_util_pct=80.0,
        sm_clock_mhz=1200.0,
        mem_clock_mhz=1500.0,
        power_w=500.0,
        power_cap_w=700.0,
        total_energy_joules=float(ts_ns / 1_000_000_000) * 500.0,
        idle_reason_active=False,
        thermal_limit_active=thermal,
        power_limit_active=power_limit,
        low_util_counter_ns=0,
        capabilities=DeviceCapabilities(
            thermal_limit=thermal is not None,
            power_limit=power_limit is not None,
        ),
    )


def test_thermal_and_power_limit_percentages_are_sampled_over_window() -> None:
    window = RollingWindow(max_window_seconds=300)
    window.append(_sample(0, False, True))
    window.append(_sample(1_000_000_000, True, True))
    window.append(_sample(2_000_000_000, True, False))
    window.append(_sample(3_000_000_000, False, False))

    summary = window.summarize(window_seconds=10)

    assert summary.thermal_limit_pct_window == 50.0
    assert summary.power_limit_pct_window == 50.0


def test_missing_thermal_limit_signal_yields_null_percentages() -> None:
    window = RollingWindow(max_window_seconds=300)
    window.append(_sample(0, None, None))
    window.append(_sample(1_000_000_000, None, None))

    summary = window.summarize(window_seconds=10)

    assert summary.thermal_limit_pct_window is None
    assert summary.power_limit_pct_window is None

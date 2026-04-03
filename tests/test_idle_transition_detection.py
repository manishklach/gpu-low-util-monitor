from gpu_low_util_monitor.models import DeviceCapabilities, DeviceIdentity, DeviceSample
from gpu_low_util_monitor.rolling_window import RollingWindow


def sample(ts_ns: int, idle: bool | None) -> DeviceSample:
    return DeviceSample(
        identity=DeviceIdentity(index=0, uuid="GPU-0", name="GPU"),
        monotonic_ns=ts_ns,
        wall_time_iso="2026-04-03T00:00:00+00:00",
        gpu_util_pct=10.0,
        sm_clock_mhz=900.0,
        mem_clock_mhz=1500.0,
        power_w=100.0,
        power_cap_w=700.0,
        total_energy_joules=float(ts_ns / 1_000_000_000) * 100.0,
        idle_reason_active=idle,
        low_util_counter_ns=0,
        capabilities=DeviceCapabilities(),
    )


def test_idle_transition_counts_false_to_true_only() -> None:
    window = RollingWindow(max_window_seconds=300)
    window.append(sample(0, False))
    window.append(sample(1_000_000_000, False))
    window.append(sample(2_000_000_000, True))
    window.append(sample(3_000_000_000, True))
    window.append(sample(4_000_000_000, False))
    window.append(sample(5_000_000_000, True))

    summary = window.summarize(window_seconds=10)

    assert summary.idle_entries_window == 2
    assert summary.idle_reason_pct_window == 50.0

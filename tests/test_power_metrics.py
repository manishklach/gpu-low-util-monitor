from pathlib import Path

from gpu_low_util_monitor.models import DeviceCapabilities, DeviceIdentity, DeviceSample
from gpu_low_util_monitor.power import PowerCalibration, compute_power_activity_pct, load_power_calibration_store
from gpu_low_util_monitor.reporting import HeatmapJsonWriter
from gpu_low_util_monitor.rolling_window import RollingWindow


def _sample(
    ts_ns: int,
    power_w: float,
    total_energy_joules: float,
    power_cap_w: float = 700.0,
) -> DeviceSample:
    return DeviceSample(
        identity=DeviceIdentity(index=0, uuid="GPU-0", name="NVIDIA H100 80GB HBM3"),
        monotonic_ns=ts_ns,
        wall_time_iso="2026-04-03T00:00:00+00:00",
        gpu_util_pct=50.0,
        sm_clock_mhz=1200.0,
        mem_clock_mhz=1500.0,
        power_w=power_w,
        power_cap_w=power_cap_w,
        total_energy_joules=total_energy_joules,
        idle_reason_active=False,
        low_util_counter_ns=0,
        capabilities=DeviceCapabilities(),
    )


def test_power_summary_and_energy_delta_math() -> None:
    window = RollingWindow(max_window_seconds=300)
    window.append(_sample(0, 100.0, 0.0))
    window.append(_sample(10_000_000_000, 200.0, 1_000.0))
    window.append(_sample(20_000_000_000, 300.0, 4_000.0))

    summary = window.summarize(window_seconds=20)

    assert summary.avg_power_w_window == 250.0
    assert summary.power_pct_of_cap_window == 35.714
    assert summary.energy_joules_window == 4000.0


def test_power_activity_pct_respects_calibration() -> None:
    calibration = PowerCalibration(idle_baseline_w=100.0, busy_reference_w=500.0)
    assert compute_power_activity_pct(300.0, calibration) == 50.0
    assert compute_power_activity_pct(700.0, calibration) == 100.0
    assert compute_power_activity_pct(50.0, calibration) == 0.0


def test_invalid_or_missing_calibration_yields_null_activity() -> None:
    invalid = PowerCalibration(idle_baseline_w=400.0, busy_reference_w=300.0)
    assert compute_power_activity_pct(200.0, invalid) is None
    assert compute_power_activity_pct(200.0, None) is None


def test_calibration_file_and_overrides(tmp_path: Path) -> None:
    path = tmp_path / "power_calibration.json"
    path.write_text(
        """
        {
          "default": {"idle_baseline_w": 80.0, "busy_reference_w": 700.0},
          "by_uuid": {"GPU-0": {"idle_baseline_w": 90.0, "busy_reference_w": 650.0}},
          "by_name_prefix": {"NVIDIA H200": {"idle_baseline_w": 100.0, "busy_reference_w": 680.0}}
        }
        """,
        encoding="utf-8",
    )

    store = load_power_calibration_store(path, cli_idle_baseline_w=None, cli_busy_reference_w=None)
    calibration = store.resolve(DeviceIdentity(index=0, uuid="GPU-0", name="NVIDIA H100 80GB HBM3"))

    assert calibration is not None
    assert calibration.idle_baseline_w == 90.0


def test_heatmap_writer_format(tmp_path: Path) -> None:
    from gpu_low_util_monitor.models import SampleReport, WindowSummary

    report = SampleReport(
        sample=_sample(0, 220.0, 220.0),
        short_summary=WindowSummary(
            window_seconds=60,
            sample_count=2,
            low_util_pct_window=40.0,
            idle_reason_pct_window=10.0,
            idle_entries_window=1,
            avg_gpu_util_window=60.0,
            avg_sm_clock_mhz_window=1200.0,
            avg_mem_clock_mhz_window=1500.0,
            avg_power_w_window=210.0,
            power_pct_of_cap_window=30.0,
            energy_joules_window=210.0,
            power_activity_pct_window=25.0,
        ),
        long_summary=WindowSummary(
            window_seconds=1200,
            sample_count=10,
            low_util_pct_window=55.0,
            idle_reason_pct_window=15.0,
            idle_entries_window=3,
            avg_gpu_util_window=50.0,
            avg_sm_clock_mhz_window=1100.0,
            avg_mem_clock_mhz_window=1500.0,
            avg_power_w_window=205.0,
            power_pct_of_cap_window=29.286,
            energy_joules_window=4100.0,
            power_activity_pct_window=22.5,
        ),
    )

    writer = HeatmapJsonWriter(tmp_path, group_by="gpu")
    writer.write_reports([report])

    text = (tmp_path / "gpu_heatmap.jsonl").read_text(encoding="utf-8")
    assert '"current_power_w":220.0' in text
    assert '"power_activity_pct_long":22.5' in text

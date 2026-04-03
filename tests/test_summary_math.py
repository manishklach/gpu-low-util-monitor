from pathlib import Path

from gpu_low_util_monitor.collector import CollectorConfig, GPUCollector
from gpu_low_util_monitor.nvml_adapter import FakeNVMLBackend
from gpu_low_util_monitor.reporting import ConsoleReporter, CsvSummaryWriter, JsonlWriter


def test_multi_gpu_collection_and_formatting(tmp_path: Path) -> None:
    ticks = iter([0, 1_000_000_000])
    collector = GPUCollector(
        FakeNVMLBackend(scenarios=["fully-idle", "steady-busy"]),
        CollectorConfig(interval_seconds=1.0, window_short_seconds=60, window_long_seconds=1200),
        monotonic_ns_fn=lambda: next(ticks),
    )
    collector.initialize()
    collector.poll_once()
    reports = collector.poll_once()

    assert len(reports) == 2
    idle_gpu = next(report for report in reports if report.sample.identity.index == 0)
    busy_gpu = next(report for report in reports if report.sample.identity.index == 1)

    assert idle_gpu.long_summary.low_util_pct_window == 100.0
    assert busy_gpu.long_summary.low_util_pct_window == 2.0

    jsonl = JsonlWriter(tmp_path)
    csv = CsvSummaryWriter(tmp_path)
    jsonl.write_reports(reports)
    csv.write_reports(reports)

    jsonl_text = (tmp_path / "gpu_samples.jsonl").read_text(encoding="utf-8")
    csv_text = (tmp_path / "gpu_summary.csv").read_text(encoding="utf-8")

    assert '"gpu_index":0' in jsonl_text
    assert '"summary_short"' in jsonl_text
    assert '"summary_long"' in jsonl_text
    assert '"summary_60s"' in jsonl_text
    assert '"availability"' in jsonl_text
    assert "window_role" in csv_text
    assert "window_seconds" in csv_text
    assert "low_util_pct_window" in csv_text
    assert ",short,60," in csv_text
    assert ",long,1200," in csv_text


def test_console_reporter_labels_configured_windows() -> None:
    ticks = iter([0, 1_000_000_000])
    collector = GPUCollector(
        FakeNVMLBackend(scenarios=["fully-idle"]),
        CollectorConfig(interval_seconds=1.0, window_short_seconds=75, window_long_seconds=900),
        monotonic_ns_fn=lambda: next(ticks),
    )
    collector.initialize()
    collector.poll_once()
    reports = collector.poll_once()

    rendered = ConsoleReporter().render(reports)

    assert "low_util_short(75s)" in rendered
    assert "low_util_long(15m)" in rendered

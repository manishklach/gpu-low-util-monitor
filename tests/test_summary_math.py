from pathlib import Path

from gpu_low_util_monitor.collector import CollectorConfig, GPUCollector
from gpu_low_util_monitor.nvml_adapter import FakeNVMLBackend
from gpu_low_util_monitor.reporting import CsvSummaryWriter, JsonlWriter


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
    assert "window_seconds" in csv_text

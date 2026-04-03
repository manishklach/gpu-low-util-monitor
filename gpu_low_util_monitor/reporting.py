"""Output sinks for JSONL, CSV, console, and Prometheus."""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from gpu_low_util_monitor.models import SampleReport
from gpu_low_util_monitor.util import dumps_compact_json, ensure_directory

LOGGER = logging.getLogger(__name__)


class JsonlWriter:
    """Append one JSONL row per GPU sample."""

    def __init__(self, out_dir: Path) -> None:
        self._path = ensure_directory(out_dir) / "gpu_samples.jsonl"

    def write_reports(self, reports: list[SampleReport]) -> None:
        """Append reports to the JSONL file."""
        with self._path.open("a", encoding="utf-8") as handle:
            for report in reports:
                handle.write(dumps_compact_json(report.to_json_dict()) + "\n")


class CsvSummaryWriter:
    """Write rolling summary snapshots in CSV format."""

    FIELDNAMES = [
        "wall_time_iso",
        "gpu_index",
        "uuid",
        "name",
        "window_seconds",
        "low_util_pct_window",
        "idle_reason_pct_window",
        "idle_entries_window",
        "avg_gpu_util_window",
        "avg_sm_clock_mhz_window",
        "avg_mem_clock_mhz_window",
        "avg_power_w_window",
    ]

    def __init__(self, out_dir: Path) -> None:
        self._path = ensure_directory(out_dir) / "gpu_summary.csv"
        self._initialized = self._path.exists()

    def write_reports(self, reports: list[SampleReport]) -> None:
        """Append long-window summaries to the CSV file."""
        with self._path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.FIELDNAMES)
            if not self._initialized:
                writer.writeheader()
                self._initialized = True
            for report in reports:
                summary = report.long_summary
                writer.writerow(
                    {
                        "wall_time_iso": report.sample.wall_time_iso,
                        "gpu_index": report.sample.identity.index,
                        "uuid": report.sample.identity.uuid,
                        "name": report.sample.identity.name,
                        "window_seconds": summary.window_seconds,
                        **summary.to_public_dict(),
                    }
                )


class ConsoleReporter:
    """Render a concise one-line-per-GPU console view."""

    HEADER = (
        "gpu idx | name | low_util_1m | low_util_20m | idle_pct_1m | "
        "idle_pct_20m | idle_entries_20m | util_20m | sm_clk_20m | power_20m"
    )

    def render(self, reports: list[SampleReport]) -> str:
        """Render reports as a multi-line string."""
        rows = [self.HEADER]
        for report in reports:
            rows.append(
                " | ".join(
                    [
                        str(report.sample.identity.index),
                        report.sample.identity.name,
                        _fmt(report.short_summary.low_util_pct_window),
                        _fmt(report.long_summary.low_util_pct_window),
                        _fmt(report.short_summary.idle_reason_pct_window),
                        _fmt(report.long_summary.idle_reason_pct_window),
                        _fmt(report.long_summary.idle_entries_window),
                        _fmt(report.long_summary.avg_gpu_util_window),
                        _fmt(report.long_summary.avg_sm_clock_mhz_window),
                        _fmt(report.long_summary.avg_power_w_window),
                    ]
                )
            )
        return "\n".join(rows)


class PrometheusExporter:
    """Optional Prometheus exporter for current rolling summaries."""

    def __init__(self, port: int) -> None:
        try:
            from prometheus_client import Gauge
        except ImportError as exc:
            raise RuntimeError(
                "prometheus-client is not installed. Install with `pip install -e \".[prometheus]\"`."
            ) from exc
        self._port = port
        labels = ("gpu_index", "uuid", "name")
        self._gauges = {
            "gpu_low_util_pct_1m": Gauge("gpu_low_util_pct_1m", "Short-window low utilization percentage.", labels),
            "gpu_low_util_pct_20m": Gauge("gpu_low_util_pct_20m", "Long-window low utilization percentage.", labels),
            "gpu_idle_reason_pct_1m": Gauge("gpu_idle_reason_pct_1m", "Short-window idle reason percentage.", labels),
            "gpu_idle_reason_pct_20m": Gauge("gpu_idle_reason_pct_20m", "Long-window idle reason percentage.", labels),
            "gpu_idle_entries_20m": Gauge("gpu_idle_entries_20m", "Long-window idle entry count.", labels),
            "gpu_avg_gpu_util_20m": Gauge("gpu_avg_gpu_util_20m", "Long-window average GPU utilization percentage.", labels),
            "gpu_avg_sm_clock_mhz_20m": Gauge("gpu_avg_sm_clock_mhz_20m", "Long-window average SM clock in MHz.", labels),
            "gpu_avg_power_w_20m": Gauge("gpu_avg_power_w_20m", "Long-window average power in watts.", labels),
        }

    def start(self) -> None:
        """Start the HTTP exporter."""
        from prometheus_client import start_http_server

        start_http_server(self._port)
        LOGGER.info("Started Prometheus exporter on port %s", self._port)

    def update(self, reports: list[SampleReport]) -> None:
        """Update gauges from the current reports."""
        for report in reports:
            labels = (
                str(report.sample.identity.index),
                report.sample.identity.uuid,
                report.sample.identity.name,
            )
            self._set("gpu_low_util_pct_1m", labels, report.short_summary.low_util_pct_window)
            self._set("gpu_low_util_pct_20m", labels, report.long_summary.low_util_pct_window)
            self._set("gpu_idle_reason_pct_1m", labels, report.short_summary.idle_reason_pct_window)
            self._set("gpu_idle_reason_pct_20m", labels, report.long_summary.idle_reason_pct_window)
            self._set("gpu_idle_entries_20m", labels, report.long_summary.idle_entries_window)
            self._set("gpu_avg_gpu_util_20m", labels, report.long_summary.avg_gpu_util_window)
            self._set("gpu_avg_sm_clock_mhz_20m", labels, report.long_summary.avg_sm_clock_mhz_window)
            self._set("gpu_avg_power_w_20m", labels, report.long_summary.avg_power_w_window)

    def _set(self, name: str, labels: tuple[str, str, str], value: float | int | None) -> None:
        """Set a gauge when a value is available."""
        if value is None:
            return
        self._gauges[name].labels(*labels).set(value)


def _fmt(value: float | int | None) -> str:
    """Format console values compactly."""
    if value is None:
        return "null"
    if isinstance(value, int):
        return str(value)
    return f"{value:.1f}"

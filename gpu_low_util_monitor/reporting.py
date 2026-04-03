"""Output sinks for JSONL, CSV, console, and Prometheus."""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from gpu_low_util_monitor.models import SampleReport, WindowSummary
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
        "window_role",
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
        """Append short- and long-window summaries to the CSV file."""
        with self._path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.FIELDNAMES)
            if not self._initialized:
                writer.writeheader()
                self._initialized = True
            for report in reports:
                for window_role, summary in (("short", report.short_summary), ("long", report.long_summary)):
                    writer.writerow(
                        {
                            "wall_time_iso": report.sample.wall_time_iso,
                            "gpu_index": report.sample.identity.index,
                            "uuid": report.sample.identity.uuid,
                            "name": report.sample.identity.name,
                            "window_role": window_role,
                            "window_seconds": summary.window_seconds,
                            **summary.to_public_dict(),
                        }
                    )


class ConsoleReporter:
    """Render a concise one-line-per-GPU console view with configured windows."""

    def render(self, reports: list[SampleReport]) -> str:
        """Render reports as a multi-line string."""
        if not reports:
            return "gpu idx | name | no data"
        short_label = _format_window_label(reports[0].short_summary.window_seconds)
        long_label = _format_window_label(reports[0].long_summary.window_seconds)
        rows = [
            " | ".join(
                [
                    "gpu idx",
                    "name",
                    f"low_util_short({short_label})",
                    f"low_util_long({long_label})",
                    f"idle_pct_short({short_label})",
                    f"idle_pct_long({long_label})",
                    f"idle_entries_long({long_label})",
                    f"util_long({long_label})",
                    f"sm_clk_long({long_label})",
                    f"power_long({long_label})",
                ]
            )
        ]
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
    """Optional Prometheus exporter for current rolling summaries.

    Metrics include explicit `window_role` and `window_seconds` labels so that
    operators can change window lengths without the metric names implying a
    fixed 60-second or 1200-second product contract.
    """

    def __init__(self, port: int) -> None:
        try:
            from prometheus_client import Gauge
        except ImportError as exc:
            raise RuntimeError(
                "prometheus-client is not installed. Install with `pip install -e \".[prometheus]\"`."
            ) from exc
        self._port = port
        labels = ("gpu_index", "uuid", "name", "window_role", "window_seconds")
        self._gauges = {
            "gpu_low_util_pct": Gauge("gpu_low_util_pct", "Rolling low-utilization percentage.", labels),
            "gpu_idle_reason_pct": Gauge("gpu_idle_reason_pct", "Rolling sampled Idle percentage.", labels),
            "gpu_idle_entries": Gauge("gpu_idle_entries", "Rolling software-derived Idle entry count.", labels),
            "gpu_avg_gpu_util": Gauge("gpu_avg_gpu_util", "Rolling average GPU utilization percentage.", labels),
            "gpu_avg_sm_clock_mhz": Gauge("gpu_avg_sm_clock_mhz", "Rolling average SM clock in MHz.", labels),
            "gpu_avg_power_w": Gauge("gpu_avg_power_w", "Rolling average power in watts.", labels),
        }

    def start(self) -> None:
        """Start the HTTP exporter."""
        from prometheus_client import start_http_server

        start_http_server(self._port)
        LOGGER.info("Started Prometheus exporter on port %s", self._port)

    def update(self, reports: list[SampleReport]) -> None:
        """Update gauges from the current reports."""
        for report in reports:
            self._set_windowed_metrics(report, "short", report.short_summary)
            self._set_windowed_metrics(report, "long", report.long_summary)

    def _set_windowed_metrics(self, report: SampleReport, window_role: str, summary: WindowSummary) -> None:
        """Update all gauges for one report and one configured window."""
        labels = (
            str(report.sample.identity.index),
            report.sample.identity.uuid,
            report.sample.identity.name,
            window_role,
            str(summary.window_seconds),
        )
        self._set("gpu_low_util_pct", labels, summary.low_util_pct_window)
        self._set("gpu_idle_reason_pct", labels, summary.idle_reason_pct_window)
        self._set("gpu_idle_entries", labels, summary.idle_entries_window)
        self._set("gpu_avg_gpu_util", labels, summary.avg_gpu_util_window)
        self._set("gpu_avg_sm_clock_mhz", labels, summary.avg_sm_clock_mhz_window)
        self._set("gpu_avg_power_w", labels, summary.avg_power_w_window)

    def _set(self, name: str, labels: tuple[str, str, str, str, str], value: float | int | None) -> None:
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


def _format_window_label(window_seconds: int) -> str:
    """Return a compact human-readable label for a configured window."""
    if window_seconds % 60 == 0:
        minutes = window_seconds // 60
        if minutes == 1:
            return "1m"
        return f"{minutes}m"
    return f"{window_seconds}s"

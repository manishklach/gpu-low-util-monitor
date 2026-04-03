"""CLI entry point for gpu-low-util-monitor."""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from gpu_low_util_monitor.collector import CollectorConfig, GPUCollector
from gpu_low_util_monitor.nvml_adapter import FakeNVMLBackend, RealNVMLBackend
from gpu_low_util_monitor.power import load_power_calibration_store
from gpu_low_util_monitor.reporting import (
    ConsoleReporter,
    CsvSummaryWriter,
    HeatmapJsonWriter,
    JsonlWriter,
    PrometheusExporter,
)
from gpu_low_util_monitor.util import configure_logging

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Monitor low-utilization time, idle-state behavior, power-based activity, and thermal/policy corroboration on NVIDIA datacenter GPUs.",
        epilog=(
            "This tool measures low-utilization, idle-state behavior, and power-based activity "
            "over time using documented NVIDIA signals. It provides a practical proxy for GPU "
            "underuse, workload starvation, underfeeding, or dark/dim GPUs, but it should not "
            "claim omniscient knowledge of economic waste or all causes of low activity. Thermal "
            "and power-limit signals are exposed as corroborating context, not singular truth. The "
            "short and long windows are operator-configurable; 60 seconds and 1200 seconds are "
            "defaults, not fixed product semantics."
        ),
    )
    parser.add_argument("--interval", type=float, default=1.0, help="Polling interval in seconds.")
    parser.add_argument(
        "--window-short",
        type=int,
        default=60,
        help="Operator-configurable short rolling window in seconds. Default: 60.",
    )
    parser.add_argument(
        "--window-long",
        type=int,
        default=1200,
        help="Operator-configurable long rolling window in seconds. Default: 1200.",
    )
    parser.add_argument("--out-dir", type=Path, default=Path("./out"), help="Output directory for JSONL and CSV.")
    parser.add_argument("--jsonl", action="store_true", help="Write one JSONL row per GPU sample with rolling summaries.")
    parser.add_argument("--csv", action="store_true", help="Write periodic CSV snapshots for the configured short and long windows.")
    parser.add_argument("--console-refresh", type=float, default=10.0, help="Console refresh interval in seconds.")
    parser.add_argument("--once", action="store_true", help="Run a single sampling pass to validate field availability and current state.")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging.")
    parser.add_argument(
        "--prometheus-port",
        type=int,
        default=None,
        help="Serve current rolling summaries as Prometheus gauges labeled by window role and window duration.",
    )
    parser.add_argument("--simulate", action="store_true", help="Use the fake NVML backend for local simulation.")
    parser.add_argument(
        "--power-mode",
        choices=("off", "raw", "calibrated"),
        default="raw",
        help="Choose whether power metrics are off, emitted as raw documented telemetry, or emitted with a repo-defined calibrated power-activity proxy.",
    )
    parser.add_argument(
        "--idle-baseline-w",
        type=float,
        default=None,
        help="Optional idle-baseline power in watts for the repo-defined normalized power-activity proxy.",
    )
    parser.add_argument(
        "--busy-reference-w",
        type=float,
        default=None,
        help="Optional busy-reference power in watts for the repo-defined normalized power-activity proxy.",
    )
    parser.add_argument("--power-calibration-file", type=Path, default=None, help="Optional JSON file with default and per-GPU power calibration overrides.")
    parser.add_argument(
        "--emit-heatmap-json",
        action="store_true",
        help="Write machine-friendly JSONL snapshots for later heatmap or notebook visualization.",
    )
    parser.add_argument("--heatmap-group-by", choices=("host", "gpu"), default="host", help="Grouping hint to include in heatmap JSONL snapshots.")
    parser.add_argument(
        "--no-power-normalization",
        action="store_true",
        help="Disable the repo-defined normalized power-activity proxy even if calibration is available.",
    )
    parser.add_argument(
        "--fail-on-unsupported",
        action="store_true",
        help="Fail immediately when an optional documented NVML field is unavailable.",
    )
    return parser


def main() -> int:
    """CLI program entry point."""
    args = build_parser().parse_args()
    configure_logging(args.verbose)

    calibrations = load_power_calibration_store(
        args.power_calibration_file,
        cli_idle_baseline_w=args.idle_baseline_w,
        cli_busy_reference_w=args.busy_reference_w,
    )

    backend = FakeNVMLBackend() if args.simulate else RealNVMLBackend(fail_on_unsupported=args.fail_on_unsupported)
    collector = GPUCollector(
        backend=backend,
        config=CollectorConfig(
            interval_seconds=args.interval,
            window_short_seconds=args.window_short,
            window_long_seconds=args.window_long,
            power_mode=args.power_mode,
            power_calibrations=calibrations,
            enable_power_normalization=args.power_mode == "calibrated" and not args.no_power_normalization,
        ),
    )

    jsonl_writer = JsonlWriter(args.out_dir) if args.jsonl else None
    csv_writer = CsvSummaryWriter(args.out_dir) if args.csv else None
    heatmap_writer = HeatmapJsonWriter(args.out_dir, group_by=args.heatmap_group_by) if args.emit_heatmap_json else None
    console_reporter = ConsoleReporter()
    exporter = PrometheusExporter(args.prometheus_port) if args.prometheus_port else None

    try:
        collector.initialize()
    except Exception as exc:
        LOGGER.error("%s", exc)
        return 2

    if exporter is not None:
        exporter.start()

    last_console_ts = 0.0
    last_csv_ts = 0.0

    try:
        while True:
            loop_start = time.monotonic()
            reports = collector.poll_once()
            if jsonl_writer is not None:
                jsonl_writer.write_reports(reports)
            if heatmap_writer is not None:
                heatmap_writer.write_reports(reports)
            if exporter is not None:
                exporter.update(reports)

            now = time.monotonic()
            if csv_writer is not None and (args.once or now - last_csv_ts >= 60.0):
                csv_writer.write_reports(reports)
                last_csv_ts = now

            if args.once or now - last_console_ts >= args.console_refresh:
                print(console_reporter.render(reports), flush=True)
                last_console_ts = now

            if args.once:
                return 0

            sleep_for = max(0.0, args.interval - (time.monotonic() - loop_start))
            time.sleep(sleep_for)
    except KeyboardInterrupt:
        LOGGER.info("Interrupted; shutting down.")
        return 0
    finally:
        collector.shutdown()

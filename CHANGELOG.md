# Changelog

All notable changes to `gpu-low-util-monitor` will be documented in this file.

The format is inspired by Keep a Changelog, with entries organized by release tag.

## [v0.2.0] - 2026-04-03

### Added

- Complementary power-first observability alongside low-utilization and idle-state metrics
- Current power, rolling average power, power-cap-relative activity, and cumulative energy deltas when available
- Optional calibrated `power_activity_pct` as a repo-defined first-order activity proxy
- Heatmap-oriented JSONL export for later notebook or web visualization
- `gpu_low_util_monitor.power` module for calibration loading and normalization helpers
- Simulation coverage for dark, dim, bright, bursty, and power-limited GPU power traces
- Power-path tests covering normalization, energy delta math, calibration loading, and heatmap formatting

### Changed

- Extended NVML-first collection to gather power cap and cumulative energy when available
- Extended JSONL, CSV, console, and Prometheus outputs to carry power-focused metrics
- Updated README to describe the combined behavioral plus power-based observability model
- Kept window semantics configurable and preserved the careful non-overclaiming framing

### Notes

- Power remains a first-order activity proxy, not a perfect utilization truth source
- `power_activity_pct` is calibration-dependent and emitted only when valid calibration is available
- Energy metrics are emitted only when cumulative energy support is available on the runtime path
- DCGM power and energy fields are documented as a future optional integration path rather than a required dependency

## [v0.1.0] - 2026-04-03

### Added

- Initial public release of the NVML-first low-utilization and idle-state monitor
- Rolling short-window and long-window summaries with configurable defaults
- JSONL, CSV, and console reporting
- Optional Prometheus exporter
- Fake NVML backend for simulation and test coverage
- Linux-first packaging, systemd unit, and GitHub Actions CI

### Changed

- Shifted public semantics from fixed `1m` and `20m` naming toward configurable short/long window semantics
- Updated public outputs to include operator-configurable window labels and metadata
- Tightened README, CLI help text, and examples to avoid overclaiming

### Notes

- The headline KPI is long-window low-utilization percentage
- Sampled Idle presence and software-derived Idle entry counts are corroborating signals, not interchangeable with cumulative low-utilization policy time
- Real H100/H200 validation remains important for field support and low-util counter normalization

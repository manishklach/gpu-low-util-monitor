# gpu-low-util-monitor

![CI](https://github.com/manishklach/gpu-low-util-monitor/actions/workflows/ci.yml/badge.svg)

`gpu-low-util-monitor` is a Linux-first observability tool for NVIDIA datacenter GPUs, with NVIDIA H100 and H200 as the initial target use cases. It measures low-utilization, idle-state behavior, and power-based activity over time using documented NVIDIA signals. It provides a practical proxy for GPU underuse, workload starvation, underfeeding, or dark/dim GPUs, but it should not claim omniscient knowledge of economic waste or all causes of low activity.

## Why This Exists

Datacenter GPU observability is often too snapshot-heavy. A point-in-time GPU busy number can miss the more operationally useful question: was this GPU actually doing meaningful work over the last few minutes, or did it spend a meaningful share of that time underfed, intermittently idle, or electrically dim? This repository exists to measure a careful subset of observables: documented low-utilization policy time, sampled GPU idle-state monitoring, software-derived Idle entries, and GPU power telemetry that help distinguish dark, dim, bursty, underfed, or bright/busy GPUs over configurable rolling windows.

## Why Not Just GPU Busy?

Instantaneous utilization is useful context, but it is not the headline KPI here. Short bursts of work can make a GPU look busy in a snapshot while still leaving a large share of the recent short or long window in documented low-utilization policy, sampled idle-state presence, or low power. Rolling-window telemetry is a better fit for workload starvation, bursty scheduling, and underfed GPUs than a single busy percentage sampled at one moment.

## Quick Story

A common operator experience looks like this: `nvidia-smi` shows a GPU hovering around 70% busy, so at first glance it does not look like a problem. But the rolling-window view can still show high long-window low-utilization percentage, repeated Idle entries, and dim average power. That combination suggests the GPU is active in bursts rather than steadily fed. The point is not that the instantaneous busy number is wrong. The point is that it is incomplete.

## What It Measures

The collector uses documented NVIDIA interfaces only. NVML remains the primary high-fidelity path, and the repo now also includes an optional DCGM exporter ingest mode for environments that already expose documented DCGM metrics.

Backend modes:

- `--backend nvml`
  Primary mode. Supports the full current feature set that the runtime path exposes, including documented low-utilization policy counters, sampled Idle behavior, power telemetry, and MIG-aware enumeration when available.
- `--backend dcgm`
  Optional degraded mode that ingests documented DCGM exporter metrics from an HTTP endpoint or local metrics file. It supports GPU utilization, clocks, power, and cumulative energy when those DCGM metrics are present, but it does not expose the NVML-only low-utilization counter or sampled Idle-state behavior.

Documented signals used today:

1. `NVML_FI_DEV_PERF_POLICY_LOW_UTILIZATION`
   This is treated as the authoritative cumulative low-utilization policy signal.
2. Current clocks event reasons bitmask
   This is sampled to determine whether the documented `Idle` reason is active at the poll instant.
3. Standard telemetry
   GPU utilization, SM clock, memory clock when available, current power draw, power cap when available, cumulative energy when available, GPU name, UUID, and index.

Headline KPI:

- long-window low-utilization percentage

Corroborating behavioral metrics:

- short-window low-utilization percentage
- long-window sampled Idle percentage
- long-window Idle entry count
- long-window average GPU utilization

Complementary power/activity metrics:

- current power draw
- short-window and long-window average power draw
- long-window power as a percentage of cap when power cap is available
- optional normalized power activity percentage when calibration is available
- short-window and long-window energy accumulation when cumulative energy is available
- current sampled thermal-limit and power-limit context when documented clock-event signals are available
- short-window and long-window sampled thermal-limit and power-limit percentages when supported

The design intentionally treats low-utilization over time as the primary KPI, not instantaneous utilization. The default short and long windows are 60 seconds and 1200 seconds, but both are operator-configurable at runtime and should be interpreted as defaults rather than fixed product semantics.

In public docs, the clean mental model is:

- `low_util_pct_short` and `low_util_pct_long`
- `idle_reason_pct_short` and `idle_reason_pct_long`
- `idle_entries_short` and `idle_entries_long`
- `avg_gpu_util_short` and `avg_gpu_util_long`
- `avg_power_w_short` and `avg_power_w_long`
- `power_activity_pct_short` and `power_activity_pct_long`

Some outputs and examples still show default-style labels such as `1m` and `20m` for readability or backward compatibility. Those should be read as the configured short and long windows, whose defaults are 60 seconds and 1200 seconds.

## MIG Support

MIG support is intentionally careful rather than overclaimed.

- In NVML mode, `--mig-mode auto` prefers per-MIG-instance reporting when MIG instances can be enumerated on a GPU.
- `--mig-mode gpu` reports physical GPUs only, even if MIG is enabled.
- `--mig-mode mig` requests MIG-only reporting where MIG enumeration is available.

Outputs include additional identity fields so operators can distinguish physical GPUs from MIG instances:

- `entity_kind`
- `parent_uuid`
- `mig_instance_id`
- `mig_profile`

Important caveat: MIG instances do not always expose the same signals as a full physical GPU. If a metric is unavailable for a MIG instance or backend mode, the repo emits `null` and keeps the availability flags honest.

NVML is the right default for this repo because it is direct, documented, and already available anywhere `nvidia-smi` works. DCGM remains relevant for fleet aggregation and managed environments; that is why it appears in the references and roadmap, even though the current implementation path stays NVML-first.

## Behavioral Metrics

### `low_util_pct_window`

`low_util_pct_window` is the fraction of elapsed wall time in the rolling window during which the documented low-utilization perf-policy counter increased.

Formula:

`100 * sum(delta_low_util_counter_ns) / sum(delta_elapsed_ns)`

Implementation notes:

- Derived from deltas of the cumulative `NVML_FI_DEV_PERF_POLICY_LOW_UTILIZATION` counter
- Uses monotonic time for elapsed-time math
- Clamped to `[0, 100]`
- Counter resets or negative deltas are treated defensively and never contribute misleading negative time

Interpretation:

- High long-window low-utilization percentage suggests the GPU spent a meaningful fraction of the recent long window in documented low-utilization policy

### `idle_reason_pct_window`

`idle_reason_pct_window` is the fraction of samples in the rolling window where the current `Idle` clock-event reason was active.

Formula:

`100 * idle_sample_count / total_sample_count`

Implementation notes:

- Based on polling the current clocks event reasons bitmask at each sample
- Represents sampled state presence, not a cumulative hardware timer

Interpretation:

- High long-window sampled Idle percentage suggests the GPU frequently appeared idle at sample times

### `idle_entries_window`

`idle_entries_window` is the count of `false -> true` transitions into Idle state derived by polling.

Implementation notes:

- This is a software-derived metric
- NVIDIA does not provide a built-in idle-entry counter through the documented signals used here
- Transition fidelity depends on polling cadence

Interpretation:

- High long-window Idle entry count suggests bursty or intermittent dispatch

## Power Metrics

Power is treated as a strong first-order activity proxy, not a perfect truth engine. It is complementary to low-utilization and idle-state telemetry:

- power tells you that a GPU looks dark, dim, or bright
- low-util / idle telemetry helps explain the pattern and frequency behind that behavior

### `current_power_w`

Current sampled device power draw in watts when supported.

### `avg_power_w_window`

Rolling time-weighted average power over the configured window.

### `power_pct_of_cap_window`

Derived percentage:

`100 * avg_power_w_window / avg_power_cap_w_window`

It is emitted only when a power cap is available and is clipped to `[0, 100]`.

### `energy_joules_window`

Cumulative energy delta over the configured window when a cumulative energy counter is available. If the runtime path does not expose cumulative energy, the value is `null`.

### `power_activity_pct_window`

Repo-defined normalized first-order activity proxy inspired by the idea that power is often a strong first-order indicator of GPU activity:

`100 * (avg_power_w_window - idle_baseline_w) / (busy_reference_w - idle_baseline_w)`

Important cautions:

- this is not an official NVIDIA metric
- it is clipped to `[0, 100]`
- it is only emitted when valid calibration values are available
- if calibration is missing or invalid, the value is `null`

## Thermal Corroboration

Low-util behavior is not always a workload-feeding problem. A GPU can also look constrained because thermal-limit or power-limit reasons are active.

This repository exposes those signals as corroborating context, not singular truth:

- `thermal_limit_active` and `power_limit_active`
- `thermal_limit_pct_window` and `power_limit_pct_window`

These metrics are derived from documented current clocks event or throttle reason bitmasks when supported by the runtime path. They help operators distinguish a likely underfed or bursty workload from a GPU that is being held back by thermal or power-policy conditions.

## Metric Semantics

### Supporting Metrics

- `avg_gpu_util_window`
- `avg_sm_clock_mhz_window`
- `avg_mem_clock_mhz_window`
- `avg_power_w_window`
- `power_pct_of_cap_window`
- `energy_joules_window`
- `power_activity_pct_window`

These are supporting context, not replacements for the headline KPI. Raw power is documented telemetry. Normalized power activity is a repo-defined calibration-based proxy, not an official NVIDIA metric.

### Distinctions That Matter

This repository explicitly distinguishes:

- cumulative low-utilization policy time
- current sampled Idle state
- software-derived Idle entry counts
- raw power draw
- optional normalized power activity based on operator-supplied calibration
- current sampled thermal-limit and power-limit states
- sampled thermal-limit and power-limit percentages over rolling windows

These are related but not interchangeable signals.

## Interpretation Guidance

The best operational read comes from the metrics together, not in isolation.

- High long-window low-utilization percentage suggests sustained or repeated time in documented low-utilization policy
- High long-window sampled Idle percentage suggests the GPU often looked idle when sampled
- High long-window Idle entry count suggests bursty scheduling or intermittent dispatch
- Low power over the long window suggests the GPU looked dark or dim as a first-order electrical activity proxy
- High long-window power with low long-window low-utilization percentage suggests a bright, likely healthy busy GPU
- Moderate long-window average GPU utilization does not invalidate high low-utilization time; short bursts of work can coexist with meaningful low-util intervals
- Low-utilization and low power are often consistent with workload starvation or underfeeding, but the tool measures observables rather than proving root cause

Common interpretations:

- Low power + high long-window low-utilization percentage: likely underfed, dark, or poorly packed GPU
- Low power + high long-window sampled Idle percentage: likely frequently idle at sample times
- Low power + high long-window Idle entry count: likely bursty or intermittent dispatch
- High power + low long-window low-utilization percentage: likely healthy busy GPU
- High power + high long-window low-utilization percentage: investigate for calibration mismatch, measurement interpretation issues, or more complex workload behavior
- High long-window low-utilization with elevated thermal-limit or power-limit percentage: investigate whether the observed behavior reflects cooling, thermal throttling, or performance-policy pressure rather than purely workload starvation

## Limitations

- The Idle event reason may be deprecated or removed in future NVIDIA releases
- Low-utilization is not identical to zero work
- Power-based activity is still a proxy, not a perfect utilization truth engine
- Normalized power activity depends on calibration quality
- Underfeeding can come from many causes: host stalls, bubbles, sync gaps, small batches, bursty scheduling, and other pipeline effects
- `idle_entries_window` is derived in software by polling `Idle` transitions, not provided directly by NVIDIA
- Polling interval affects how many short idle episodes are observed
- Cumulative energy support is platform and runtime dependent
- This tool measures observables, not root-cause certainty
- The normalization of the low-utilization counter and cumulative energy counter should still be validated on the target driver branch during hardware bring-up
- Thermal-limit and power-limit corroboration depend on documented clock-event/throttle reason support on the target driver/runtime path

## Installation

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,nvml]"
```

Today the easiest path is still cloning the repo and installing it locally. The packaging metadata is now PyPI-ready and versioned from the package itself, but the README should not imply that a published package already exists unless and until one is actually released.

Simulation only:

```bash
pip install -e ".[dev]"
```

With optional Prometheus exporter support:

```bash
pip install -e ".[dev,prometheus]"
```

For release builds:

```bash
pip install -e ".[release]"
python -m build
twine check dist/*
```

## Power Calibration

Raw current power and rolling average power are emitted whenever the runtime path supports them. Normalized power activity is optional and requires calibration.

You can provide calibration in two ways:

1. CLI defaults:

```bash
python -m gpu_low_util_monitor --idle-baseline-w 80 --busy-reference-w 700
```

2. JSON calibration file:

```json
{
  "default": {
    "idle_baseline_w": 80.0,
    "busy_reference_w": 700.0
  },
  "by_uuid": {
    "GPU-1234": {
      "idle_baseline_w": 82.0,
      "busy_reference_w": 690.0
    }
  },
  "by_name_prefix": {
    "NVIDIA H100": {
      "idle_baseline_w": 78.0,
      "busy_reference_w": 700.0
    }
  }
}
```

Per-GPU UUID overrides win first, then model-family prefix overrides, then the default calibration. If no valid calibration is available, `power_activity_pct_window` stays `null`.

## Usage

```bash
python -m gpu_low_util_monitor \
  --interval 1 \
  --window-short 60 \
  --window-long 1200 \
  --out-dir ./out \
  --jsonl \
  --csv \
  --console-refresh 10
```

Useful commands:

```bash
python -m gpu_low_util_monitor --simulate --once --verbose
python -m gpu_low_util_monitor --simulate --interval 1 --window-short 60 --window-long 1200 --out-dir ./out --jsonl --csv
python -m gpu_low_util_monitor --simulate --prometheus-port 9108 --out-dir ./out
python -m gpu_low_util_monitor --simulate --idle-baseline-w 80 --busy-reference-w 700 --emit-heatmap-json --jsonl --csv
python -m gpu_low_util_monitor --once --verbose
python -m gpu_low_util_monitor --backend dcgm --dcgm-url http://dcgm-exporter:9400/metrics --window-short 60 --window-long 1200
python -m gpu_low_util_monitor --backend nvml --mig-mode auto --once --verbose
```

The `--window-short` and `--window-long` values are operator-configurable. The defaults are 60 seconds and 1200 seconds, but the semantics of the tool are not tied to those particular durations. Public examples often show 1 minute and 20 minutes because they are sensible defaults, not because they are immutable product constants.

Fastest way to try the tool without hardware:

```bash
pip install -e ".[dev]"
python -m gpu_low_util_monitor --simulate --once --verbose
```

Power-specific options:

- `--backend nvml|dcgm`
- `--mig-mode auto|gpu|mig`
- `--dcgm-url`
- `--dcgm-file`
- `--dcgm-timeout`
- `--power-mode off|raw|calibrated`
- `--idle-baseline-w`
- `--busy-reference-w`
- `--power-calibration-file`
- `--emit-heatmap-json`
- `--heatmap-group-by host|gpu`
- `--no-power-normalization`

## Deployment

### Docker

A production-friendly image definition is included in [Dockerfile](Dockerfile). It installs the package with the `nvml` and `prometheus` extras and starts the monitor by default with sensible runtime arguments.

Example build and run:

```bash
docker build -t gpu-low-util-monitor:local .
docker run --rm \
  --gpus all \
  -v $(pwd)/out:/var/log/gpu-low-util-monitor \
  gpu-low-util-monitor:local
```

Assumptions:

- the host has NVIDIA drivers installed
- the container runtime exposes GPUs to the container
- NVML is visible inside the container

### Kubernetes / DaemonSet

Sample manifests live in [deploy/configmap.yaml](deploy/configmap.yaml) and [deploy/daemonset.yaml](deploy/daemonset.yaml).

The DaemonSet is intentionally minimal and assumes:

- GPU nodes are already configured with NVIDIA runtime/device visibility
- your cluster labels GPU nodes in a way similar to `nvidia.com/gpu.present=true`
- exposing all host GPUs to the monitor pod is acceptable for your environment

Apply the sample manifests with:

```bash
kubectl apply -f deploy/configmap.yaml
kubectl apply -f deploy/daemonset.yaml
```

## Dashboarding

A Grafana starter dashboard is included at [grafana/dashboard.json](grafana/dashboard.json). It focuses on the operator questions this repo is designed to answer:

- long-window and short-window low-utilization
- long-window sampled Idle percentage and Idle entries
- long-window average GPU utilization
- current and long-window average power
- long-window power as a percentage of cap
- long-window thermal-limit and power-limit corroboration

## How It Works

At each poll, the collector:

1. Captures a monotonic timestamp and collects one documented NVML sample per GPU
2. Updates time-based rolling windows for low-utilization, sampled Idle state, utilization, clocks, power, and energy where available
3. Computes short-window and long-window summaries, optionally adds calibrated power normalization, then emits JSONL, CSV, console, heatmap, and Prometheus outputs

The windows are time-based rather than sample-count-based, so interval jitter is handled correctly. Short and long windows remain operator-configurable; 60 seconds and 1200 seconds are defaults only.

Backend-specific caveats:

- NVML mode is the only mode that currently supports the documented low-utilization perf-policy counter used for the headline KPI.
- DCGM mode is intentionally degraded: low-utilization percentage, sampled Idle percentage, Idle entries, and thermal/power-limit reason sampling are emitted as unavailable because they do not map cleanly through the current DCGM exporter ingest path.
- MIG instance reporting is most complete in NVML mode. In DCGM mode, MIG awareness depends on exporter labels such as `GPU_I_ID` and `GPU_I_PROFILE`.

## Running Later on H100/H200

### 1. Verify driver and NVML visibility

```bash
nvidia-smi
```

Confirm that:

- the GPUs are visible
- the driver is healthy
- NVML is available

### 2. Run one-shot validation

```bash
python -m gpu_low_util_monitor --once --verbose
```

Validate that:

- the low-utilization perf-policy counter is exposed on the target driver and GPU
- current Idle reason polling works on that host
- current power and power cap look plausible
- cumulative energy appears if supported on that platform

### 3. Run continuous collection

```bash
python -m gpu_low_util_monitor \
  --interval 1 \
  --window-short 60 \
  --window-long 1200 \
  --out-dir /var/log/gpu-low-util-monitor \
  --jsonl \
  --csv \
  --emit-heatmap-json \
  --console-refresh 10
```

### 4. Inspect outputs

```bash
tail -f /var/log/gpu-low-util-monitor/gpu_samples.jsonl
tail -f /var/log/gpu-low-util-monitor/gpu_summary.csv
tail -f /var/log/gpu-low-util-monitor/gpu_heatmap.jsonl
```

### 5. Optional systemd deployment

```bash
sudo cp systemd/gpu-low-util-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gpu-low-util-monitor.service
sudo systemctl status gpu-low-util-monitor.service
```

## Illustrative Case Study

Illustrative scenario, not a claimed production result:

Standard monitoring showed modest GPU utilization and no obvious outage. `gpu-low-util-monitor` then showed that the GPU spent a large share of the configured long window in documented low-utilization policy, re-entered Idle repeatedly, and looked relatively dim in rolling power. That combination points more toward host-side feeding gaps or bursty dispatch than a healthy steady-state workload. If thermal-limit or power-limit sampled percentages were also elevated, the operator would have stronger evidence to investigate cooling or policy pressure instead of workload starvation alone.

## Example Outputs

### Console

```text
gpu idx | name | low_util_short(1m) | low_util_long(20m) | idle_pct_short(1m) | idle_pct_long(20m) | idle_entries_long(20m) | current_power_w | avg_power_short(1m) | avg_power_long(20m) | power_pct_cap_long(20m) | power_activity_long(20m) | util_long(20m) | sm_clk_long(20m)
0 | NVIDIA H100 80GB HBM3 | 65.8 | 67.1 | 30.5 | 33.2 | 49 | 212.0 | 218.6 | 216.1 | 30.9 | 22.0 | 27.4 | 1008.8
1 | NVIDIA H200 141GB HBM3e | 2.0 | 2.0 | 0.0 | 0.0 | 0 | 662.0 | 662.0 | 662.0 | 94.6 | 93.9 | 96.0 | 1830.0
```

The example above uses the default windows. If you change `--window-short` or `--window-long`, the rendered labels change too. In other words, `low_util_long(20m)` in this example should be read as "the configured long-window low-utilization percentage," not as a fixed product constant.

### JSONL

See [examples/sample_output.jsonl](examples/sample_output.jsonl).

### MIG-Aware JSONL

See [examples/sample_mig_output.jsonl](examples/sample_mig_output.jsonl).

### CSV

See [examples/sample_summary.csv](examples/sample_summary.csv).

### Heatmap JSONL

If `--emit-heatmap-json` is enabled, the tool writes machine-friendly snapshots for later notebook or web visualization. Each row is centered on the configured long window and includes generic window metadata so downstream consumers do not need to assume 20 minutes:

- timestamp
- host
- gpu index
- UUID
- GPU name
- current power
- `window_role` and `window_seconds`
- long-window average power
- long-window normalized power activity when calibrated
- long-window low-utilization percentage
- long-window sampled Idle percentage
- long-window Idle entry count
- long-window sampled thermal-limit and power-limit percentages

### Prometheus Exposition

See [examples/sample_prometheus.txt](examples/sample_prometheus.txt).

### DCGM Exporter Input Example

See [examples/sample_dcgm_exporter.prom](examples/sample_dcgm_exporter.prom).

### Screenshots

See [examples/screenshots/README.md](examples/screenshots/README.md) for the placeholder structure reserved for future visual captures.

## References

- NVIDIA NVML API Reference Guide: [docs.nvidia.com/deploy/nvml-api](https://docs.nvidia.com/deploy/nvml-api/index.html)
- NVML device queries, including power and total energy APIs: [group__nvmlDeviceQueries.html](https://docs.nvidia.com/deploy/nvml-api/group__nvmlDeviceQueries.html)
- NVML field value enums and field IDs: [group__nvmlFieldValueEnums.html](https://docs.nvidia.com/deploy/nvml-api/group__nvmlFieldValueEnums.html)
- NVML clocks event reasons: [group__nvmlClocksEventReasons.html](https://docs.nvidia.com/deploy/nvml-api/group__nvmlClocksEventReasons.html)
- NVIDIA `nvidia-smi` documentation: [docs.nvidia.com/deploy/nvidia-smi](https://docs.nvidia.com/deploy/nvidia-smi/index.html)
- NVIDIA DCGM field identifiers: [dcgm-api-field-ids.html](https://docs.nvidia.com/datacenter/dcgm/latest/dcgm-api/dcgm-api-field-ids.html)

These references are the basis for the repository's semantics:

- NVML is the underlying management interface used by `nvidia-smi`
- `NVML_FI_DEV_PERF_POLICY_LOW_UTILIZATION` is used as the primary low-utilization policy signal and therefore the basis of the headline long-window KPI
- NVML power and energy queries provide the raw inputs for the complementary power-first activity view in the current implementation
- DCGM field identifiers such as `DCGM_FI_DEV_GPU_UTIL`, `DCGM_FI_DEV_SM_CLOCK`, `DCGM_FI_DEV_MEM_CLOCK`, `DCGM_FI_DEV_POWER_USAGE`, and `DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION` are the basis of the optional DCGM exporter ingest mode
- Idle is treated as a current sampled event reason, not a cumulative timer
- NVIDIA documents that Idle-related event reporting may be deprecated in future releases
- `nvidia-smi` exposes clocks event reasons and related counters, which helps operators validate related signals on target hosts
- DCGM documents fields such as `DCGM_FI_DEV_GPU_UTIL`, `DCGM_FI_DEV_SM_CLOCK`, `DCGM_FI_DEV_MEM_CLOCK`, `DCGM_FI_DEV_POWER_USAGE`, `DCGM_FI_DEV_POWER_USAGE_INSTANT`, and `DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION`, which are the basis of the current optional DCGM exporter ingest mode

## Roadmap

### Actively Working On

- Validate documented field support and counter units across real H100 and H200 driver stacks
- Validate total energy support and scaling across driver branches and supported GPU families
- Add more hardware validation notes for future NVIDIA datacenter GPUs

### Backlog

- Add richer Prometheus labeling and scrape examples
- Add summary snapshots and fleet-level aggregation helpers
- Add examples for correlating low-utilization time with scheduler and input-pipeline telemetry
- Expand DCGM support beyond exporter ingest for environments that want richer DCGM-backed field integration

## Release Notes

Current release line highlights:

- configurable short and long rolling windows
- low-utilization, idle-state, and power-first observability in one tool
- JSONL output with role-based and duration-based summaries
- CSV summaries that include `window_role` and `window_seconds`
- heatmap JSONL snapshots that center the configured long window while including explicit window metadata
- configurable-window-aware Prometheus metrics
- fake NVML backend for simulation and tests
- Linux-first packaging, systemd unit, and GitHub Actions CI

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for local setup and contribution guidance.

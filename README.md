# gpu-low-util-monitor

`gpu-low-util-monitor` is a Linux-first observability tool for NVIDIA datacenter GPUs, with H100 and H200 as the initial target. It measures low-utilization time, idle-state behavior, and supporting telemetry over rolling windows using documented NVIDIA NVML signals. This tool measures low-utilization and idle-state behavior over time using documented NVIDIA signals. It provides a practical proxy for GPU underuse, workload starvation, or underfeeding, but it should not claim omniscient knowledge of economic waste or all causes of low activity.

## Why This Exists

Datacenter GPUs are expensive, and operators often need a defensible answer to a narrower question than "was this GPU worth the money?": did the GPU spend a meaningful fraction of recent wall time in a documented low-utilization policy state, appear idle at sample times, or bounce in and out of idle episodes that suggest bursty or underfed work? This repository exists to make that rolling-window view easy to collect, export, and validate.

## What It Measures

The collector uses NVIDIA NVML as the primary source of truth and relies only on documented fields and APIs:

1. `NVML_FI_DEV_PERF_POLICY_LOW_UTILIZATION`
2. Current clocks event reasons bitmask, to detect whether the documented `Idle` reason is active at the current sample
3. Standard telemetry:
   GPU utilization, SM clock, memory clock when available, power draw, GPU name, UUID, and index

Headline KPI:

- `low_util_pct_20m`

Corroborating metrics:

- `low_util_pct_1m`
- `idle_reason_pct_20m`
- `idle_entries_20m`
- `avg_gpu_util_20m`

The design intentionally treats low-utilization over time as the primary KPI, not instantaneous utilization.

## Metric Semantics

### `low_util_pct_window`

`low_util_pct_window` is the fraction of elapsed wall time in the rolling window during which the documented low-utilization perf-policy counter increased.

Formula:

`100 * sum(delta_low_util_counter_ns) / sum(delta_elapsed_ns)`

Implementation notes:

- Derived from deltas of the cumulative `NVML_FI_DEV_PERF_POLICY_LOW_UTILIZATION` counter
- Uses monotonic time for elapsed-time math
- Clamped to `[0, 100]`
- Counter resets or negative deltas are treated defensively and do not contribute positive time

Interpretation:

- High `low_util_pct_20m` suggests the GPU spent a meaningful fraction of the recent window in documented low-utilization policy

### `idle_reason_pct_window`

`idle_reason_pct_window` is the fraction of samples in the rolling window where the current `Idle` clock-event reason was active.

Formula:

`100 * idle_sample_count / total_sample_count`

Implementation notes:

- Based on polling the current clocks event reasons bitmask at each sample
- Represents sampled idle-state presence, not a cumulative hardware timer

Interpretation:

- High `idle_reason_pct_20m` suggests the GPU frequently appeared idle at sample times

### `idle_entries_window`

`idle_entries_window` is the count of `false -> true` transitions into Idle state derived by polling.

Implementation notes:

- This is a software-derived metric
- NVIDIA does not provide a built-in idle-entry counter through the documented signals used here
- Transition fidelity depends on polling cadence

Interpretation:

- High `idle_entries_20m` suggests bursty or intermittent dispatch, especially when paired with non-trivial `low_util_pct_20m`

### `avg_gpu_util_window`

`avg_gpu_util_window` is a time-weighted average of sampled GPU utilization across the window.

Interpretation:

- Supporting context only, not the headline KPI

### Distinctions That Matter

This repository explicitly distinguishes:

- low-utilization policy time: cumulative documented perf-policy counter behavior
- current sampled Idle reason: point-in-time state observed at each poll
- software-derived idle entry counts: userland transition counts computed from polling

These are not interchangeable metrics.

## Interpretation Guidance

The best operational read comes from the metrics together, not in isolation.

- High `low_util_pct_20m` suggests sustained or repeated time in documented low-utilization policy
- High `idle_reason_pct_20m` suggests the GPU often looked idle when sampled
- High `idle_entries_20m` suggests bursty scheduling or intermittent dispatch
- Moderate `avg_gpu_util_20m` does not invalidate high low-utilization time; short bursts of work can coexist with meaningful low-util intervals
- Low-utilization is often consistent with workload starvation or underfeeding, but the tool measures observables rather than proving root cause

Common interpretations:

- High `low_util_pct_20m` + high `idle_reason_pct_20m`: likely many idle or near-idle periods
- High `low_util_pct_20m` + lower `idle_reason_pct_20m`: likely underfed, bursty, or bubble-heavy work rather than complete idleness
- Low `low_util_pct_20m` + high utilization + lower clocks: potentially power or thermal limitation rather than lack of work

## Limitations

- This tool does not claim universal truth about "underutilization" or economic waste
- Low-utilization is not identical to zero work
- Underfeeding can come from many causes: host stalls, bubbles, synchronization gaps, small batches, bursty scheduling, and other pipeline effects
- `idle_entries_window` is derived in software by polling `Idle` transitions, not provided directly by NVIDIA
- Polling interval affects how many short idle episodes are observed
- The idle event reason API may be deprecated or changed in future NVIDIA releases
- This tool measures observables, not root-cause certainty

## How It Works

At each poll, the collector:

1. Captures a monotonic timestamp
2. Reads one sample per GPU through the NVML adapter
3. Reads the cumulative low-utilization perf-policy counter when supported
4. Reads the current clocks event reasons bitmask and determines whether `Idle` is active when supported
5. Collects utilization, clocks, and power telemetry
6. Appends the sample to a time-based rolling window
7. Computes rolling summaries for the short and long windows
8. Emits JSONL, CSV, console output, and optional Prometheus gauges

Windows are time-based, not sample-count-based, so interval jitter is handled correctly.

## Installation

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,nvml]"
```

Simulation only:

```bash
pip install -e ".[dev]"
```

With Prometheus exporter support:

```bash
pip install -e ".[dev,prometheus]"
```

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
python -m gpu_low_util_monitor --once --verbose
```

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
- clocks, power, and utilization values look plausible

### 3. Run continuous collection

```bash
python -m gpu_low_util_monitor \
  --interval 1 \
  --window-short 60 \
  --window-long 1200 \
  --out-dir /var/log/gpu-low-util-monitor \
  --jsonl \
  --csv \
  --console-refresh 10
```

### 4. Inspect outputs

```bash
tail -f /var/log/gpu-low-util-monitor/gpu_samples.jsonl
tail -f /var/log/gpu-low-util-monitor/gpu_summary.csv
```

### 5. Optional systemd deployment

```bash
sudo cp systemd/gpu-low-util-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gpu-low-util-monitor.service
sudo systemctl status gpu-low-util-monitor.service
```

## Example Outputs

### Console

```text
gpu idx | name | low_util_1m | low_util_20m | idle_pct_1m | idle_pct_20m | idle_entries_20m | util_20m | sm_clk_20m | power_20m
0 | NVIDIA H100 80GB HBM3 | 65.8 | 67.1 | 30.5 | 33.2 | 49 | 27.4 | 1008.8 | 216.1
1 | NVIDIA H200 141GB HBM3e | 2.0 | 2.0 | 0.0 | 0.0 | 0 | 96.0 | 1830.0 | 662.0
```

### JSONL

See [examples/sample_output.jsonl](/Users/ManishKL/Documents/Playground/gpu-low-util-monitor/examples/sample_output.jsonl).

### CSV

See [examples/sample_summary.csv](/Users/ManishKL/Documents/Playground/gpu-low-util-monitor/examples/sample_summary.csv).

## Prometheus Metrics

If `--prometheus-port` is set, the exporter publishes:

- `gpu_low_util_pct_1m`
- `gpu_low_util_pct_20m`
- `gpu_idle_reason_pct_1m`
- `gpu_idle_reason_pct_20m`
- `gpu_idle_entries_20m`
- `gpu_avg_gpu_util_20m`
- `gpu_avg_sm_clock_mhz_20m`
- `gpu_avg_power_w_20m`

These reflect the current rolling summaries, labeled by GPU index, UUID, and name.

## Simulation Mode

The fake NVML backend supports realistic local validation scenarios:

1. Fully idle GPU
2. Steady busy GPU
3. Bursty workload
4. Underfed GPU
5. Power-limited busy GPU

Simulation mode is intended for development, metric validation, and documentation before access to H100 or H200 hardware.

## Roadmap

- Validate documented field support and counter units across real H100 and H200 driver stacks
- Add richer Prometheus labeling and scrape examples
- Add summary snapshots and fleet-level aggregation helpers
- Add examples for correlating low-utilization time with scheduler and input-pipeline telemetry
- Add more hardware validation notes for future NVIDIA datacenter GPUs

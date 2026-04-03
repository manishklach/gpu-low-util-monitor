# gpu-low-util-monitor

`gpu-low-util-monitor` is a Linux-first observability tool for NVIDIA datacenter GPUs, with H100 and H200 as the initial target. It measures low-utilization time, idle-state behavior, and supporting telemetry over rolling windows using documented NVIDIA NVML signals. This tool measures low-utilization and idle-state behavior over time using documented NVIDIA signals. It provides a practical proxy for GPU underuse, workload starvation, or underfeeding, but it should not claim omniscient knowledge of economic waste or all causes of low activity.

## Why This Exists

Datacenter GPUs are expensive, and operators often need a defensible answer to a narrower question than "was this GPU kept busy enough recently?" This repository exists to measure a careful subset of observables: documented low-utilization policy time, sampled Idle-state presence, software-derived Idle entries, and supporting telemetry that helps interpret likely underfeeding, bursty dispatch, or near-idle behavior over rolling windows.

## What It Measures

The collector uses NVIDIA NVML as the primary source of truth and relies only on documented fields and APIs:

1. `NVML_FI_DEV_PERF_POLICY_LOW_UTILIZATION`
   This is treated as the authoritative cumulative low-utilization policy signal.
2. Current clocks event reasons bitmask
   This is sampled to determine whether the documented `Idle` reason is active at the poll instant.
3. Standard telemetry
   GPU utilization, SM clock, memory clock when available, power draw, GPU name, UUID, and index.

Headline KPI:

- long-window low-utilization percentage

Corroborating metrics:

- short-window low-utilization percentage
- long-window sampled Idle percentage
- long-window Idle entry count
- long-window average GPU utilization
The design intentionally treats low-utilization over time as the primary KPI, not instantaneous utilization. The default short and long windows are 60 seconds and 1200 seconds, but both are operator-configurable at runtime.

## Metric Semantics

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

### Supporting Metrics

- `avg_gpu_util_window`
- `avg_sm_clock_mhz_window`
- `avg_mem_clock_mhz_window`
- `avg_power_w_window`

These are supporting context, not the headline KPI.

### Distinctions That Matter

This repository explicitly distinguishes:

- cumulative low-utilization policy time
- current sampled Idle state
- software-derived idle entry counts

These are related but not interchangeable signals.

## Interpretation Guidance

The best operational read comes from the metrics together, not in isolation.

- High long-window low-utilization percentage suggests sustained or repeated time in documented low-utilization policy
- High long-window sampled Idle percentage suggests the GPU often looked idle when sampled
- High long-window Idle entry count suggests bursty scheduling or intermittent dispatch
- Moderate long-window average GPU utilization does not invalidate high low-utilization time; short bursts of work can coexist with meaningful low-util intervals
- Low-utilization is often consistent with workload starvation or underfeeding, but the tool measures observables rather than proving root cause

Common interpretations:

- High long-window low-utilization percentage + high long-window sampled Idle percentage: likely many idle or near-idle periods
- High long-window low-utilization percentage + lower long-window sampled Idle percentage: likely underfed, bursty, or bubble-heavy work rather than complete idleness
- Low long-window low-utilization percentage + high utilization + lower clocks: potentially power or thermal limitation rather than lack of work

## Limitations

- The Idle event reason may be deprecated or removed in future NVIDIA releases
- Low-utilization is not identical to zero work
- Underfeeding can come from many causes: host stalls, bubbles, sync gaps, small batches, bursty scheduling, and other pipeline effects
- `idle_entries_window` is derived in software by polling `Idle` transitions, not provided directly by NVIDIA
- Polling interval affects how many short idle episodes are observed
- This tool measures observables, not root-cause certainty
- The normalization of the low-utilization counter should still be validated on the target driver branch during hardware bring-up

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

Windows are time-based, not sample-count-based, so interval jitter is handled correctly. Short and long windows are configurable; 60 seconds and 1200 seconds are defaults only.

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

With optional Prometheus exporter support:

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

The `--window-short` and `--window-long` values are operator-configurable. The defaults are 60 seconds and 1200 seconds, but the semantics of the tool are not tied to those particular durations.

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
gpu idx | name | low_util_short(1m) | low_util_long(20m) | idle_pct_short(1m) | idle_pct_long(20m) | idle_entries_long(20m) | util_long(20m) | sm_clk_long(20m) | power_long(20m)
0 | NVIDIA H100 80GB HBM3 | 65.8 | 67.1 | 30.5 | 33.2 | 49 | 27.4 | 1008.8 | 216.1
1 | NVIDIA H200 141GB HBM3e | 2.0 | 2.0 | 0.0 | 0.0 | 0 | 96.0 | 1830.0 | 662.0
```

The example above uses the default windows. If you change `--window-short` or `--window-long`, the rendered labels change too.

### JSONL

See [examples/sample_output.jsonl](examples/sample_output.jsonl).

### CSV

See [examples/sample_summary.csv](examples/sample_summary.csv).

## Prometheus Metrics

If `--prometheus-port` is set and `prometheus-client` is installed, the exporter publishes configurable-window-aware metrics:

- `gpu_low_util_pct`
- `gpu_idle_reason_pct`
- `gpu_idle_entries`
- `gpu_avg_gpu_util`
- `gpu_avg_sm_clock_mhz`
- `gpu_avg_power_w`

These reflect the current rolling summaries and are labeled by GPU index, UUID, name, `window_role`, and `window_seconds`.

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

## References

- NVIDIA NVML API Reference Guide: [docs.nvidia.com/deploy/nvml-api](https://docs.nvidia.com/deploy/nvml-api/index.html)
- NVML field value enums and field IDs: [group__nvmlFieldValueEnums.html](https://docs.nvidia.com/deploy/nvml-api/group__nvmlFieldValueEnums.html)
- NVML clocks event reasons: [group__nvmlClocksEventReasons.html](https://docs.nvidia.com/deploy/nvml-api/group__nvmlClocksEventReasons.html)
- NVIDIA `nvidia-smi` documentation: [docs.nvidia.com/deploy/nvidia-smi](https://docs.nvidia.com/deploy/nvidia-smi/index.html)

These references are the basis for the repository's semantics:

- NVML is the underlying management interface used by `nvidia-smi`
- `NVML_FI_DEV_PERF_POLICY_LOW_UTILIZATION` is used as the primary low-utilization policy signal and therefore the basis of the headline long-window KPI
- Idle is treated as a current sampled event reason, not a cumulative timer
- NVIDIA documents that Idle-related event reporting may be deprecated in future releases
- `nvidia-smi` exposes clocks event reasons and clocks event reason counters, which helps operators validate related signals on target hosts

# Contributing

Thanks for helping improve `gpu-low-util-monitor`.

This repository aims to stay small, careful, and operationally useful. The best contributions are usually precise bug fixes, better hardware validation notes, sharper documentation, or additional simulation and test coverage for supported NVIDIA datacenter GPUs.

## What Helps Most

- field-support reports from real hardware such as H100, H200, A100, and similar datacenter GPUs
- fixes for documented NVML or output-semantics issues
- better tests for rolling-window math, unsupported fields, and power calibration behavior
- documentation improvements that make the repo clearer without overstating what the metrics mean

## Development

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,nvml]"
python -m pytest
```

If you do not have access to NVIDIA hardware, use simulation mode and the fake NVML backend to reproduce behavior locally.

## Contribution Style

- prefer documented NVIDIA signals over clever but unsupported heuristics
- keep wording scientifically careful
- treat short and long windows as configurable defaults, not fixed product truths
- preserve backward compatibility when the churn would outweigh the clarity gain

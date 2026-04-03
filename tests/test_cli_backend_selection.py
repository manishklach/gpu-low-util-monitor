from argparse import Namespace
from pathlib import Path

import pytest

from gpu_low_util_monitor.cli import build_backend
from gpu_low_util_monitor.dcgm_adapter import DcgmExporterBackend
from gpu_low_util_monitor.nvml_adapter import FakeNVMLBackend, RealNVMLBackend


def _args(**overrides: object) -> Namespace:
    base = {
        "simulate": False,
        "backend": "nvml",
        "fail_on_unsupported": False,
        "mig_mode": "auto",
        "dcgm_url": None,
        "dcgm_file": None,
        "dcgm_timeout": 5.0,
    }
    base.update(overrides)
    return Namespace(**base)


def test_build_backend_prefers_fake_backend_for_simulation() -> None:
    backend = build_backend(_args(simulate=True))
    assert isinstance(backend, FakeNVMLBackend)


def test_build_backend_selects_nvml_backend() -> None:
    backend = build_backend(_args(backend="nvml", mig_mode="gpu"))
    assert isinstance(backend, RealNVMLBackend)


def test_build_backend_selects_dcgm_backend_from_file(tmp_path: Path) -> None:
    metrics_file = tmp_path / "dcgm.prom"
    metrics_file.write_text("DCGM_FI_DEV_GPU_UTIL{gpu=\"0\",UUID=\"GPU-0\"} 10\n", encoding="utf-8")
    backend = build_backend(_args(backend="dcgm", dcgm_file=metrics_file))
    assert isinstance(backend, DcgmExporterBackend)


def test_build_backend_requires_dcgm_source() -> None:
    with pytest.raises(RuntimeError):
        build_backend(_args(backend="dcgm"))

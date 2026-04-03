from pathlib import Path

from gpu_low_util_monitor.collector import CollectorConfig, GPUCollector
from gpu_low_util_monitor.dcgm_adapter import DcgmExporterBackend, FileMetricsSource


def test_dcgm_backend_maps_supported_metrics_and_degrades_unsupported(tmp_path: Path) -> None:
    metrics_path = tmp_path / "dcgm.prom"
    metrics_path.write_text(
        """
        # HELP DCGM_FI_DEV_GPU_UTIL GPU util
        DCGM_FI_DEV_GPU_UTIL{gpu="0",UUID="GPU-0",device="nvidia0",modelName="NVIDIA H100 80GB HBM3"} 37
        DCGM_FI_DEV_SM_CLOCK{gpu="0",UUID="GPU-0",device="nvidia0",modelName="NVIDIA H100 80GB HBM3"} 1230
        DCGM_FI_DEV_MEM_CLOCK{gpu="0",UUID="GPU-0",device="nvidia0",modelName="NVIDIA H100 80GB HBM3"} 1593
        DCGM_FI_DEV_POWER_USAGE{gpu="0",UUID="GPU-0",device="nvidia0",modelName="NVIDIA H100 80GB HBM3"} 245
        DCGM_FI_DEV_POWER_MGMT_LIMIT{gpu="0",UUID="GPU-0",device="nvidia0",modelName="NVIDIA H100 80GB HBM3"} 700
        DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION{gpu="0",UUID="GPU-0",device="nvidia0",modelName="NVIDIA H100 80GB HBM3"} 1000
        """,
        encoding="utf-8",
    )

    ticks = iter([0, 1_000_000_000])
    collector = GPUCollector(
        DcgmExporterBackend(FileMetricsSource(metrics_path)),
        CollectorConfig(interval_seconds=1.0, window_short_seconds=60, window_long_seconds=1200),
        monotonic_ns_fn=lambda: next(ticks),
    )
    collector.initialize()
    collector.poll_once()
    reports = collector.poll_once()

    report = reports[0]
    assert report.sample.gpu_util_pct == 37.0
    assert report.sample.power_w == 245.0
    assert report.sample.capabilities.low_util_counter is False
    assert report.sample.capabilities.idle_reason is False
    assert report.long_summary.low_util_pct_window is None
    assert report.long_summary.idle_reason_pct_window is None
    assert report.long_summary.avg_power_w_window == 245.0


def test_dcgm_backend_can_enumerate_mig_entities(tmp_path: Path) -> None:
    metrics_path = tmp_path / "dcgm_mig.prom"
    metrics_path.write_text(
        """
        DCGM_FI_DEV_GPU_UTIL{gpu="0",UUID="GPU-parent-0",device="nvidia0",modelName="NVIDIA H100 80GB HBM3",GPU_I_ID="5",GPU_I_PROFILE="1g.10gb"} 55
        DCGM_FI_DEV_POWER_USAGE{gpu="0",UUID="GPU-parent-0",device="nvidia0",modelName="NVIDIA H100 80GB HBM3",GPU_I_ID="5",GPU_I_PROFILE="1g.10gb"} 110
        """,
        encoding="utf-8",
    )

    backend = DcgmExporterBackend(FileMetricsSource(metrics_path), mig_strategy="auto")
    backend.initialize()
    identities = backend.device_identities()

    assert len(identities) == 1
    assert identities[0].entity_kind == "mig"
    assert identities[0].parent_uuid == "GPU-parent-0"
    assert identities[0].mig_instance_id == "5"

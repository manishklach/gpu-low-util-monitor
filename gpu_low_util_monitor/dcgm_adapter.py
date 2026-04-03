"""DCGM exporter ingest backend.

This backend is intentionally pragmatic: it ingests documented DCGM field
metrics from either a Prometheus-style exporter endpoint or a metrics file.
It does not attempt to reproduce every NVML-only signal. Unsupported metrics
are surfaced as unavailable rather than guessed.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Protocol
from urllib.request import urlopen

from gpu_low_util_monitor.models import DeviceCapabilities, DeviceIdentity, DeviceSample
from gpu_low_util_monitor.util import utc_now_iso

LOGGER = logging.getLogger(__name__)

_LINE_RE = re.compile(
    r"^(?P<metric>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(?P<labels>.*)\})?\s+(?P<value>[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)$"
)
_LABEL_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)="((?:\\.|[^"])*)"')


class MetricsSource(Protocol):
    """Protocol for retrieving a Prometheus exposition payload."""

    def read_text(self) -> str:
        """Return the latest exposition payload."""


class UrlMetricsSource:
    """Fetch metrics from an HTTP endpoint."""

    def __init__(self, url: str, timeout_seconds: float = 5.0) -> None:
        self._url = url
        self._timeout_seconds = timeout_seconds

    def read_text(self) -> str:
        """Fetch the current exposition payload."""
        with urlopen(self._url, timeout=self._timeout_seconds) as response:  # noqa: S310
            return response.read().decode("utf-8")


class FileMetricsSource:
    """Read metrics from a local text file."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def read_text(self) -> str:
        """Read the current exposition payload."""
        return self._path.read_text(encoding="utf-8")


class DcgmExporterBackend:
    """Ingest documented DCGM exporter metrics as a degraded backend mode."""

    def __init__(self, source: MetricsSource, mig_strategy: str = "auto") -> None:
        self._source = source
        self._mig_strategy = mig_strategy
        self._identities: list[DeviceIdentity] = []
        self._snapshot: dict[str, dict[str, float | str | None]] = {}
        self._last_monotonic_ns: int | None = None

    def initialize(self) -> None:
        """Load the first snapshot and enumerate identities."""
        self._refresh_snapshot()

    def shutdown(self) -> None:
        """No-op for DCGM exporter ingestion."""

    def device_identities(self) -> list[DeviceIdentity]:
        """Return the currently enumerated DCGM entities."""
        return list(self._identities)

    def read_device_sample(self, identity: DeviceIdentity, monotonic_ns: int) -> DeviceSample:
        """Convert the current DCGM snapshot into a device sample."""
        if self._last_monotonic_ns != monotonic_ns:
            self._refresh_snapshot()
            self._last_monotonic_ns = monotonic_ns
        metrics = self._snapshot[identity.uuid]
        capabilities = DeviceCapabilities(
            low_util_counter=False,
            idle_reason=False,
            thermal_limit=False,
            power_limit=False,
            mem_clock=metrics.get("mem_clock_mhz") is not None,
            power_cap=metrics.get("power_cap_w") is not None,
            total_energy=metrics.get("total_energy_joules") is not None,
        )
        return DeviceSample(
            identity=identity,
            monotonic_ns=monotonic_ns,
            wall_time_iso=utc_now_iso(),
            gpu_util_pct=_as_float(metrics.get("gpu_util_pct")),
            sm_clock_mhz=_as_float(metrics.get("sm_clock_mhz")),
            mem_clock_mhz=_as_float(metrics.get("mem_clock_mhz")),
            power_w=_as_float(metrics.get("power_w")),
            power_cap_w=_as_float(metrics.get("power_cap_w")),
            total_energy_joules=_as_float(metrics.get("total_energy_joules")),
            idle_reason_active=None,
            thermal_limit_active=None,
            power_limit_active=None,
            low_util_counter_ns=None,
            capabilities=capabilities,
        )

    def _refresh_snapshot(self) -> None:
        """Refresh the parsed exporter snapshot."""
        text = self._source.read_text()
        records = _parse_prometheus_text(text)
        snapshot: dict[str, dict[str, float | str | None]] = {}
        identities: dict[str, DeviceIdentity] = {}
        for metric_name, labels, value in records:
            identity = self._identity_from_labels(labels)
            if identity is None:
                continue
            identities[identity.uuid] = identity
            entity = snapshot.setdefault(identity.uuid, {})
            if metric_name == "DCGM_FI_DEV_GPU_UTIL":
                entity["gpu_util_pct"] = value
            elif metric_name == "DCGM_FI_DEV_SM_CLOCK":
                entity["sm_clock_mhz"] = value
            elif metric_name == "DCGM_FI_DEV_MEM_CLOCK":
                entity["mem_clock_mhz"] = value
            elif metric_name in {"DCGM_FI_DEV_POWER_USAGE_INSTANT", "DCGM_FI_DEV_POWER_USAGE"}:
                existing = entity.get("power_w")
                if metric_name == "DCGM_FI_DEV_POWER_USAGE_INSTANT" or existing is None:
                    entity["power_w"] = value
            elif metric_name == "DCGM_FI_DEV_POWER_MGMT_LIMIT":
                entity["power_cap_w"] = value
            elif metric_name == "DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION":
                entity["total_energy_joules"] = value
        if not identities:
            raise RuntimeError("No DCGM device metrics found in exporter payload")
        self._identities = list(identities.values())
        self._snapshot = snapshot

    def _identity_from_labels(self, labels: dict[str, str]) -> DeviceIdentity | None:
        """Build an identity from DCGM exporter labels."""
        raw_gpu = labels.get("gpu") or labels.get("GPU")
        parent_uuid = labels.get("UUID") or labels.get("uuid")
        name = labels.get("modelName") or labels.get("name") or labels.get("device") or "NVIDIA GPU"
        gpu_index = _parse_gpu_index(raw_gpu)
        mig_id = labels.get("GPU_I_ID") or labels.get("gpu_i_id")
        mig_profile = labels.get("GPU_I_PROFILE") or labels.get("gpu_i_profile")

        if mig_id and self._mig_strategy != "gpu":
            if not parent_uuid:
                parent_uuid = f"GPU-{gpu_index}"
            mig_uuid = f"{parent_uuid}/MIG-{mig_id}"
            mig_name = f"{name} MIG {mig_profile}" if mig_profile else f"{name} MIG {mig_id}"
            return DeviceIdentity(
                index=gpu_index,
                uuid=mig_uuid,
                name=mig_name,
                entity_kind="mig",
                parent_uuid=parent_uuid,
                mig_instance_id=mig_id,
                mig_profile=mig_profile,
            )

        if self._mig_strategy == "mig" and mig_id is None:
            return None
        if not parent_uuid:
            parent_uuid = f"GPU-{gpu_index}"
        return DeviceIdentity(
            index=gpu_index,
            uuid=parent_uuid,
            name=name,
            entity_kind="gpu",
        )


def _parse_prometheus_text(text: str) -> list[tuple[str, dict[str, str], float]]:
    """Parse a compact subset of Prometheus exposition text."""
    records: list[tuple[str, dict[str, str], float]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _LINE_RE.match(stripped)
        if match is None:
            continue
        labels: dict[str, str] = {}
        labels_text = match.group("labels")
        if labels_text:
            for key, value in _LABEL_RE.findall(labels_text):
                labels[key] = bytes(value, "utf-8").decode("unicode_escape")
        records.append((match.group("metric"), labels, float(match.group("value"))))
    return records


def _parse_gpu_index(raw_gpu: str | None) -> int:
    """Best-effort parse of the GPU index from exporter labels."""
    if raw_gpu is None:
        return -1
    digits = "".join(char for char in raw_gpu if char.isdigit())
    return int(digits) if digits else -1


def _as_float(value: float | str | None) -> float | None:
    """Convert a parsed metric value to float when present."""
    if value is None:
        return None
    return float(value)

"""Power-focused helpers for calibration, normalization, and interpretation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from gpu_low_util_monitor.models import DeviceIdentity
from gpu_low_util_monitor.util import clamp


@dataclass(frozen=True)
class PowerCalibration:
    """Calibration inputs for normalized power activity."""

    idle_baseline_w: float
    busy_reference_w: float

    def is_valid(self) -> bool:
        """Return whether the calibration can produce a meaningful normalization."""
        return self.idle_baseline_w >= 0.0 and self.busy_reference_w > self.idle_baseline_w


@dataclass(frozen=True)
class PowerCalibrationStore:
    """Calibration defaults and optional per-GPU overrides."""

    default: PowerCalibration | None = None
    by_uuid: dict[str, PowerCalibration] | None = None
    by_name_prefix: dict[str, PowerCalibration] | None = None

    def resolve(self, identity: DeviceIdentity) -> PowerCalibration | None:
        """Resolve the most specific calibration available for a GPU."""
        uuid_overrides = self.by_uuid or {}
        if identity.uuid in uuid_overrides:
            calibration = uuid_overrides[identity.uuid]
            return calibration if calibration.is_valid() else None

        prefix_overrides = self.by_name_prefix or {}
        for prefix, calibration in prefix_overrides.items():
            if identity.name.startswith(prefix):
                return calibration if calibration.is_valid() else None

        if self.default is not None and self.default.is_valid():
            return self.default
        return None


def load_power_calibration_store(
    path: Path | None,
    cli_idle_baseline_w: float | None,
    cli_busy_reference_w: float | None,
) -> PowerCalibrationStore:
    """Load calibration defaults and overrides from CLI and an optional JSON file."""
    file_payload: dict[str, object] = {}
    if path is not None:
        file_payload = json.loads(path.read_text(encoding="utf-8"))

    file_default = _parse_calibration_payload(file_payload.get("default"))
    cli_default = (
        PowerCalibration(idle_baseline_w=cli_idle_baseline_w, busy_reference_w=cli_busy_reference_w)
        if cli_idle_baseline_w is not None and cli_busy_reference_w is not None
        else None
    )

    return PowerCalibrationStore(
        default=cli_default or file_default,
        by_uuid=_parse_override_block(file_payload.get("by_uuid")),
        by_name_prefix=_parse_override_block(file_payload.get("by_name_prefix")),
    )


def compute_power_activity_pct(avg_power_w: float | None, calibration: PowerCalibration | None) -> float | None:
    """Compute a normalized power activity proxy from calibrated bounds."""
    if avg_power_w is None or calibration is None or not calibration.is_valid():
        return None
    normalized = 100.0 * (avg_power_w - calibration.idle_baseline_w) / (
        calibration.busy_reference_w - calibration.idle_baseline_w
    )
    return round(clamp(normalized, 0.0, 100.0), 3)


def compute_power_pct_of_cap(avg_power_w: float | None, avg_power_cap_w: float | None) -> float | None:
    """Compute rolling average power as a percentage of rolling average power cap."""
    if avg_power_w is None or avg_power_cap_w is None or avg_power_cap_w <= 0.0:
        return None
    return round(clamp(100.0 * avg_power_w / avg_power_cap_w, 0.0, 100.0), 3)


def _parse_override_block(payload: object) -> dict[str, PowerCalibration]:
    """Parse a mapping of override identifiers to calibrations."""
    if not isinstance(payload, dict):
        return {}
    parsed: dict[str, PowerCalibration] = {}
    for key, value in payload.items():
        calibration = _parse_calibration_payload(value)
        if calibration is not None:
            parsed[str(key)] = calibration
    return parsed


def _parse_calibration_payload(payload: object) -> PowerCalibration | None:
    """Parse one calibration object from JSON-like input."""
    if not isinstance(payload, dict):
        return None
    idle = payload.get("idle_baseline_w")
    busy = payload.get("busy_reference_w")
    if not isinstance(idle, (int, float)) or not isinstance(busy, (int, float)):
        return None
    calibration = PowerCalibration(idle_baseline_w=float(idle), busy_reference_w=float(busy))
    return calibration if calibration.is_valid() else None

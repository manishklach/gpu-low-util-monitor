"""Data models for GPU low-utilization monitoring."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class DeviceIdentity:
    """Static identity for one GPU."""

    index: int
    uuid: str
    name: str


@dataclass(frozen=True)
class DeviceCapabilities:
    """Availability flags for optional fields on a GPU."""

    low_util_counter: bool = True
    idle_reason: bool = True
    thermal_limit: bool = True
    power_limit: bool = True
    mem_clock: bool = True
    power_cap: bool = True
    total_energy: bool = True

    def to_dict(self) -> dict[str, bool]:
        """Return a stable JSON-serializable mapping."""
        return asdict(self)


@dataclass(frozen=True)
class DeviceSample:
    """One poll result for a GPU."""

    identity: DeviceIdentity
    monotonic_ns: int
    wall_time_iso: str
    gpu_util_pct: float | None
    sm_clock_mhz: float | None
    mem_clock_mhz: float | None
    power_w: float | None
    power_cap_w: float | None
    total_energy_joules: float | None
    idle_reason_active: bool | None
    thermal_limit_active: bool | None
    power_limit_active: bool | None
    low_util_counter_ns: int | None
    capabilities: DeviceCapabilities


@dataclass(frozen=True)
class WindowSummary:
    """Rolling summary over a time window."""

    window_seconds: int
    sample_count: int
    low_util_pct_window: float | None
    idle_reason_pct_window: float | None
    idle_entries_window: int | None
    thermal_limit_pct_window: float | None
    power_limit_pct_window: float | None
    avg_gpu_util_window: float | None
    avg_sm_clock_mhz_window: float | None
    avg_mem_clock_mhz_window: float | None
    avg_power_w_window: float | None
    power_pct_of_cap_window: float | None
    energy_joules_window: float | None
    power_activity_pct_window: float | None

    def to_public_dict(self) -> dict[str, Any]:
        """Return the summary fields intended for external output."""
        return {
            "low_util_pct_window": self.low_util_pct_window,
            "idle_reason_pct_window": self.idle_reason_pct_window,
            "idle_entries_window": self.idle_entries_window,
            "thermal_limit_pct_window": self.thermal_limit_pct_window,
            "power_limit_pct_window": self.power_limit_pct_window,
            "avg_gpu_util_window": self.avg_gpu_util_window,
            "avg_sm_clock_mhz_window": self.avg_sm_clock_mhz_window,
            "avg_mem_clock_mhz_window": self.avg_mem_clock_mhz_window,
            "avg_power_w_window": self.avg_power_w_window,
            "power_pct_of_cap_window": self.power_pct_of_cap_window,
            "energy_joules_window": self.energy_joules_window,
            "power_activity_pct_window": self.power_activity_pct_window,
        }


@dataclass(frozen=True)
class SampleReport:
    """One output record combining a current sample and rolling summaries."""

    sample: DeviceSample
    short_summary: WindowSummary
    long_summary: WindowSummary

    def to_json_dict(self) -> dict[str, Any]:
        """Convert the report into a JSONL-friendly dictionary.

        The payload includes both role-based keys (`summary_short`, `summary_long`)
        and explicit duration keys (`summary_60s`, `summary_1200s`, etc.) so that
        downstream consumers can rely on operator-configured windows without
        treating the default durations as fixed product semantics.
        """
        short_key = f"summary_{self.short_summary.window_seconds}s"
        long_key = f"summary_{self.long_summary.window_seconds}s"
        return {
            "wall_time_iso": self.sample.wall_time_iso,
            "gpu_index": self.sample.identity.index,
            "uuid": self.sample.identity.uuid,
            "name": self.sample.identity.name,
            "timestamp_ns": self.sample.monotonic_ns,
            "sample": {
                "gpu_util_pct": self.sample.gpu_util_pct,
                "sm_clock_mhz": self.sample.sm_clock_mhz,
                "mem_clock_mhz": self.sample.mem_clock_mhz,
                "current_power_w": self.sample.power_w,
                "power_w": self.sample.power_w,
                "power_cap_w": self.sample.power_cap_w,
                "total_energy_joules": self.sample.total_energy_joules,
                "idle_reason_active": self.sample.idle_reason_active,
                "thermal_limit_active": self.sample.thermal_limit_active,
                "power_limit_active": self.sample.power_limit_active,
                "low_util_counter_ns": self.sample.low_util_counter_ns,
            },
            "summary_short": self.short_summary.to_public_dict(),
            "summary_long": self.long_summary.to_public_dict(),
            short_key: self.short_summary.to_public_dict(),
            long_key: self.long_summary.to_public_dict(),
            "availability": self.sample.capabilities.to_dict(),
        }

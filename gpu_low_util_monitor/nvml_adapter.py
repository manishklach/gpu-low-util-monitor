"""NVML access layer and a fake backend for simulation/testing."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from gpu_low_util_monitor.models import DeviceCapabilities, DeviceIdentity, DeviceSample
from gpu_low_util_monitor.util import utc_now_iso

LOGGER = logging.getLogger(__name__)


class NVMLBackend(Protocol):
    """Protocol implemented by real and fake backends."""

    def initialize(self) -> None:
        """Initialize backend state."""

    def shutdown(self) -> None:
        """Release backend state."""

    def device_identities(self) -> list[DeviceIdentity]:
        """Return the visible GPUs."""

    def read_device_sample(self, identity: DeviceIdentity, monotonic_ns: int) -> DeviceSample:
        """Read one sample for the target GPU."""


class UnsupportedFieldError(RuntimeError):
    """Raised when a requested field is unsupported."""


class RealNVMLBackend:
    """Documented-NVML backend using `nvidia-ml-py` when available."""

    def __init__(self, fail_on_unsupported: bool = False) -> None:
        self._fail_on_unsupported = fail_on_unsupported
        self._handles: dict[int, object] = {}
        self._warned_once: set[tuple[int, str]] = set()
        self._pynvml = None

    def initialize(self) -> None:
        """Import NVML bindings and initialize the library."""
        try:
            import pynvml  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "pynvml is not installed. Install with `pip install -e \".[nvml]\"` or use --simulate."
            ) from exc
        self._pynvml = pynvml
        try:
            pynvml.nvmlInit()
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"Failed to initialize NVML: {exc}") from exc
        for index in range(pynvml.nvmlDeviceGetCount()):
            self._handles[index] = pynvml.nvmlDeviceGetHandleByIndex(index)

    def shutdown(self) -> None:
        """Shutdown NVML if it was initialized."""
        if self._pynvml is None:
            return
        try:
            self._pynvml.nvmlShutdown()
        except Exception:  # pragma: no cover
            LOGGER.debug("Ignoring NVML shutdown failure", exc_info=True)

    def device_identities(self) -> list[DeviceIdentity]:
        """Return visible devices."""
        if self._pynvml is None:
            raise RuntimeError("NVML backend not initialized")
        identities: list[DeviceIdentity] = []
        for index, handle in self._handles.items():
            name = self._decode(self._pynvml.nvmlDeviceGetName(handle))
            uuid = self._decode(self._pynvml.nvmlDeviceGetUUID(handle))
            identities.append(DeviceIdentity(index=index, uuid=uuid, name=name))
        return identities

    def read_device_sample(self, identity: DeviceIdentity, monotonic_ns: int) -> DeviceSample:
        """Read one GPU sample using documented APIs and field ids."""
        if self._pynvml is None:
            raise RuntimeError("NVML backend not initialized")
        pynvml = self._pynvml
        handle = self._handles[identity.index]

        capabilities = DeviceCapabilities()

        util_pct = None
        sm_clock = None
        mem_clock = None
        power_w = None
        power_cap_w = None
        total_energy_joules = None
        idle_reason_active = None
        thermal_limit_active = None
        power_limit_active = None
        low_util_counter_ns = None

        try:
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            util_pct = float(util.gpu)
        except Exception:
            util_pct = None

        try:
            sm_clock = float(pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_SM))
        except Exception:
            sm_clock = None

        try:
            mem_clock = float(pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_MEM))
        except Exception as exc:
            capabilities = DeviceCapabilities(
                low_util_counter=capabilities.low_util_counter,
                idle_reason=capabilities.idle_reason,
                mem_clock=False,
            )
            self._warn_unsupported(identity.index, "mem_clock", exc)

        try:
            power_w = float(pynvml.nvmlDeviceGetPowerUsage(handle)) / 1000.0
        except Exception:
            power_w = None

        try:
            power_cap_w = self._read_power_cap_w(handle)
        except Exception as exc:
            capabilities = DeviceCapabilities(
                low_util_counter=capabilities.low_util_counter,
                idle_reason=capabilities.idle_reason,
                mem_clock=capabilities.mem_clock,
                power_cap=False,
                total_energy=capabilities.total_energy,
            )
            self._warn_unsupported(identity.index, "power_cap", exc)

        try:
            total_energy_joules = self._read_total_energy_joules(handle)
        except Exception as exc:
            capabilities = DeviceCapabilities(
                low_util_counter=capabilities.low_util_counter,
                idle_reason=capabilities.idle_reason,
                mem_clock=capabilities.mem_clock,
                power_cap=capabilities.power_cap,
                total_energy=False,
            )
            self._warn_unsupported(identity.index, "total_energy", exc)

        try:
            idle_reason_active = self._read_idle_reason(handle)
        except Exception as exc:
            capabilities = DeviceCapabilities(
                low_util_counter=capabilities.low_util_counter,
                idle_reason=False,
                thermal_limit=capabilities.thermal_limit,
                power_limit=capabilities.power_limit,
                mem_clock=capabilities.mem_clock,
                power_cap=capabilities.power_cap,
                total_energy=capabilities.total_energy,
            )
            self._warn_unsupported(identity.index, "idle_reason", exc)
            idle_reason_active = None

        try:
            thermal_limit_active = self._read_reason_mask_state(
                handle,
                (
                    "nvmlClocksEventReasonSwThermalSlowdown",
                    "nvmlClocksEventReasonHwThermalSlowdown",
                    "nvmlClocksThrottleReasonSwThermalSlowdown",
                    "nvmlClocksThrottleReasonHwThermalSlowdown",
                ),
            )
        except Exception as exc:
            capabilities = DeviceCapabilities(
                low_util_counter=capabilities.low_util_counter,
                idle_reason=capabilities.idle_reason,
                thermal_limit=False,
                power_limit=capabilities.power_limit,
                mem_clock=capabilities.mem_clock,
                power_cap=capabilities.power_cap,
                total_energy=capabilities.total_energy,
            )
            self._warn_unsupported(identity.index, "thermal_limit", exc)
            thermal_limit_active = None

        try:
            power_limit_active = self._read_reason_mask_state(
                handle,
                (
                    "nvmlClocksEventReasonSwPowerCap",
                    "nvmlClocksEventReasonHwPowerBrakeSlowdown",
                    "nvmlClocksThrottleReasonSwPowerCap",
                    "nvmlClocksThrottleReasonHwPowerBrakeSlowdown",
                ),
            )
        except Exception as exc:
            capabilities = DeviceCapabilities(
                low_util_counter=capabilities.low_util_counter,
                idle_reason=capabilities.idle_reason,
                thermal_limit=capabilities.thermal_limit,
                power_limit=False,
                mem_clock=capabilities.mem_clock,
                power_cap=capabilities.power_cap,
                total_energy=capabilities.total_energy,
            )
            self._warn_unsupported(identity.index, "power_limit", exc)
            power_limit_active = None

        try:
            low_util_counter_ns = self._read_low_util_counter_ns(handle)
        except Exception as exc:
            capabilities = DeviceCapabilities(
                low_util_counter=False,
                idle_reason=capabilities.idle_reason,
                thermal_limit=capabilities.thermal_limit,
                power_limit=capabilities.power_limit,
                mem_clock=capabilities.mem_clock,
                power_cap=capabilities.power_cap,
                total_energy=capabilities.total_energy,
            )
            self._warn_unsupported(identity.index, "low_util_counter", exc)
            low_util_counter_ns = None

        return DeviceSample(
            identity=identity,
            monotonic_ns=monotonic_ns,
            wall_time_iso=utc_now_iso(),
            gpu_util_pct=util_pct,
            sm_clock_mhz=sm_clock,
            mem_clock_mhz=mem_clock,
            power_w=power_w,
            power_cap_w=power_cap_w,
            total_energy_joules=total_energy_joules,
            idle_reason_active=idle_reason_active,
            thermal_limit_active=thermal_limit_active,
            power_limit_active=power_limit_active,
            low_util_counter_ns=low_util_counter_ns,
            capabilities=capabilities,
        )

    def _read_low_util_counter_ns(self, handle: object) -> int:
        """Read the documented low-utilization perf-policy counter.

        NVML exposes the field through `nvmlDeviceGetFieldValues` without an explicit
        unit annotation in the field-id enum docs. The implementation normalizes the
        returned value to nanoseconds for the rolling-window math used elsewhere in
        the repository, matching the time-based semantics of NVML perf-policy
        violation data. Operators should validate the observed scale on their target
        driver branch during hardware bring-up.
        """
        pynvml = self._pynvml
        assert pynvml is not None
        values = pynvml.nvmlDeviceGetFieldValues(handle, [pynvml.NVML_FI_DEV_PERF_POLICY_LOW_UTILIZATION])
        field_value = values[0]
        if field_value.nvmlReturn != pynvml.NVML_SUCCESS:
            raise UnsupportedFieldError(f"Field query failed with nvmlReturn={field_value.nvmlReturn}")
        return int(field_value.value.uiVal) * 1000

    def _read_idle_reason(self, handle: object) -> bool:
        """Read whether the Idle clocks-event reason is active.

        This is a sampled instantaneous state, not a cumulative timer. NVIDIA also
        documents that Idle-related clock-event reporting may be deprecated in future
        releases, so callers must tolerate this signal being unavailable.
        """
        pynvml = self._pynvml
        assert pynvml is not None
        return self._read_reason_mask_state(handle, ("nvmlClocksEventReasonIdle", "nvmlClocksThrottleReasonGpuIdle"))

    def _read_reason_mask_state(self, handle: object, constant_names: tuple[str, ...]) -> bool:
        """Read whether any documented clock-event/throttle reason bit is active."""
        pynvml = self._pynvml
        assert pynvml is not None
        if hasattr(pynvml, "nvmlDeviceGetCurrentClocksEventReasons"):
            mask = int(pynvml.nvmlDeviceGetCurrentClocksEventReasons(handle))
        elif hasattr(pynvml, "nvmlDeviceGetCurrentClocksThrottleReasons"):
            mask = int(pynvml.nvmlDeviceGetCurrentClocksThrottleReasons(handle))
        else:
            raise UnsupportedFieldError("Current clocks event reasons API is unavailable")

        available_masks = [
            int(getattr(pynvml, constant_name))
            for constant_name in constant_names
            if hasattr(pynvml, constant_name)
        ]
        if not available_masks:
            raise UnsupportedFieldError(f"Reason bit constant unavailable for any of: {constant_names}")
        return any(mask & candidate for candidate in available_masks)

    def _read_power_cap_w(self, handle: object) -> float:
        """Read the enforced or configured power cap in watts when available."""
        pynvml = self._pynvml
        assert pynvml is not None
        if hasattr(pynvml, "nvmlDeviceGetEnforcedPowerLimit"):
            return float(pynvml.nvmlDeviceGetEnforcedPowerLimit(handle)) / 1000.0
        if hasattr(pynvml, "nvmlDeviceGetPowerManagementLimit"):
            return float(pynvml.nvmlDeviceGetPowerManagementLimit(handle)) / 1000.0
        raise UnsupportedFieldError("Power cap query API is unavailable")

    def _read_total_energy_joules(self, handle: object) -> float:
        """Read cumulative total energy consumption in joules when available."""
        pynvml = self._pynvml
        assert pynvml is not None
        if not hasattr(pynvml, "nvmlDeviceGetTotalEnergyConsumption"):
            raise UnsupportedFieldError("Total energy consumption API is unavailable")
        # NVML documents this API in millijoules on supported platforms.
        return float(pynvml.nvmlDeviceGetTotalEnergyConsumption(handle)) / 1000.0

    def _warn_unsupported(self, gpu_index: int, field_name: str, exc: Exception) -> None:
        """Warn once per GPU/field or raise in strict mode."""
        if self._fail_on_unsupported:
            raise UnsupportedFieldError(f"GPU {gpu_index} field {field_name} unsupported: {exc}") from exc
        key = (gpu_index, field_name)
        if key not in self._warned_once:
            LOGGER.warning("GPU %s field %s unavailable: %s", gpu_index, field_name, exc)
            self._warned_once.add(key)

    @staticmethod
    def _decode(value: bytes | str) -> str:
        """Decode NVML byte strings."""
        return value.decode("utf-8") if isinstance(value, bytes) else value


@dataclass(frozen=True)
class SimulationScenario:
    """Simulation configuration for one fake GPU."""

    identity: DeviceIdentity
    kind: str


class FakeNVMLBackend:
    """Synthetic backend that produces realistic-looking sample streams."""

    def __init__(self, scenarios: list[str] | None = None) -> None:
        scenario_names = scenarios or [
                "fully-idle",
                "steady-busy",
                "bursty",
                "underfed",
                "power-limited-busy",
                "thermal-limited-busy",
            ]
        default_names = [
            "NVIDIA H100 80GB HBM3",
            "NVIDIA H200 141GB HBM3e",
            "NVIDIA H100 80GB HBM3",
            "NVIDIA H200 141GB HBM3e",
            "NVIDIA H100 80GB HBM3",
        ]
        self._scenarios = [
            SimulationScenario(
                identity=DeviceIdentity(index=index, uuid=f"GPU-sim-{index:04d}", name=default_names[index % len(default_names)]),
                kind=name,
            )
            for index, name in enumerate(scenario_names)
        ]
        self._state: dict[int, dict[str, float | int]] = {}

    def initialize(self) -> None:
        """Initialize fake device state."""
        for scenario in self._scenarios:
            self._state[scenario.identity.index] = {
                "last_ts_ns": 0,
                "low_util_counter_ns": 0,
                "total_energy_joules": 0.0,
                "phase": 0,
            }

    def shutdown(self) -> None:
        """No-op for the fake backend."""

    def device_identities(self) -> list[DeviceIdentity]:
        """Return simulated devices."""
        return [scenario.identity for scenario in self._scenarios]

    def read_device_sample(self, identity: DeviceIdentity, monotonic_ns: int) -> DeviceSample:
        """Generate a synthetic sample for one device."""
        scenario = next(item for item in self._scenarios if item.identity.index == identity.index)
        state = self._state[identity.index]
        last_ts_ns = int(state["last_ts_ns"])
        elapsed_ns = monotonic_ns - last_ts_ns if last_ts_ns else 1_000_000_000
        elapsed_s = elapsed_ns / 1_000_000_000
        phase = int(state["phase"])

        metrics = self._simulate_metrics(scenario.kind, phase)
        low_util_counter_ns = int(state["low_util_counter_ns"]) + int(metrics["low_util_fraction"] * elapsed_ns)
        total_energy_joules = float(state["total_energy_joules"]) + float(metrics["power_w"]) * elapsed_s

        state["last_ts_ns"] = monotonic_ns
        state["low_util_counter_ns"] = low_util_counter_ns
        state["total_energy_joules"] = total_energy_joules
        state["phase"] = phase + max(1, round(elapsed_s))

        capabilities = DeviceCapabilities(
            low_util_counter=True,
            idle_reason=metrics["idle_reason_active"] is not None,
            mem_clock=metrics["mem_clock_mhz"] is not None,
            power_cap=metrics["power_cap_w"] is not None,
            total_energy=True,
            thermal_limit=metrics["thermal_limit_active"] is not None,
            power_limit=metrics["power_limit_active"] is not None,
        )

        return DeviceSample(
            identity=identity,
            monotonic_ns=monotonic_ns,
            wall_time_iso=utc_now_iso(),
            gpu_util_pct=float(metrics["gpu_util_pct"]) if metrics["gpu_util_pct"] is not None else None,
            sm_clock_mhz=float(metrics["sm_clock_mhz"]) if metrics["sm_clock_mhz"] is not None else None,
            mem_clock_mhz=float(metrics["mem_clock_mhz"]) if metrics["mem_clock_mhz"] is not None else None,
            power_w=float(metrics["power_w"]) if metrics["power_w"] is not None else None,
            power_cap_w=float(metrics["power_cap_w"]) if metrics["power_cap_w"] is not None else None,
            total_energy_joules=total_energy_joules,
            idle_reason_active=bool(metrics["idle_reason_active"]) if metrics["idle_reason_active"] is not None else None,
            thermal_limit_active=bool(metrics["thermal_limit_active"]) if metrics["thermal_limit_active"] is not None else None,
            power_limit_active=bool(metrics["power_limit_active"]) if metrics["power_limit_active"] is not None else None,
            low_util_counter_ns=low_util_counter_ns,
            capabilities=capabilities,
        )

    def _simulate_metrics(self, kind: str, phase: int) -> dict[str, float | bool | None]:
        """Generate scenario-specific metrics."""
        bursty_active = (phase // 5) % 2 == 0
        if kind == "fully-idle":
            return {
                "gpu_util_pct": 0.0,
                "sm_clock_mhz": 210.0,
                "mem_clock_mhz": 405.0,
                "power_w": 78.0,
                "power_cap_w": 700.0,
                "idle_reason_active": True,
                "thermal_limit_active": False,
                "power_limit_active": False,
                "low_util_fraction": 1.0,
            }
        if kind == "steady-busy":
            return {
                "gpu_util_pct": 96.0,
                "sm_clock_mhz": 1830.0,
                "mem_clock_mhz": 1593.0,
                "power_w": 662.0,
                "power_cap_w": 700.0,
                "idle_reason_active": False,
                "thermal_limit_active": False,
                "power_limit_active": False,
                "low_util_fraction": 0.02,
            }
        if kind == "bursty":
            return {
                "gpu_util_pct": 72.0 if bursty_active else 0.0,
                "sm_clock_mhz": 1590.0 if bursty_active else 210.0,
                "mem_clock_mhz": 1593.0,
                "power_w": 518.0 if bursty_active else 92.0,
                "power_cap_w": 700.0,
                "idle_reason_active": not bursty_active,
                "thermal_limit_active": False,
                "power_limit_active": False,
                "low_util_fraction": 0.12 if bursty_active else 1.0,
            }
        if kind == "underfed":
            return {
                "gpu_util_pct": 24.0 + (phase % 6) * 3.0,
                "sm_clock_mhz": 960.0 + (phase % 4) * 40.0,
                "mem_clock_mhz": 1593.0,
                "power_w": 205.0 + (phase % 5) * 6.0,
                "power_cap_w": 700.0,
                "idle_reason_active": phase % 7 in (0, 1),
                "thermal_limit_active": False,
                "power_limit_active": False,
                "low_util_fraction": 0.72,
            }
        if kind == "power-limited-busy":
            return {
                "gpu_util_pct": 88.0,
                "sm_clock_mhz": 1320.0,
                "mem_clock_mhz": 1593.0,
                "power_w": 698.0,
                "power_cap_w": 700.0,
                "idle_reason_active": False,
                "thermal_limit_active": False,
                "power_limit_active": True,
                "low_util_fraction": 0.05,
            }
        if kind == "thermal-limited-busy":
            return {
                "gpu_util_pct": 79.0,
                "sm_clock_mhz": 1185.0,
                "mem_clock_mhz": 1593.0,
                "power_w": 610.0,
                "power_cap_w": 700.0,
                "idle_reason_active": False,
                "thermal_limit_active": True,
                "power_limit_active": False,
                "low_util_fraction": 0.08,
            }
        raise ValueError(f"Unknown simulation scenario: {kind}")

from gpu_low_util_monitor.collector import CollectorConfig, GPUCollector
from gpu_low_util_monitor.models import DeviceCapabilities, DeviceIdentity, DeviceSample


class FlakyBackend:
    def initialize(self) -> None:
        self.identities = [
            DeviceIdentity(index=0, uuid="GPU-0", name="GPU-0"),
            DeviceIdentity(index=1, uuid="GPU-1", name="GPU-1"),
        ]

    def shutdown(self) -> None:
        pass

    def device_identities(self) -> list[DeviceIdentity]:
        return self.identities

    def read_device_sample(self, identity: DeviceIdentity, monotonic_ns: int) -> DeviceSample:
        if identity.index == 0:
            raise RuntimeError("device lost")
        return DeviceSample(
            identity=identity,
            monotonic_ns=monotonic_ns,
            wall_time_iso="2026-04-03T00:00:00+00:00",
            gpu_util_pct=90.0,
            sm_clock_mhz=1800.0,
            mem_clock_mhz=1500.0,
            power_w=600.0,
            idle_reason_active=False,
            low_util_counter_ns=10_000_000,
            capabilities=DeviceCapabilities(),
        )


def test_collector_continues_when_one_gpu_read_fails() -> None:
    ticks = iter([1_000_000_000])
    collector = GPUCollector(
        FlakyBackend(),
        CollectorConfig(interval_seconds=1.0, window_short_seconds=60, window_long_seconds=1200),
        monotonic_ns_fn=lambda: next(ticks),
    )
    collector.initialize()

    reports = collector.poll_once()

    assert len(reports) == 1
    assert reports[0].sample.identity.index == 1

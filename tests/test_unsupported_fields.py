from gpu_low_util_monitor.collector import CollectorConfig, GPUCollector
from gpu_low_util_monitor.models import DeviceCapabilities, DeviceIdentity, DeviceSample


class UnsupportedIdleBackend:
    def initialize(self) -> None:
        self.identity = DeviceIdentity(index=0, uuid="GPU-0", name="GPU")

    def shutdown(self) -> None:
        pass

    def device_identities(self) -> list[DeviceIdentity]:
        return [self.identity]

    def read_device_sample(self, identity: DeviceIdentity, monotonic_ns: int) -> DeviceSample:
        return DeviceSample(
            identity=identity,
            monotonic_ns=monotonic_ns,
            wall_time_iso="2026-04-03T00:00:00+00:00",
            gpu_util_pct=15.0,
            sm_clock_mhz=1000.0,
            mem_clock_mhz=None,
            power_w=150.0,
            idle_reason_active=None,
            low_util_counter_ns=None,
            capabilities=DeviceCapabilities(low_util_counter=False, idle_reason=False, mem_clock=False),
        )


def test_unsupported_fields_propagate_to_summaries() -> None:
    ticks = iter([0, 1_000_000_000])
    collector = GPUCollector(
        UnsupportedIdleBackend(),
        CollectorConfig(interval_seconds=1.0, window_short_seconds=60, window_long_seconds=1200),
        monotonic_ns_fn=lambda: next(ticks),
    )
    collector.initialize()
    collector.poll_once()
    reports = collector.poll_once()

    report = reports[0]
    assert report.sample.capabilities.low_util_counter is False
    assert report.long_summary.low_util_pct_window is None
    assert report.long_summary.idle_reason_pct_window is None
    assert report.long_summary.idle_entries_window is None

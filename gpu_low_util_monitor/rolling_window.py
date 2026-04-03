"""Time-based rolling-window aggregation for GPU metrics."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from gpu_low_util_monitor.models import DeviceSample, WindowSummary
from gpu_low_util_monitor.util import clamp


@dataclass
class IntervalRecord:
    """Derived interval from the previous sample to the current sample."""

    start_ns: int
    end_ns: int
    elapsed_ns: int
    low_util_delta_ns: int | None
    gpu_util_pct: float | None
    sm_clock_mhz: float | None
    mem_clock_mhz: float | None
    power_w: float | None


class RollingWindow:
    """Maintain time-based samples and derived interval summaries for one GPU."""

    def __init__(self, max_window_seconds: int) -> None:
        self._max_window_ns = int(max_window_seconds * 1_000_000_000)
        self._samples: deque[DeviceSample] = deque()
        self._intervals: deque[IntervalRecord] = deque()

    def append(self, sample: DeviceSample) -> None:
        """Append a new sample and derive interval metrics from the prior sample."""
        previous = self._samples[-1] if self._samples else None
        if previous is not None and sample.monotonic_ns > previous.monotonic_ns:
            elapsed_ns = sample.monotonic_ns - previous.monotonic_ns
            self._intervals.append(
                IntervalRecord(
                    start_ns=previous.monotonic_ns,
                    end_ns=sample.monotonic_ns,
                    elapsed_ns=elapsed_ns,
                    low_util_delta_ns=self._safe_counter_delta(
                        previous.low_util_counter_ns,
                        sample.low_util_counter_ns,
                        elapsed_ns,
                    ),
                    gpu_util_pct=sample.gpu_util_pct,
                    sm_clock_mhz=sample.sm_clock_mhz,
                    mem_clock_mhz=sample.mem_clock_mhz,
                    power_w=sample.power_w,
                )
            )
        self._samples.append(sample)
        self._evict(sample.monotonic_ns)

    @staticmethod
    def _safe_counter_delta(
        previous_counter_ns: int | None,
        current_counter_ns: int | None,
        elapsed_ns: int,
    ) -> int | None:
        """Return a defensively clamped counter delta for one interval."""
        if previous_counter_ns is None or current_counter_ns is None:
            return None
        if current_counter_ns < previous_counter_ns:
            return 0
        delta = current_counter_ns - previous_counter_ns
        return int(clamp(float(delta), 0.0, float(elapsed_ns)))

    def summarize(self, window_seconds: int) -> WindowSummary:
        """Compute a rolling summary for a time-bounded window."""
        if not self._samples:
            return WindowSummary(
                window_seconds=window_seconds,
                sample_count=0,
                low_util_pct_window=None,
                idle_reason_pct_window=None,
                idle_entries_window=None,
                avg_gpu_util_window=None,
                avg_sm_clock_mhz_window=None,
                avg_mem_clock_mhz_window=None,
                avg_power_w_window=None,
            )

        newest_ts = self._samples[-1].monotonic_ns
        cutoff_ns = newest_ts - int(window_seconds * 1_000_000_000)
        samples_in_window = [sample for sample in self._samples if sample.monotonic_ns >= cutoff_ns]

        total_elapsed_ns = 0
        total_low_util_ns = 0
        low_util_supported = False

        weighted_gpu_util = 0.0
        weighted_sm_clock = 0.0
        weighted_mem_clock = 0.0
        weighted_power = 0.0
        gpu_util_elapsed_ns = 0
        sm_clock_elapsed_ns = 0
        mem_clock_elapsed_ns = 0
        power_elapsed_ns = 0

        for interval in self._intervals:
            if interval.end_ns <= cutoff_ns:
                continue
            overlap_start = max(interval.start_ns, cutoff_ns)
            overlap_end = interval.end_ns
            overlap_ns = max(0, overlap_end - overlap_start)
            if overlap_ns <= 0 or interval.elapsed_ns <= 0:
                continue
            weight = overlap_ns / interval.elapsed_ns
            total_elapsed_ns += overlap_ns

            if interval.low_util_delta_ns is not None:
                low_util_supported = True
                total_low_util_ns += int(interval.low_util_delta_ns * weight)

            if interval.gpu_util_pct is not None:
                weighted_gpu_util += interval.gpu_util_pct * overlap_ns
                gpu_util_elapsed_ns += overlap_ns
            if interval.sm_clock_mhz is not None:
                weighted_sm_clock += interval.sm_clock_mhz * overlap_ns
                sm_clock_elapsed_ns += overlap_ns
            if interval.mem_clock_mhz is not None:
                weighted_mem_clock += interval.mem_clock_mhz * overlap_ns
                mem_clock_elapsed_ns += overlap_ns
            if interval.power_w is not None:
                weighted_power += interval.power_w * overlap_ns
                power_elapsed_ns += overlap_ns

        idle_states = [sample.idle_reason_active for sample in samples_in_window if sample.idle_reason_active is not None]
        idle_reason_pct = None
        idle_entries = None
        if idle_states:
            idle_reason_pct = round(100.0 * sum(1 for value in idle_states if value) / len(idle_states), 3)
            idle_entries = 0
            previous_state: bool | None = None
            first_sample = samples_in_window[0]
            first_index = next(index for index, sample in enumerate(self._samples) if sample is first_sample)
            if first_index > 0:
                previous_state = self._samples[first_index - 1].idle_reason_active
            for sample in samples_in_window:
                state = sample.idle_reason_active
                if state is None:
                    previous_state = None
                    continue
                if previous_state is False and state is True:
                    idle_entries += 1
                previous_state = state

        low_util_pct = None
        if low_util_supported and total_elapsed_ns > 0:
            low_util_pct = round(
                clamp(100.0 * total_low_util_ns / total_elapsed_ns, 0.0, 100.0),
                3,
            )

        return WindowSummary(
            window_seconds=window_seconds,
            sample_count=len(samples_in_window),
            low_util_pct_window=low_util_pct,
            idle_reason_pct_window=idle_reason_pct,
            idle_entries_window=idle_entries,
            avg_gpu_util_window=_safe_weighted_average(weighted_gpu_util, gpu_util_elapsed_ns),
            avg_sm_clock_mhz_window=_safe_weighted_average(weighted_sm_clock, sm_clock_elapsed_ns),
            avg_mem_clock_mhz_window=_safe_weighted_average(weighted_mem_clock, mem_clock_elapsed_ns),
            avg_power_w_window=_safe_weighted_average(weighted_power, power_elapsed_ns),
        )

    def _evict(self, newest_ts: int) -> None:
        """Evict samples and intervals beyond the retention horizon."""
        cutoff_ns = newest_ts - self._max_window_ns
        while len(self._samples) > 1 and self._samples[1].monotonic_ns < cutoff_ns:
            self._samples.popleft()
        while self._intervals and self._intervals[0].end_ns < cutoff_ns:
            self._intervals.popleft()


def _safe_weighted_average(total: float, elapsed_ns: int) -> float | None:
    """Return a rounded time-weighted average or None."""
    if elapsed_ns <= 0:
        return None
    return round(total / elapsed_ns, 3)

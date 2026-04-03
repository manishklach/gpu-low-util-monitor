import importlib.util

import pytest

from gpu_low_util_monitor.reporting import PrometheusExporter


def test_prometheus_exporter_is_optional() -> None:
    if importlib.util.find_spec("prometheus_client") is not None:
        exporter = PrometheusExporter(port=9108)
        assert exporter is not None
        return

    with pytest.raises(RuntimeError):
        PrometheusExporter(port=9108)

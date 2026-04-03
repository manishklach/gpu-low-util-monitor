from pathlib import Path


def test_prometheus_alert_rules_file_contains_expected_alerts() -> None:
    alert_file = (
        Path(__file__).resolve().parents[1]
        / "monitoring"
        / "prometheus_alerts.yml"
    )

    text = alert_file.read_text(encoding="utf-8")

    assert "GPU_LowUtil_High_LongWindow" in text
    assert "GPU_Underfed_Likely" in text
    assert "GPU_Dim_And_Idle_Bursty" in text
    assert "GPU_Power_Low_With_High_LowUtil" in text
    assert "GPU_ThermalOrPerfPolicyContext" in text
    assert 'gpu_low_util_pct{window_role="long"}' in text
    assert 'gpu_avg_gpu_util{window_role="long"}' in text

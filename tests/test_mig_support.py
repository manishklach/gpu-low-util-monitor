import sys
from types import SimpleNamespace

from gpu_low_util_monitor.nvml_adapter import RealNVMLBackend


class _FakePynvml:
    NVML_SUCCESS = 0
    NVML_DEVICE_MIG_ENABLE = 1

    def __init__(self) -> None:
        self._parent_handle = object()
        self._mig_handle = object()

    def nvmlInit(self) -> None:
        return None

    def nvmlShutdown(self) -> None:
        return None

    def nvmlDeviceGetCount(self) -> int:
        return 1

    def nvmlDeviceGetHandleByIndex(self, index: int) -> object:
        return self._parent_handle

    def nvmlDeviceGetName(self, handle: object) -> bytes:
        if handle is self._mig_handle:
            return b"1g.10gb"
        return b"NVIDIA H100 80GB HBM3"

    def nvmlDeviceGetUUID(self, handle: object) -> bytes:
        if handle is self._mig_handle:
            return b"MIG-GPU-0/5/0"
        return b"GPU-parent-0"

    def nvmlDeviceGetMigMode(self, handle: object) -> tuple[int, int]:
        return (1, 1)

    def nvmlDeviceGetMaxMigDeviceCount(self, handle: object) -> int:
        return 1

    def nvmlDeviceGetMigDeviceHandleByIndex(self, handle: object, index: int) -> object:
        return self._mig_handle


def test_nvml_backend_enumerates_mig_instances(monkeypatch) -> None:
    fake_module = _FakePynvml()
    monkeypatch.setitem(sys.modules, "pynvml", fake_module)

    backend = RealNVMLBackend(mig_strategy="auto")
    backend.initialize()
    identities = backend.device_identities()

    assert len(identities) == 1
    assert identities[0].entity_kind == "mig"
    assert identities[0].parent_uuid == "GPU-parent-0"
    assert identities[0].mig_instance_id == "0"

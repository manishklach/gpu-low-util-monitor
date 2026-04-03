import tomllib
from pathlib import Path

from gpu_low_util_monitor import __version__


def test_pyproject_uses_dynamic_version_from_package() -> None:
    payload = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert payload["project"]["dynamic"] == ["version"]
    assert payload["tool"]["setuptools"]["dynamic"]["version"]["attr"] == "gpu_low_util_monitor.__version__"
    assert __version__ == "0.3.0"

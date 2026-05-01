import pytest
from lsmm.core import installer


@pytest.fixture(autouse=True)
def reset_migration_flag():
    """Reset the module-level migration guard between tests."""
    installer._migration_done = False
    yield
    installer._migration_done = False


@pytest.fixture()
def fake_manifest_path(tmp_path, monkeypatch):
    """Point MANIFEST_PATH to a temp file so tests never touch the real user path."""
    path = tmp_path / "installed_mods.json"
    monkeypatch.setattr(installer, "MANIFEST_PATH", path)
    return path

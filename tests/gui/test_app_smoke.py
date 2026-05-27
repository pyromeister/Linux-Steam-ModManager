import pytest


pytestmark = pytest.mark.gui


def test_gui_app_imports_and_instantiates():
    """Smoke-test the GTK entrypoint under a real or virtual display."""
    gi = pytest.importorskip("gi")
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")

    from lsmm.gui.app import ModManagerApp

    app = ModManagerApp()

    assert app.get_application_id() == "io.github.pyromeister.lsmm"

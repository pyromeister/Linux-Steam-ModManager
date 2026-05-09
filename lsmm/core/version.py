APP_NAME = "Linux-Steam-ModManager"
APP_SLUG = "lsmm"

try:
    from importlib.metadata import version as _pkg_version
    APP_VERSION = _pkg_version("lsmm")
except Exception:
    try:
        import re as _re
        from pathlib import Path as _Path
        _toml = (_Path(__file__).parent.parent.parent / "pyproject.toml").read_text()
        _m = _re.search(r'^version\s*=\s*"([^"]+)"', _toml, _re.MULTILINE)
        APP_VERSION = _m.group(1) if _m else "0.1.1"
    except Exception:
        APP_VERSION = "0.1.1"

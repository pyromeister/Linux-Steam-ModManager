APP_NAME = "Linux-Steam-ModManager"
APP_SLUG = "lsmm"

try:
    from importlib.metadata import version as _pkg_version
    APP_VERSION = _pkg_version("lsmm")
except Exception:
    APP_VERSION = "0.1.1"

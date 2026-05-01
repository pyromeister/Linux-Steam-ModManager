"""GitHub release checker — debounced to once per 24h, silent on failure."""
import json
import logging
import time
import urllib.error
from pathlib import Path

from lsmm.core import net
from lsmm.core.version import APP_VERSION

log = logging.getLogger(__name__)

_RELEASES_URL = "https://api.github.com/repos/pyromeister/Linux-Steam-ModManager/releases/latest"
_CHECK_INTERVAL = 86400  # 24 h
_DEBOUNCE_PATH = Path.home() / ".local/state/linux-mod-manager/update_check.json"


def _parse_version(tag: str) -> tuple[int, ...]:
    return tuple(int(x) for x in tag.lstrip("v").split(".") if x.isdigit())


def _debounce_ok() -> bool:
    """Return True if enough time has passed since the last check."""
    try:
        data = json.loads(_DEBOUNCE_PATH.read_text())
        return time.time() - data.get("checked_at", 0) >= _CHECK_INTERVAL
    except Exception:
        return True


def _record_check() -> None:
    try:
        _DEBOUNCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _DEBOUNCE_PATH.write_text(json.dumps({"checked_at": time.time()}))
    except Exception:
        pass


def check_for_update() -> tuple[str, str] | None:
    """Return (tag, html_url) if a newer release exists, else None.

    Silent on any network or parse error.
    """
    if not _debounce_ok():
        return None

    _record_check()

    try:
        data = json.loads(net.request(_RELEASES_URL, timeout=10))
        tag = data.get("tag_name", "")
        url = data.get("html_url", "")
        if _parse_version(tag) > _parse_version(APP_VERSION):
            return tag, url
        return None
    except (urllib.error.URLError, urllib.error.HTTPError, Exception):
        log.debug("Update check failed (silent)", exc_info=True)
        return None

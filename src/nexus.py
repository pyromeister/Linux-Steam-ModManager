"""
Nexus Mods NXM URL handler and download client.
nxm://game_domain/mods/mod_id/files/file_id?key=K&expires=T&user_id=U
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

NXM_PATTERN = re.compile(r"^nxm://([^/]+)/mods/(\d+)/files/(\d+)", re.IGNORECASE)
NEXUS_API_BASE = "https://api.nexusmods.com/v1"
USER_AGENT = "linux-mod-manager/1.0"


def parse_nxm(url: str) -> dict | None:
    """Parse nxm:// URL. Returns None if not a valid NXM link."""
    m = NXM_PATTERN.match(url.strip())
    if not m:
        return None
    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)
    return {
        "game_domain": m.group(1).lower(),
        "mod_id": int(m.group(2)),
        "file_id": int(m.group(3)),
        "key": params.get("key", [None])[0],
        "expires": params.get("expires", [None])[0],
    }


def get_download_link(nxm: dict, api_key: str) -> str:
    """
    Query Nexus API for a CDN download URL.
    Raises RuntimeError on API errors.
    """
    game = nxm["game_domain"]
    mod_id = nxm["mod_id"]
    file_id = nxm["file_id"]

    endpoint = f"{NEXUS_API_BASE}/games/{game}/mods/{mod_id}/files/{file_id}/download_link.json"
    qs = {}
    if nxm.get("key"):
        qs["key"] = nxm["key"]
    if nxm.get("expires"):
        qs["expires"] = nxm["expires"]
    if qs:
        endpoint += "?" + urllib.parse.urlencode(qs)

    req = urllib.request.Request(
        endpoint,
        headers={"apikey": api_key, "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"Nexus API {e.code}: {body}") from e

    if not data or not isinstance(data, list):
        raise RuntimeError("No download links returned by Nexus API")

    # Prefer Nexus CDN over third-party mirrors
    for entry in data:
        if "CDN" in entry.get("short_name", "").upper():
            return entry["URI"]
    return data[0]["URI"]


def download_file(url: str, dest: Path, on_progress=None) -> None:
    """
    Download URL to dest. Calls on_progress(downloaded_bytes, total_bytes) if given.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        dest.parent.mkdir(parents=True, exist_ok=True)
        downloaded = 0
        with dest.open("wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if on_progress:
                    on_progress(downloaded, total)

"""
Nexus Mods NXM URL handler and download client.
nxm://game_domain/mods/mod_id/files/file_id?key=K&expires=T&user_id=U
"""

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from lsmm.core import net
from lsmm.core.version import APP_NAME, APP_VERSION

NXM_PATTERN = re.compile(r"^nxm://([^/]+)/mods/(\d+)/files/(\d+)", re.IGNORECASE)


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


NEXUS_API_BASE = "https://api.nexusmods.com/v1"


def _api_headers(api_key: str) -> dict:
    return {
        "apikey": api_key,
        "User-Agent": f"{APP_NAME}/{APP_VERSION} (+https://github.com/pyromeister/Linux-Steam-ModManager)",
        "Application-Name": APP_NAME,
        "Application-Version": APP_VERSION,
    }


def parse_nxm(url: str) -> dict | None:
    """
    Parse an nxm:// URL. Returns dict with game_domain, mod_id, file_id,
    key, expires, user_id — or None if URL doesn't match.
    """
    m = NXM_PATTERN.match(url)
    if not m:
        return None
    qs = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    return {
        "game_domain": m.group(1),
        "mod_id": int(m.group(2)),
        "file_id": int(m.group(3)),
        "key": qs.get("key"),
        "expires": qs.get("expires"),
        "user_id": qs.get("user_id"),
    }


def get_download_link(nxm: dict, api_key: str) -> str:
    """
    Call Nexus API to get a CDN download URL for the given NXM parameters.
    Returns the download URL string.
    Raises RuntimeError on API failure.
    """
    endpoint = (
        f"{NEXUS_API_BASE}/games/{nxm['game_domain']}/mods/{nxm['mod_id']}"
        f"/files/{nxm['file_id']}/download_link.json"
    )
    qs = {}
    if nxm.get("key"):
        qs["key"] = nxm["key"]
    if nxm.get("expires"):
        qs["expires"] = nxm["expires"]
    if qs:
        endpoint += "?" + urllib.parse.urlencode(qs)

    try:
        data = json.loads(net.request(endpoint, headers=_api_headers(api_key)))
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"Nexus API {e.code}: {body}") from e

    if not data:
        raise RuntimeError("Nexus returned empty download links list")
    return data[0]["URI"]


def get_mod_files(game_domain: str, mod_id: int, api_key: str) -> list[dict]:
    """
    Fetch file list for a mod. Returns list of file dicts
    (file_id, name, version, category_name, uploaded_timestamp, …).
    """
    endpoint = f"{NEXUS_API_BASE}/games/{game_domain}/mods/{mod_id}/files.json"
    try:
        data = json.loads(net.request(endpoint, headers=_api_headers(api_key)))
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"Nexus API {e.code}: {body}") from e

    files = data.get("files", [])
    # Normalise: ensure file_id key exists
    for f in files:
        if "file_id" not in f and "id" in f:
            f["file_id"] = f["id"][0] if isinstance(f["id"], list) else f["id"]
    return files


def check_update(game_domain: str, mod_id: int, current_file_id: int, api_key: str) -> dict | None:
    """Return newest main-file dict if a newer file exists, else None."""
    files = get_mod_files(game_domain, mod_id, api_key)
    main_files = [f for f in files if f.get("category_name") in ("MAIN", "Main")]
    if not main_files:
        return None
    newest = max(main_files, key=lambda f: f.get("uploaded_timestamp", 0))
    if newest.get("file_id") != current_file_id:
        return newest
    return None


def fetch_collection(slug: str, api_key: str) -> dict | None:
    """Fetch collection metadata from Nexus API. Returns None on any failure."""
    endpoint = f"{NEXUS_API_BASE}/collections/{slug}.json"
    try:
        return json.loads(net.request(endpoint, headers=_api_headers(api_key)))
    except Exception:
        return None


def fetch_collection_graphql(slug: str, api_key: str) -> dict | None:
    url = "https://api.nexusmods.com/v2/graphql"
    headers = _api_headers(api_key) | {"Content-Type": "application/json"}
    query = {
        "query": """
        {
            collection(slug: "%s") {
                name
                game { domainName }
                latestPublishedRevision {
                    modFiles {
                        optional
                        fileId
                        file {
                            modId
                            mod { name }
                        }
                    }
                }
            }
        }
        """ % slug
    }
    try:
        response = json.loads(net.request(url, data=json.dumps(query).encode(), headers=headers))
    except Exception:
        return None

    try:
        rev = response["data"]["collection"]["latestPublishedRevision"]
        game_domain = response["data"]["collection"]["game"]["domainName"]
        col_name = response["data"]["collection"]["name"]
        mods = []
        for mf in rev.get("modFiles", []):
            f = mf.get("file", {})
            mods.append({
                "mod_id": f.get("modId"),
                "file_id": mf.get("fileId"),
                "game_domain": game_domain,
                "mod_name": f.get("mod", {}).get("name", ""),
                "optional": mf.get("optional", False),
            })
        return {"name": col_name, "game_domain": game_domain, "mods": mods}
    except (KeyError, TypeError):
        return None


def download_file(url: str, dest: Path, on_progress=None, expected_md5: str | None = None) -> None:
    """
    Download URL to dest. Calls on_progress(downloaded_bytes, total_bytes) if given.
    """
    parsed = urllib.parse.urlsplit(url)
    safe_url = urllib.parse.urlunsplit(
        parsed._replace(path=urllib.parse.quote(parsed.path, safe="/:@!$&'()*+,;="))
    )
    req = urllib.request.Request(safe_url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
    hasher = hashlib.md5() if expected_md5 else None
    with urllib.request.urlopen(req, timeout=net.DEFAULT_TIMEOUT) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        dest.parent.mkdir(parents=True, exist_ok=True)
        downloaded = 0
        with dest.open("wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                if hasher:
                    hasher.update(chunk)
                downloaded += len(chunk)
                if on_progress:
                    on_progress(downloaded, total)
    if expected_md5 and hasher:
        actual = hasher.hexdigest()
        if actual.lower() != expected_md5.lower():
            dest.unlink(missing_ok=True)
            raise RuntimeError(
                f"Checksum mismatch for {dest.name}: expected {expected_md5}, got {actual}"
            )

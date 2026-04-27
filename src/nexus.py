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


def get_mod_files(game_domain: str, mod_id: int, api_key: str) -> list[dict]:
    """
    Fetch all file listings for a mod from Nexus API.
    Returns list of file dicts (file_id, name, version, category_name, uploaded_timestamp, …).
    """
    endpoint = f"{NEXUS_API_BASE}/games/{game_domain}/mods/{mod_id}/files.json"
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
    return data.get("files", [])


def check_update(game_domain: str, mod_id: int, current_file_id: int, api_key: str) -> dict | None:
    """
    Check if a newer MAIN file exists for a mod.
    Returns the latest MAIN file dict if it differs from current_file_id, else None.
    """
    files = get_mod_files(game_domain, mod_id, api_key)
    main_files = [f for f in files if f.get("category_name") == "MAIN"]
    if not main_files:
        return None
    latest = max(main_files, key=lambda f: f.get("uploaded_timestamp", 0))
    if latest.get("file_id") != current_file_id:
        return latest
    return None


def fetch_collection(slug: str, api_key: str) -> dict | None:
    """Fetch collection metadata from Nexus API. Returns None on any failure."""
    endpoint = f"{NEXUS_API_BASE}/collections/{slug}.json"
    req = urllib.request.Request(
        endpoint,
        headers={"apikey": api_key, "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def fetch_collection_graphql(slug: str, api_key: str) -> dict | None:
    url = "https://api.nexusmods.com/v2/graphql"
    headers = {
        "apikey": api_key,
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
    }
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
        req = urllib.request.Request(
            url,
            data=json.dumps(query).encode(),
            headers=headers,
        )
        with urllib.request.urlopen(req) as resp:
            response = json.loads(resp.read())
    except Exception:
        return None

    collection_data = response.get("data", {}).get("collection")
    if not collection_data:
        return None

    mods = []
    for mod_file in collection_data["latestPublishedRevision"]["modFiles"]:
        mods.append({
            "optional": mod_file["optional"],
            "file_id": mod_file["fileId"],
            "mod_id": mod_file["file"]["modId"],
            "name": mod_file["file"]["mod"]["name"],
        })

    return {
        "name": collection_data["name"],
        "game_domain": collection_data["game"]["domainName"],
        "mods": mods,
    }


def download_file(url: str, dest: Path, on_progress=None) -> None:
    """
    Download URL to dest. Calls on_progress(downloaded_bytes, total_bytes) if given.
    """
    # CDN URLs sometimes contain spaces or unencoded chars in the path — fix them
    parsed = urllib.parse.urlsplit(url)
    safe_url = urllib.parse.urlunsplit(
        parsed._replace(path=urllib.parse.quote(parsed.path, safe="/:@!$&'()*+,;="))
    )
    req = urllib.request.Request(safe_url, headers={"User-Agent": USER_AGENT})
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

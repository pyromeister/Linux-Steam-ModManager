import json
import urllib.error
from unittest.mock import patch

import pytest

from lsmm.core import nexus
from lsmm.core.nexus import (
    parse_nxm,
    get_download_link,
    get_mod_files,
    check_update,
    fetch_collection,
    md5_file,
)


class TestParseNxm:
    def test_full_url_parses_all_fields(self):
        url = "nxm://skyrimspecialedition/mods/12345/files/67890?key=ABC&expires=9999999999&user_id=42"
        result = parse_nxm(url)
        assert result is not None
        assert result["game_domain"] == "skyrimspecialedition"
        assert result["mod_id"] == 12345
        assert result["file_id"] == 67890
        assert result["key"] == "ABC"
        assert result["expires"] == "9999999999"
        assert result["user_id"] == "42"

    def test_mod_id_and_file_id_are_ints(self):
        url = "nxm://starfield/mods/999/files/111?key=K&expires=1"
        result = parse_nxm(url)
        assert isinstance(result["mod_id"], int)
        assert isinstance(result["file_id"], int)

    def test_url_without_query_params_returns_none_values(self):
        url = "nxm://skyrimspecialedition/mods/12345/files/67890"
        result = parse_nxm(url)
        assert result is not None
        assert result["key"] is None
        assert result["expires"] is None
        assert result["user_id"] is None

    def test_non_nxm_scheme_returns_none(self):
        assert parse_nxm("https://www.nexusmods.com/skyrimspecialedition/mods/12345") is None

    def test_empty_string_returns_none(self):
        assert parse_nxm("") is None

    def test_random_string_returns_none(self):
        assert parse_nxm("not-a-url") is None

    def test_bare_nxm_scheme_returns_none(self):
        assert parse_nxm("nxm://") is None

    def test_case_insensitive_scheme(self):
        url = "NXM://skyrimspecialedition/mods/1/files/1"
        assert parse_nxm(url) is not None

    def test_various_game_domains(self):
        for domain in ("fallout4", "starfield", "oblivion"):
            result = parse_nxm(f"nxm://{domain}/mods/1/files/1")
            assert result["game_domain"] == domain


class TestMd5File:
    def test_md5_of_known_content(self, tmp_path):
        import hashlib
        p = tmp_path / "test.bin"
        p.write_bytes(b"hello")
        expected = hashlib.md5(b"hello").hexdigest()
        assert md5_file(p) == expected

    def test_md5_empty_file(self, tmp_path):
        import hashlib
        p = tmp_path / "empty.bin"
        p.write_bytes(b"")
        assert md5_file(p) == hashlib.md5(b"").hexdigest()


class TestApiHeaders:
    def test_headers_contain_apikey(self):
        headers = nexus._api_headers("mykey123")
        assert headers["apikey"] == "mykey123"

    def test_headers_contain_user_agent(self):
        headers = nexus._api_headers("k")
        assert "User-Agent" in headers

    def test_headers_contain_app_name(self):
        headers = nexus._api_headers("k")
        assert "Application-Name" in headers


class TestGetDownloadLink:
    def test_returns_uri_from_response(self):
        nxm = {"game_domain": "skyrimspecialedition", "mod_id": 1, "file_id": 1,
               "key": "K", "expires": "9999999999", "user_id": None}
        with patch("lsmm.core.nexus.net.request") as mock_req:
            mock_req.return_value = json.dumps([{"URI": "https://cdn.example.com/file.zip"}])
            uri = get_download_link(nxm, "apikey")
        assert uri == "https://cdn.example.com/file.zip"

    def test_raises_on_http_error(self):
        nxm = {"game_domain": "skyrimspecialedition", "mod_id": 1, "file_id": 1,
               "key": None, "expires": None, "user_id": None}
        err = urllib.error.HTTPError(url="", code=403, msg="Forbidden", hdrs=None, fp=None)
        err.read = lambda: b"Forbidden"
        with patch("lsmm.core.nexus.net.request", side_effect=err):
            with pytest.raises(RuntimeError, match="403"):
                get_download_link(nxm, "badkey")

    def test_raises_on_empty_response(self):
        nxm = {"game_domain": "skyrimspecialedition", "mod_id": 1, "file_id": 1,
               "key": None, "expires": None, "user_id": None}
        with patch("lsmm.core.nexus.net.request") as mock_req:
            mock_req.return_value = json.dumps([])
            with pytest.raises(RuntimeError, match="empty"):
                get_download_link(nxm, "apikey")

    def test_includes_key_and_expires_in_url(self):
        nxm = {"game_domain": "skyrimspecialedition", "mod_id": 1, "file_id": 1,
               "key": "MYKEY", "expires": "9999999999", "user_id": None}
        with patch("lsmm.core.nexus.net.request") as mock_req:
            mock_req.return_value = json.dumps([{"URI": "https://cdn.example.com/f.zip"}])
            get_download_link(nxm, "apikey")
        call_url = mock_req.call_args[0][0]
        assert "key=MYKEY" in call_url
        assert "expires=9999999999" in call_url


class TestGetModFiles:
    def test_returns_file_list(self):
        fake_files = [{"file_id": 1, "name": "main.zip", "category_name": "MAIN",
                       "uploaded_timestamp": 1000}]
        with patch("lsmm.core.nexus.net.request") as mock_req:
            mock_req.return_value = json.dumps({"files": fake_files})
            files = get_mod_files("skyrimspecialedition", 1, "apikey")
        assert len(files) == 1
        assert files[0]["name"] == "main.zip"

    def test_raises_on_http_error(self):
        err = urllib.error.HTTPError(url="", code=404, msg="Not Found", hdrs=None, fp=None)
        err.read = lambda: b"Not Found"
        with patch("lsmm.core.nexus.net.request", side_effect=err):
            with pytest.raises(RuntimeError, match="404"):
                get_mod_files("skyrimspecialedition", 1, "apikey")

    def test_normalises_id_list_to_file_id(self):
        fake_files = [{"id": [42, 0], "name": "main.zip", "category_name": "MAIN",
                       "uploaded_timestamp": 1000}]
        with patch("lsmm.core.nexus.net.request") as mock_req:
            mock_req.return_value = json.dumps({"files": fake_files})
            files = get_mod_files("skyrimspecialedition", 1, "apikey")
        assert files[0]["file_id"] == 42


class TestCheckUpdate:
    def _file(self, file_id, ts):
        return {"file_id": file_id, "name": "main.zip",
                "category_name": "MAIN", "uploaded_timestamp": ts}

    def test_returns_newer_file(self):
        with patch("lsmm.core.nexus.get_mod_files") as mock_gmf:
            mock_gmf.return_value = [self._file(1, 1000), self._file(2, 2000)]
            result = check_update("skyrimspecialedition", 1, current_file_id=1, api_key="k")
        assert result["file_id"] == 2

    def test_returns_none_when_already_newest(self):
        with patch("lsmm.core.nexus.get_mod_files") as mock_gmf:
            mock_gmf.return_value = [self._file(2, 2000)]
            result = check_update("skyrimspecialedition", 1, current_file_id=2, api_key="k")
        assert result is None

    def test_returns_none_when_no_main_files(self):
        with patch("lsmm.core.nexus.get_mod_files") as mock_gmf:
            mock_gmf.return_value = [{"file_id": 1, "category_name": "OPTIONAL",
                                      "uploaded_timestamp": 9999}]
            result = check_update("skyrimspecialedition", 1, current_file_id=1, api_key="k")
        assert result is None


class TestFetchCollection:
    def test_returns_parsed_json(self):
        with patch("lsmm.core.nexus.net.request") as mock_req:
            mock_req.return_value = json.dumps({"name": "Cool Collection"})
            result = fetch_collection("cool-collection", "apikey")
        assert result["name"] == "Cool Collection"

    def test_returns_none_on_exception(self):
        with patch("lsmm.core.nexus.net.request", side_effect=Exception("fail")):
            result = fetch_collection("cool-collection", "apikey")
        assert result is None


class TestFetchCollectionGraphql:
    _response = {
        "data": {
            "collection": {
                "name": "My Collection",
                "game": {"domainName": "skyrimspecialedition"},
                "latestPublishedRevision": {
                    "modFiles": [
                        {
                            "optional": False,
                            "fileId": 67890,
                            "file": {"modId": 12345, "mod": {"name": "Cool Mod"}},
                        }
                    ]
                },
            }
        }
    }

    def test_returns_collection_with_mods(self):
        with patch("lsmm.core.nexus.net.request") as mock_req:
            mock_req.return_value = json.dumps(self._response)
            result = nexus.fetch_collection_graphql("my-collection", "apikey")
        assert result is not None
        assert result["name"] == "My Collection"
        assert result["game_domain"] == "skyrimspecialedition"
        assert len(result["mods"]) == 1
        assert result["mods"][0]["mod_id"] == 12345
        assert result["mods"][0]["file_id"] == 67890

    def test_returns_none_on_network_error(self):
        with patch("lsmm.core.nexus.net.request", side_effect=Exception("fail")):
            result = nexus.fetch_collection_graphql("my-collection", "apikey")
        assert result is None

    def test_returns_none_on_missing_data_key(self):
        with patch("lsmm.core.nexus.net.request") as mock_req:
            mock_req.return_value = json.dumps({"error": "not found"})
            result = nexus.fetch_collection_graphql("my-collection", "apikey")
        assert result is None

    def test_handles_empty_mod_files(self):
        response = {
            "data": {
                "collection": {
                    "name": "Empty",
                    "game": {"domainName": "fallout4"},
                    "latestPublishedRevision": {"modFiles": []},
                }
            }
        }
        with patch("lsmm.core.nexus.net.request") as mock_req:
            mock_req.return_value = json.dumps(response)
            result = nexus.fetch_collection_graphql("empty-col", "apikey")
        assert result["mods"] == []


# ── check_nxm_expiry ──────────────────────────────────────────────────────────

def test_check_nxm_expiry_raises_for_past():
    nxm = {"expires": "1"}
    with pytest.raises(nexus.NxmExpiredError):
        nexus.check_nxm_expiry(nxm)


def test_check_nxm_expiry_ok_for_future():
    import time
    nxm = {"expires": str(int(time.time()) + 3600)}
    nexus.check_nxm_expiry(nxm)


def test_check_nxm_expiry_ok_when_no_expires():
    nexus.check_nxm_expiry({"expires": None})


# ── _nxm_error_message ────────────────────────────────────────────────────────

def test_nxm_error_message_403():
    from lsmm.core.nexus import nxm_error_message as _nxm_error_message
    msg = _nxm_error_message(RuntimeError("Nexus API 403: Forbidden"))
    assert "API key" in msg


def test_nxm_error_message_404():
    from lsmm.core.nexus import nxm_error_message as _nxm_error_message
    msg = _nxm_error_message(RuntimeError("Nexus API 404: Not Found"))
    assert "not found" in msg.lower()


def test_nxm_error_message_410():
    from lsmm.core.nexus import nxm_error_message as _nxm_error_message
    msg = _nxm_error_message(RuntimeError("Nexus API 410: Gone"))
    assert "removed" in msg


def test_nxm_error_message_unknown():
    from lsmm.core.nexus import nxm_error_message as _nxm_error_message
    msg = _nxm_error_message(RuntimeError("some random error"))
    assert "NXM import failed" in msg


class TestGetModChangelogs:
    def test_returns_version_dict(self):
        fake = {"1.0": "Initial release", "1.1": "Bug fixes"}
        with patch("lsmm.core.nexus.net.request") as mock_req:
            mock_req.return_value = json.dumps(fake)
            result = nexus.get_mod_changelogs("skyrimspecialedition", 1, "apikey")
        assert result == fake

    def test_returns_empty_on_network_error(self):
        with patch("lsmm.core.nexus.net.request", side_effect=Exception("fail")):
            result = nexus.get_mod_changelogs("skyrimspecialedition", 1, "apikey")
        assert result == {}

    def test_returns_empty_when_response_not_dict(self):
        with patch("lsmm.core.nexus.net.request") as mock_req:
            mock_req.return_value = json.dumps([])
            result = nexus.get_mod_changelogs("skyrimspecialedition", 1, "apikey")
        assert result == {}

    def test_hits_correct_endpoint(self):
        with patch("lsmm.core.nexus.net.request") as mock_req:
            mock_req.return_value = json.dumps({})
            nexus.get_mod_changelogs("fallout4", 42, "apikey")
        url = mock_req.call_args[0][0]
        assert "fallout4" in url
        assert "42" in url
        assert "changelogs.json" in url

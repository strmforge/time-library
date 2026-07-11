import io
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import update_source  # noqa: E402


class _Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def test_latest_release_api_discovers_version_and_matching_archive(monkeypatch):
    payload = {
        "tag_name": "v2026.7.10",
        "assets": [
            {
                "name": "time-library-2026.7.10.zip",
                "browser_download_url": "https://example.test/time-library-2026.7.10.zip",
            },
            {
                "name": "time-library-2026.7.10.zip.sha256",
                "browser_download_url": "https://example.test/time-library-2026.7.10.zip.sha256",
            },
        ],
    }
    monkeypatch.delenv("TIME_LIBRARY_UPDATE_VERSION_URL", raising=False)
    monkeypatch.delenv("MEMCORE_UPDATE_VERSION_URL", raising=False)
    monkeypatch.setattr(update_source, "urlopen", lambda request, timeout=10: _Response(json.dumps(payload).encode()))

    result = update_source.check_remote_version()

    assert result["ok"] is True
    assert result["latest_version"] == "2026.7.10"
    assert result["metadata_source"] == "github_releases_api"
    assert result["archive_available"] is True
    assert result["archive_url"].endswith("time-library-2026.7.10.zip")
    assert result["checksum_url"].endswith("time-library-2026.7.10.zip.sha256")


def test_latest_release_without_packaged_archive_is_not_installable(monkeypatch):
    payload = {"tag_name": "v2026.7.10", "assets": [{"name": "install.sh"}]}
    monkeypatch.setattr(update_source, "urlopen", lambda request, timeout=10: _Response(json.dumps(payload).encode()))

    result = update_source.check_remote_version()

    assert result["ok"] is True
    assert result["latest_version"] == "2026.7.10"
    assert result["archive_available"] is False
    assert result["archive_url"] == ""


def test_plain_version_override_remains_supported(monkeypatch):
    monkeypatch.setenv("TIME_LIBRARY_UPDATE_VERSION_URL", "file:///tmp/VERSION")
    monkeypatch.setattr(update_source, "urlopen", lambda request, timeout=10: _Response(b"2026.7.10\n"))

    result = update_source.check_remote_version()

    assert result["ok"] is True
    assert result["latest_version"] == "2026.7.10"
    assert result["metadata_source"] == "file"
    assert result["archive_url"].endswith("v2026.7.10/time-library-2026.7.10.zip")

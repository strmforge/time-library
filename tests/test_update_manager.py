import hashlib

from src import update_manager
from src.memcore_version import SERVICE_VERSION


def test_default_checksum_version_uses_current_release(tmp_path, monkeypatch):
    package = tmp_path / "package.zip"
    package.write_bytes(b"release package")
    expected = hashlib.sha256(package.read_bytes()).hexdigest()
    monkeypatch.setattr(update_manager, "KNOWN_CHECKSUMS", {SERVICE_VERSION: expected})

    safety = update_manager.UpdateSafetyModel()
    assert safety.verify_checksum(str(package)) == (True, "checksum verified")
    package.write_bytes(b"changed package")
    ok, reason = safety.verify_checksum(str(package))
    assert ok is False
    assert reason.startswith("checksum mismatch:")


def test_unknown_version_or_platform_checksum_fails_closed(tmp_path, monkeypatch):
    package = tmp_path / "package.zip"
    package.write_bytes(b"release package")
    monkeypatch.setattr(
        update_manager,
        "KNOWN_CHECKSUMS",
        {SERVICE_VERSION: {"linux": "known-linux-sha"}},
    )

    safety = update_manager.UpdateSafetyModel()
    assert safety.verify_checksum(str(package), platform="darwin") == (
        False,
        f"no known checksum for platform darwin, version {SERVICE_VERSION}",
    )
    assert safety.verify_checksum(str(package), version="future.version") == (
        False,
        "no known checksum for version future.version",
    )

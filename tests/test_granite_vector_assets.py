import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

from src import granite_vector_assets as assets


def _legacy_model_config():
    return {
        "version": "1.0",
        "recall": {
            "mode": "local_bge_m3",
            "local_bge_m3": {
                "model_name": "BAAI/bge-m3",
                "model_path": "BAAI/bge-m3",
                "embedding_model": "BAAI/bge-m3",
                "embedding_dim": 1024,
                "pooling": "mean_unmasked",
                "table": "experiences_v2",
            },
            "substring": {"table": "experiences"},
        },
    }


def test_upgrade_migrates_only_known_bge_default_to_honest_fts5(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "model_config.json").write_text(json.dumps(_legacy_model_config()), encoding="utf-8")

    result = assets.migrate_legacy_bge_upgrade(tmp_path)
    migrated = json.loads((config / "model_config.json").read_text(encoding="utf-8"))

    assert result["write_performed"] is True
    assert result["resume_vector_enable"] is False
    assert result["state"] == "awaiting_user_enable"
    assert migrated["recall"]["mode"] == "substring"
    assert migrated["recall"]["local_vector"]["model_id"] == assets.GRANITE_MODEL_ID
    assert migrated["recall"]["local_vector"]["table"] == assets.GRANITE_TABLE
    assert migrated["recall"]["vector_fallback"]["model_name"] == "BAAI/bge-m3"
    assert migrated["recall"]["vector_fallback"]["table"] == "experiences_v2"
    assert len(list(config.glob("model_config.json.pre-granite-*.bak"))) == 1
    assert assets.migrate_legacy_bge_upgrade(tmp_path)["write_performed"] is False


def test_upgrade_resumes_explicit_vector_only_after_granite_is_ready(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    (config / "model_config.json").write_text(json.dumps(_legacy_model_config()), encoding="utf-8")
    (config / "lancedb_v2_metadata.json").write_text(json.dumps({
        "table": "experiences_v2",
        "upgrade_history": [],
    }), encoding="utf-8")
    (config / "zhiyi_model_binding.user.json").write_text(json.dumps({
        "binding_kind": "platform_default",
        "vector_recall_preference": {"enabled": True},
    }), encoding="utf-8")

    migration = assets.migrate_legacy_bge_upgrade(tmp_path)
    assert migration["resume_vector_enable"] is True
    assert json.loads((config / "model_config.json").read_text(encoding="utf-8"))["recall"]["mode"] == "substring"
    (tmp_path / "runtime" / assets.GRANITE_UPGRADE_STATUS).unlink()

    monkeypatch.setattr(assets, "granite_asset_status", lambda root, verify=False: {
        "ready": False, "state": "not_ready",
    })

    def start(root, on_complete=None):
        on_complete({"ready": True, "table_row_count": 42})
        return {"ready": False, "state": "downloading", "started": True}

    monkeypatch.setattr(assets, "start_granite_asset_prepare", start)
    result = assets.resume_legacy_vector_upgrade(tmp_path)
    migrated = json.loads((config / "model_config.json").read_text(encoding="utf-8"))
    metadata = json.loads((config / "lancedb_v2_metadata.json").read_text(encoding="utf-8"))
    preference = json.loads((config / "zhiyi_model_binding.user.json").read_text(encoding="utf-8"))

    assert result["asset_prepare_started"] is True
    assert result["state"] == "completed_enabled"
    assert migrated["recall"]["mode"] == "local_vector"
    assert metadata["table"] == assets.GRANITE_TABLE
    assert metadata["record_count"] == 42
    assert preference["vector_recall_preference"]["enabled"] is True


def test_upgrade_leaves_custom_vector_contract_untouched(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    custom = {
        "recall": {
            "mode": "local_vector",
            "local_vector": {
                "model_id": "custom/private-embedding",
                "embedding_dim": 768,
                "table": "custom_vectors",
            },
        },
    }
    path = config / "model_config.json"
    path.write_text(json.dumps(custom), encoding="utf-8")

    result = assets.migrate_legacy_bge_upgrade(tmp_path)

    assert result["applicable"] is False
    assert result["write_performed"] is False
    assert json.loads(path.read_text(encoding="utf-8")) == custom
    assert not list(config.glob("model_config.json.pre-granite-*.bak"))


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def test_asset_status_is_not_ready_without_model_or_table(tmp_path):
    status = assets.granite_asset_status(tmp_path)
    assert status["ready"] is False
    assert status["state"] == "not_ready"
    assert status["fallback"] == "FTS5+BM25"
    assert status["model_path"].startswith(str(tmp_path))
    assert ("/" + "Volumes/") not in status["model_path"]


def test_download_is_pinned_checksum_verified_and_atomic(tmp_path, monkeypatch):
    payloads = {
        "config.json": b"config",
        "model.safetensors": b"weights",
        "special_tokens_map.json": b"special",
        "tokenizer.json": b"tokenizer",
        "tokenizer_config.json": b"tokenizer-config",
    }
    monkeypatch.setattr(assets, "GRANITE_FILES", {
        name: {"size": len(value), "sha256": hashlib.sha256(value).hexdigest()}
        for name, value in payloads.items()
    })
    monkeypatch.setattr(assets, "GRANITE_TOTAL_BYTES", sum(map(len, payloads.values())))
    seen = []

    def opener(request, timeout=0):
        seen.append(request.full_url)
        return _Response(payloads[request.full_url.rsplit("/", 1)[-1]])

    assets._download_assets(tmp_path, opener=opener)
    target = assets.model_path(tmp_path)
    assert all((target / name).read_bytes() == value for name, value in payloads.items())
    assert all(assets.GRANITE_REVISION in url for url in seen)
    assert not target.with_name(target.name + ".partial").exists()


def test_download_checksum_failure_does_not_publish_partial_model(tmp_path, monkeypatch):
    expected = b"expected"
    monkeypatch.setattr(assets, "GRANITE_FILES", {
        "config.json": {"size": len(expected), "sha256": hashlib.sha256(expected).hexdigest()},
    })
    monkeypatch.setattr(assets, "GRANITE_TOTAL_BYTES", len(expected))

    def opener(request, timeout=0):
        return _Response(b"corrupt!")

    try:
        assets._download_assets(tmp_path, opener=opener)
    except ValueError as exc:
        assert "checksum mismatch" in str(exc)
    else:
        raise AssertionError("checksum mismatch must fail")
    assert not assets.model_path(tmp_path).exists()


def test_prepare_failure_is_honest_and_keeps_not_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "_model_files_status", lambda root, verify: {
        "model_path": str(assets.model_path(root)), "model_ready": False,
        "checksum_verified": False, "missing_files": ["model.safetensors"],
        "mismatched_files": [], "expected_bytes": 1,
    })
    monkeypatch.setattr(assets, "_download_assets", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")))
    result = assets.prepare_granite_assets(tmp_path, memories=[])
    assert result["ready"] is False
    assert result["state"] == "failed"
    assert "offline" in result["error"]
    assert result["fallback"] == "FTS5+BM25"


def test_index_builder_buffers_small_encoding_batches_before_lancedb_writes():
    source = Path(assets.__file__).read_text(encoding="utf-8")
    assert "write_batch_size: int = 512" in source
    assert "pending_rows.extend(" in source
    assert "if len(pending_rows) >= write_batch_size" in source
    assert "table.add(pending_rows)" in source
    assert "table.add([_row" not in source


def test_third_party_notice_pins_apache_license_and_revision():
    root = Path(__file__).resolve().parents[1]
    notice = (root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    license_text = (root / "licenses" / "Apache-2.0.txt").read_text(encoding="utf-8")
    assert assets.GRANITE_REVISION in notice
    assert "Apache-2.0" in notice
    assert "Apache License" in license_text


def test_fresh_installers_default_to_substring_without_enabling_vector():
    root = Path(__file__).resolve().parents[1]
    mac = (root / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    linux = (root / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    windows = (root / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")
    assert 'recall["mode"] = "substring"' in mac
    assert 'recall["mode"] = "substring"' in linux
    assert '$modelCfg.recall.mode = "substring"' in windows
    for script in (mac, linux, windows):
        assert "prepare_granite_vector_assets" not in script


def test_candidate_package_contains_asset_contract_but_not_model_weights(tmp_path):
    root = Path(__file__).resolve().parents[1]
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    subprocess.run(
        [
            sys.executable,
            str(root / "tools" / "build_release_artifact.py"),
            "--source",
            "working-tree",
            "--output-dir",
            str(tmp_path),
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    package = tmp_path / f"time-library-{version}.zip"
    assert package.is_file()
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
    assert any(name.endswith("/THIRD_PARTY_NOTICES.md") for name in names)
    assert any(name.endswith("/licenses/Apache-2.0.txt") for name in names)
    assert any(name.endswith("/src/granite_vector_assets.py") for name in names)
    assert any(name.endswith("/tools/prepare_granite_vector_assets.py") for name in names)
    assert not any(name.endswith("/model.safetensors") for name in names)

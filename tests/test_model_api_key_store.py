import json
import os

from src.model_api_key_store import (
    credential_ref_for,
    credential_status,
    load_model_api_key,
    migrate_legacy_binding_secret,
    resolve_model_api_key,
    store_model_api_key,
)


def test_encrypted_store_never_contains_or_returns_plaintext(tmp_path):
    root = tmp_path / "time-library"
    ref = credential_ref_for("deepseek", "deepseek")
    secret = "fixture-private-model-key"

    status = store_model_api_key(root, ref, secret)

    key_path = root / "config" / ".model_credentials.key"
    store_path = root / "config" / "model_credentials.enc.json"
    assert status == {
        "configured": True,
        "credential_ref": ref,
        "storage": "encrypted_local_file",
        "secret_value_returned": False,
    }
    assert load_model_api_key(root, ref) == secret
    assert secret not in store_path.read_text(encoding="utf-8")
    assert secret.encode() not in key_path.read_bytes()
    if os.name != "nt":
        assert oct(key_path.stat().st_mode & 0o777) == "0o600"
        assert oct(store_path.stat().st_mode & 0o777) == "0o600"


def test_resolver_prefers_transient_then_environment_then_saved(tmp_path):
    ref = credential_ref_for("deepseek", "deepseek")
    store_model_api_key(tmp_path, ref, "saved-value")

    assert resolve_model_api_key(
        tmp_path,
        api_key_env="DEEPSEEK_API_KEY",
        credential_ref=ref,
        transient_value="request-value",
        env={"DEEPSEEK_API_KEY": "environment-value"},
    ) == ("request-value", "request")
    assert resolve_model_api_key(
        tmp_path,
        api_key_env="DEEPSEEK_API_KEY",
        credential_ref=ref,
        env={"DEEPSEEK_API_KEY": "environment-value"},
    ) == ("environment-value", "environment")
    assert resolve_model_api_key(
        tmp_path,
        api_key_env="DEEPSEEK_API_KEY",
        credential_ref=ref,
        env={},
    ) == ("saved-value", "encrypted_local_file")


def test_legacy_secret_in_environment_name_is_migrated_and_scrubbed(tmp_path):
    root = tmp_path / "time-library"
    binding = root / "config" / "zhiyi_model_binding.user.json"
    binding.parent.mkdir(parents=True)
    secret = "fixture-legacy-secret-value"
    binding.write_text(
        json.dumps(
            {
                "provider": "deepseek",
                "provider_id": "deepseek",
                "model_name": "deepseek-v4-flash",
                "api_key_env": secret,
                "secrets_stored": False,
            }
        ),
        encoding="utf-8",
    )

    result = migrate_legacy_binding_secret(root)
    migrated = json.loads(binding.read_text(encoding="utf-8"))

    assert result["migrated"] is True
    assert result["plaintext_binding_scrubbed"] is True
    assert migrated["api_key_env"] == "DEEPSEEK_API_KEY"
    assert migrated["credential_ref"] == "analysis-model:deepseek"
    assert migrated["secrets_stored"] is True
    assert secret not in binding.read_text(encoding="utf-8")
    assert load_model_api_key(root, migrated["credential_ref"]) == secret
    assert credential_status(root, migrated["credential_ref"])["configured"] is True

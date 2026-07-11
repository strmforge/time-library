import json

import pytest

from src import vector_recall_runtime as vector_runtime


def _config(**overrides):
    result = {
        "model_name": "ibm-granite/granite-embedding-97m-multilingual-r2",
        "model_path": "/models/granite-97m",
        "embedding_dim": 384,
        "pooling": "cls",
        "normalize": True,
        "distance_type": "cosine",
        "max_seq_length": 256,
        "table": "experiences_v2_granite_97m_shadow",
    }
    result.update(overrides)
    return result


def test_model_contract_requires_explicit_supported_identity():
    contract = vector_runtime.model_contract(_config())
    assert contract["model_id"] == "ibm-granite/granite-embedding-97m-multilingual-r2"
    assert contract["embedding_dim"] == 384
    assert contract["pooling"] == "cls"

    with pytest.raises(ValueError, match="unsupported vector pooling"):
        vector_runtime.model_contract(_config(pooling="guess"))
    with pytest.raises(ValueError, match="embedding_dim"):
        vector_runtime.model_contract(_config(embedding_dim=0))


def test_model_contract_expands_runtime_root(monkeypatch):
    monkeypatch.setenv("MEMCORE_ROOT", "/runtime/root")
    contract = vector_runtime.model_contract(
        _config(model_path="$MEMCORE_ROOT/runtime/model_cache/granite")
    )
    assert contract["model_path"] == "/runtime/root/runtime/model_cache/granite"


def test_table_identity_round_trip_and_mismatch_is_loud(tmp_path):
    contract = vector_runtime.model_contract(_config())
    path = vector_runtime.write_table_identity(
        tmp_path,
        contract["table"],
        contract=contract,
        row_count=16484,
        corpus_signature="corpus-sha",
        source_refs_signature="refs-sha",
        build_role="shadow_candidate",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert vector_runtime.validate_table_identity(contract, payload) == []
    assert payload["storage"] == "LanceDB"
    assert payload["row_count"] == 16484

    wrong_dimension = dict(contract, embedding_dim=1024)
    assert "table_identity_dimension_mismatch" in vector_runtime.validate_table_identity(
        wrong_dimension, payload
    )
    wrong_pooling = dict(contract, pooling="mean_unmasked")
    assert "table_identity_pooling_mismatch" in vector_runtime.validate_table_identity(
        wrong_pooling, payload
    )
    assert vector_runtime.validate_table_identity(contract, None) == ["missing_table_identity"]


def test_corpus_signatures_cover_text_and_source_refs_independently():
    base = [{
        "exp_id": "exp-1",
        "summary": "summary",
        "detail": "detail",
        "source_refs": {"source_path": "/raw/a.jsonl", "offset": 4},
    }]
    corpus_a, refs_a = vector_runtime.corpus_signatures(base)
    corpus_b, refs_b = vector_runtime.corpus_signatures([
        dict(base[0], detail="changed detail")
    ])
    corpus_c, refs_c = vector_runtime.corpus_signatures([
        dict(base[0], source_refs={"source_path": "/raw/a.jsonl", "offset": 8})
    ])
    assert corpus_a != corpus_b
    assert refs_a == refs_b
    assert corpus_a == corpus_c
    assert refs_a != refs_c


def test_default_release_config_starts_without_vector_assets():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    config = json.loads((root / "config" / "default_model_config.json").read_text(encoding="utf-8"))
    assert config["recall"]["mode"] == "substring"
    assert config["recall"]["local_vector"]["model_path"].startswith("$MEMCORE_ROOT/")

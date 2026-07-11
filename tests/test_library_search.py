import json

from src import library_search


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode()


def test_library_search_queries_p3_fts5_and_five_shelf_catalog(tmp_path):
    captured = {}

    def fake_urlopen(request, **kwargs):
        captured["payload"] = json.loads(request.data.decode())
        captured["timeout"] = kwargs["timeout"]
        return FakeResponse({
            "returned": 1,
            "total_matched": 1,
            "fts5_applied": True,
            "recall_methods_used": ["keyword", "fts5", "rrf"],
            "matched_memories": [{
                "type": "case_memory",
                "exp_id": "case-1",
                "summary": "向量迁移必须保留回源",
                "detail": "先做影子对照，再切默认。",
                "source_refs": {"source_path": "/private/source.jsonl"},
                "archive_card": {"library_id": "ZX-CASE-1", "title": "向量迁移门"},
                "matched_by": "fts5_bm25",
                "confidence": 0.91,
            }],
        })

    def fake_catalog_builder(**kwargs):
        assert kwargs["xingce_root"] == str(tmp_path)
        return {
            "ok": True,
            "catalog_entry_count": 2,
            "catalog": [
                {"library_id": "ZX-TOOL-1", "shelf": "toolbook", "title": "向量工具书", "when_to_use": "迁移向量模型时"},
                {"library_id": "ZX-ERRATA-1", "shelf": "errata", "title": "无关勘误", "when_to_use": "别处"},
            ],
        }

    result = library_search.search_library(
        "向量",
        memcore_root=tmp_path,
        urlopen=fake_urlopen,
        catalog_builder=fake_catalog_builder,
    )

    assert result["ok"] is True
    assert result["degraded"] is False
    assert result["scope"] == "all_active_memory_records_plus_five_shelf_catalog"
    assert captured["payload"]["recall_mode"] == "substring"
    assert captured["payload"]["fts5_recall"] is True
    assert captured["timeout"] == 120
    assert [item["library_id"] for item in result["items"]] == ["ZX-TOOL-1", "ZX-CASE-1"]
    assert result["items"][0]["recyclable"] is False
    assert result["items"][1]["recyclable"] is True
    assert "/private/source.jsonl" not in json.dumps(result)


def test_library_search_keeps_catalog_results_when_p3_is_down(tmp_path):
    def unavailable(*args, **kwargs):
        raise ConnectionRefusedError("p3 down")

    result = library_search.search_library(
        "工具",
        memcore_root=tmp_path,
        urlopen=unavailable,
        catalog_builder=lambda **kwargs: {
            "ok": True,
            "catalog": [{"library_id": "ZX-TOOL-1", "shelf": "toolbook", "title": "工具记录"}],
        },
    )

    assert result["ok"] is True
    assert result["degraded"] is True
    assert result["returned"] == 1
    assert result["p3"]["error"] == "ConnectionRefusedError"


def test_library_search_rejects_empty_query_without_backend_calls(tmp_path):
    result = library_search.search_library("", memcore_root=tmp_path)

    assert result["ok"] is False
    assert result["error"] == "query_required"
    assert result["write_performed"] is False

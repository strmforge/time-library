"""Recall by meaning: memories found by what they say, not only by their words."""

from __future__ import annotations

import time

import pytest

np = pytest.importorskip("numpy")

from test_distill import fake, lab, memory, reply  # noqa: E402,F401  (fixtures)
from tl_server import vectors  # noqa: E402

# A stand-in for the embedding model: words that mean the same land on the same axis.
CONCEPTS = [("服务端", "后台"), ("部署", "放在", "装在"), ("NAS", "机器"), ("结论", "要点"), ("先", "开头")]


class ConceptEmbedder:
    reranker = None
    loads = 0

    def __init__(self, entry, folder) -> None:
        ConceptEmbedder.loads += 1
        self.entry = entry

    def embed(self, texts, query=False):
        rows = []
        for text in texts:
            row = np.array([sum(text.count(word) for word in group) for group in CONCEPTS] + [0.01], dtype=np.float32)
            rows.append(row / np.linalg.norm(row))
        return np.stack(rows)


ENTRY = {"id": "concepts", "label": "测试模型", "note": "", "revision": "r1", "files": [], "pooling": "mean",
         "embed": {"repo": "test/concepts", "revision": "r1", "onnx": "model.onnx", "tokenizer": "tokenizer.json"}}


@pytest.fixture()
def meaning(monkeypatch):
    monkeypatch.setattr(vectors, "Embedder", ConceptEmbedder)
    monkeypatch.setattr(vectors, "CATALOG", [dict(ENTRY)])
    monkeypatch.setattr(vectors, "IDLE_SECONDS", 0.2)


def wait_ready(lab, indexed):
    deadline = time.time() + 10
    while time.time() < deadline:
        status = lab.call("GET", "/api/v1/admin/vectors")[1]
        if status["phase"] == "ready" and status["indexed"] == indexed:
            return status
        time.sleep(0.05)
    raise AssertionError(f"vectors never became ready: {status}")


def test_a_question_in_other_words_finds_the_memory_by_meaning(lab, meaning):
    lab.assign(lab.source())
    lab.say("s1", ("user", "服务端放在 NAS 的 Docker 里"), ("user", "回答先给结论"))
    lab.fake.replies.append(reply(memory("服务端部署在 NAS 的 Docker 应用层", (1, "服务端放在 NAS 的 Docker 里")),
                                  memory("回答先给结论再展开", (2, "回答先给结论"), kind="preference")))
    lab.run()
    question = "后台装在哪台机器上"
    assert lab.device("POST", "/api/v1/recall", {"query": question})[1]["memories"] == []  # no shared words

    status = lab.call("POST", "/api/v1/admin/vectors/enable", {})[1]
    assert status["enabled"] and status["model"]["id"] == "concepts"
    status = wait_ready(lab, 2)
    assert status["active"] == 2

    (found, *rest) = lab.device("POST", "/api/v1/recall", {"query": question})[1]["memories"]
    assert found["statement"] == "服务端部署在 NAS 的 Docker 应用层" and found["matched_by"] == "meaning" and found["similarity"] > 0.9
    # Preflight stays with words: nothing is pushed into a prompt on meaning alone.
    assert lab.device("POST", "/api/v1/recall", {"query": question, "mode": "preflight"})[1]["memories"] == []

    # New memories are embedded as they arrive.
    lab.say("s2", ("user", "要点放在开头"))
    lab.fake.replies.append(reply(memory("写汇报要点放在开头", (1, "要点放在开头"), kind="preference")))
    lab.run()
    lab.call("GET", "/api/v1/admin/vectors")
    wait_ready(lab, 3)

    lab.call("POST", "/api/v1/admin/vectors/disable", {})
    assert lab.call("GET", "/api/v1/admin/vectors")[1]["phase"] == "off"
    assert lab.device("POST", "/api/v1/recall", {"query": question})[1]["memories"] == []


def test_vectors_from_another_model_are_never_mixed(lab, meaning, monkeypatch):
    lab.assign(lab.source())
    lab.say("s1", ("user", "服务端放在 NAS 的 Docker 里"))
    lab.fake.replies.append(reply(memory("服务端部署在 NAS 的 Docker 应用层", (1, "服务端放在 NAS 的 Docker 里"))))
    lab.run()
    lab.call("POST", "/api/v1/admin/vectors/enable", {})
    wait_ready(lab, 1)
    store = lab.distiller._store
    assert store._meta("vector_model") == "concepts@r1"

    lab.call("POST", "/api/v1/admin/vectors/disable", {})
    monkeypatch.setattr(vectors, "CATALOG", [dict(ENTRY, revision="r2")])
    with store._lock:
        store._db.execute("UPDATE memory_vectors SET vector = ?", (np.zeros(6, dtype=np.float16).tobytes(),))
    lab.call("POST", "/api/v1/admin/vectors/enable", {})
    wait_ready(lab, 1)
    assert store._meta("vector_model") == "concepts@r2"
    with store._lock:
        (vector,) = store._db.execute("SELECT vector FROM memory_vectors").fetchone()
    assert np.abs(np.frombuffer(vector, dtype=np.float16)).sum() > 0  # rebuilt, not the old space kept


def test_without_the_runtime_recall_stays_with_words(lab, monkeypatch):
    monkeypatch.setattr(vectors, "runtime_available", lambda: False)
    status = lab.call("GET", "/api/v1/admin/vectors")[1]
    assert status["available"] is False and status["phase"] == "off"
    assert lab.call("POST", "/api/v1/admin/vectors/enable", {})[0] == 409


class PreferPoints:
    """A stand-in reranker: memories about 要点 first."""

    def scores(self, question, texts):
        return np.array([1.0 if "要点" in text else 0.0 for text in texts], dtype=np.float32)


def test_the_reranker_has_the_last_word_on_order(lab, meaning, monkeypatch):
    monkeypatch.setattr(ConceptEmbedder, "reranker", PreferPoints())
    lab.assign(lab.source())
    lab.say("s1", ("user", "服务端放在 NAS 上"), ("user", "要点放在开头"))
    lab.fake.replies.append(reply(memory("服务端部署在 NAS", (1, "服务端放在 NAS 上")),
                                  memory("汇报要点放在开头", (2, "要点放在开头"), kind="preference")))
    lab.run()
    lab.call("POST", "/api/v1/admin/vectors/enable", {})
    wait_ready(lab, 2)
    found = lab.device("POST", "/api/v1/recall", {"query": "服务端放在哪", "limit": 2})[1]["memories"]
    assert [m["statement"] for m in found] == ["汇报要点放在开头", "服务端部署在 NAS"]


class ScoresServer:
    """A stand-in reranker: memories about the server are clearly on topic, the rest are not."""

    def scores(self, question, texts):
        return np.array([9.0 if "服务端" in text and "后台" in question else 1.0 for text in texts], dtype=np.float32)


def test_preflight_hands_over_only_what_the_reranker_finds_clearly_on_topic(lab, meaning, monkeypatch):
    monkeypatch.setattr(ConceptEmbedder, "reranker", ScoresServer())
    lab.assign(lab.source())
    lab.say("s1", ("user", "服务端放在 NAS 的 Docker 里"), ("user", "回答先给结论"))
    lab.fake.replies.append(reply(memory("服务端部署在 NAS 的 Docker 应用层", (1, "服务端放在 NAS 的 Docker 里")),
                                  memory("回答先给结论再展开", (2, "回答先给结论"), kind="preference")))
    lab.run()
    lab.call("POST", "/api/v1/admin/vectors/enable", {})
    wait_ready(lab, 2)
    found = lab.device("POST", "/api/v1/recall", {"query": "后台装在哪台机器上了", "mode": "preflight"})[1]["memories"]
    assert [m["statement"] for m in found] == ["服务端部署在 NAS 的 Docker 应用层"]  # in other words, by meaning
    assert lab.device("POST", "/api/v1/recall", {"query": "帮我写一个快速排序函数", "mode": "preflight"})[1]["memories"] == []


class ScoresBackups:
    """A stand-in reranker: anything about a backup is about the question, equally."""

    def scores(self, question, texts):
        return np.array([6.0 if "备份" in text else 0.0 for text in texts], dtype=np.float32)


def test_a_small_projects_memories_are_read_beside_everyone_elses(lab, meaning, monkeypatch):
    """Thousands of memories elsewhere are closer in words; the few of the project worked in must still be read."""
    monkeypatch.setattr(ConceptEmbedder, "reranker", ScoresBackups())
    lab.assign(lab.source())
    lab.say("s-small", ("user", "小项目的备份放在机器的另一块盘"), cwd="D:/work/small")
    lab.fake.replies.append(reply(memory("小项目的备份放在机器的另一块盘", (1, "小项目的备份放在机器的另一块盘"))))
    lab.run()
    with lab.distiller._store._tx() as db:
        row = db.execute("SELECT agent_id, id FROM segments LIMIT 1").fetchone()
        db.execute("INSERT INTO sessions(agent_id, session_id, cwd, updated_at) VALUES(?, 's-big', 'D:/work/big', 0)", (row["agent_id"],))
        for n in range(150):
            text = f"大项目的服务端备份第 {n} 份放在 NAS 机器上,服务端部署在 NAS"
            found = db.execute("INSERT INTO memories(fingerprint, statement, kind, agent_id, session_id, created_at) VALUES(?,?,'fact',?,'s-big',0)",
                               (text, text, row["agent_id"])).lastrowid
            db.execute("INSERT INTO memory_evidence(memory_id, segment_id, quote) VALUES(?,?,?)", (found, row["id"], "备份"))
    lab.call("POST", "/api/v1/admin/vectors/enable", {})
    wait_ready(lab, 151)
    time.sleep(0.1)
    ask = {"query": "服务端在 NAS 机器上的备份放在哪", "limit": 5}
    elsewhere = lab.device("POST", "/api/v1/recall", ask)[1]["memories"]
    assert not any(m["statement"].startswith("小项目") for m in elsewhere)
    here = lab.device("POST", "/api/v1/recall", {**ask, "folder": "D:/work/small/src"})[1]["memories"]
    assert here[0]["statement"].startswith("小项目") and here[0]["here"]
    assert len(here) == 5 and not any(m["here"] for m in here[1:])  # the others are still there

"""Moving a computer off an earlier install: find, import, stop, keep a copy, remove."""

from __future__ import annotations

import json
import tarfile

import pytest

import tl_client.__main__ as cli
from tl_client import old_install


@pytest.fixture()
def old(tmp_path, monkeypatch):
    root = tmp_path / "Application Support" / "time-library"
    mirror = root / "memory" / "my-mac" / "codex" / "codex_session_jsonl"
    mirror.mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "p3_recall.py").write_text("# old service\n", encoding="utf-8")
    line = lambda role, text: json.dumps({"timestamp": "2026-06-01T00:00:00Z", "type": "response_item",  # noqa: E731
                                          "payload": {"type": "message", "role": role, "content": [{"type": "input_text", "text": text}]}},
                                         ensure_ascii=False)
    session = "0a1b2c3d-1111-2222-3333-444455556666"
    (mirror / f"{session}.jsonl").write_text("\n".join([line("user", "旧对话一"), line("assistant", "好的")]) + "\n", encoding="utf-8")
    (mirror / f"{session}.seg2.jsonl").write_text(line("user", "旧对话二") + "\n", encoding="utf-8")
    (mirror / f"{session}.jsonl.canonical_dialogue.jsonl").write_text(line("user", "副本") + "\n", encoding="utf-8")
    (mirror / f"{session}.jsonl.meta.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(old_install, "candidate_roots", lambda: [root] if root.exists() else [])
    monkeypatch.setattr(old_install, "services", lambda: [])
    monkeypatch.setattr(old_install, "_processes_under", lambda _root: [])
    return root


def test_scan_finds_the_history_and_says_how_to_import_it(old):
    report = old_install.scan("PY TL/tl.py")
    (install,) = report["installs"]
    (history,) = install["history"]
    assert (history["computer"], history["source"], history["files"], history["shape"]) == ("my-mac", "codex", 2, "response_item_payload_message")
    assert "import --agent" in history["import_command"] and "--format response_item_payload_message" in history["import_command"]
    assert '--glob "**/*.seg[0-9].jsonl"' in history["import_command"]


def test_nothing_is_removed_before_a_checked_copy_exists(old, tmp_path):
    home = tmp_path / "client-home"
    with pytest.raises(SystemExit, match="not archived yet"):
        old_install.remove(home)
    assert old.exists()
    (record,) = old_install.archive(tmp_path / "keep", home)
    assert record["files"] == 5 and record["archive"].endswith(".tar")
    with tarfile.open(record["archive"]) as archive:
        names = archive.getnames()
    assert "time-library/src/p3_recall.py" in names
    removed = old_install.remove(home)
    assert not old.exists() and any("folder" in line for line in removed)


def test_the_commands_are_on_the_client(old, tmp_path, capsys):
    assert cli.main(["--home", str(tmp_path / "h"), "old-install", "scan"]) == 0
    out = capsys.readouterr().out
    assert "earlier install:" in out and "my-mac / codex: 2 files" in out
    assert cli.main(["--home", str(tmp_path / "h"), "old-install", "archive", "--to", str(tmp_path / "keep")]) == 0
    assert "checked" in capsys.readouterr().out


def test_command_output_in_another_encoding_is_still_read(monkeypatch):
    import subprocess

    class Done:
        stdout = "进程 C:\\old\\time-library\\x.py".encode("gbk")

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())
    assert "time-library" in old_install._run(["ps"])
    Done.stdout = None
    assert old_install._run(["ps"]) == ""


def test_only_processes_inside_the_old_folder_count_not_a_sibling_with_the_same_start():
    old = "C:\\Users\\me\\AppData\\Local\\time-library"
    assert old_install.runs_from(f'"C:\\Python\\python.exe" {old}\\src\\p3_recall.py serve', old)
    assert old_install.runs_from(f'python "{old}"', old)
    assert old_install.runs_from(f"python {old}", old)
    assert not old_install.runs_from(
        "C:\\Python\\pythonw.exe -m tl_client run --log C:\\Users\\me\\AppData\\Local\\time-library-client\\client.log", old)
    assert not old_install.runs_from("python /home/me/.local/share/time-library-client/tl.py run", "/home/me/.local/share/time-library")
    assert old_install.runs_from("python /home/me/.local/share/time-library/src/x.py", "/home/me/.local/share/time-library")

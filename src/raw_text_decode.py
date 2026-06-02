"""Encoding-tolerant raw text readers for source-backed memory."""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

TEXT_REPLACEMENT_CHAR = "\ufffd"


def looks_utf16(data: bytes) -> str:
    sample = data[:4096]
    if sample.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if sample.startswith(b"\xfe\xff"):
        return "utf-16-be"
    if len(sample) < 8:
        return ""
    even_nuls = sample[0::2].count(0)
    odd_nuls = sample[1::2].count(0)
    even_len = max(1, len(sample[0::2]))
    odd_len = max(1, len(sample[1::2]))
    if odd_nuls / odd_len > 0.25 and odd_nuls > even_nuls * 3:
        return "utf-16-le"
    if even_nuls / even_len > 0.25 and even_nuls > odd_nuls * 3:
        return "utf-16-be"
    return ""


def decode_text_bytes(data: bytes, *, at_file_start: bool = False) -> str:
    if not data:
        return ""

    utf16_hint = looks_utf16(data)
    preferred: list[str] = []
    if utf16_hint:
        preferred.append(utf16_hint)
        preferred.append("utf-16")
    if at_file_start:
        preferred.append("utf-8-sig")
    preferred.extend(["utf-8", "gb18030", "cp936"])

    encodings: list[str] = []
    for encoding in preferred:
        if encoding not in encodings:
            encodings.append(encoding)

    best_text = ""
    best_score: tuple[int, int, int] | None = None
    for encoding in encodings:
        try:
            text = data.decode(encoding)
            replacement_count = 0
        except UnicodeDecodeError:
            text = data.decode(encoding, errors="replace")
            replacement_count = text.count(TEXT_REPLACEMENT_CHAR)
        except Exception:
            continue
        nul_count = text.count("\x00")
        control_count = sum(1 for ch in text if ord(ch) < 32 and ch not in "\r\n\t")
        score = (replacement_count, nul_count + control_count, encodings.index(encoding))
        if best_score is None or score < best_score:
            best_text = text
            best_score = score
        if replacement_count == 0 and nul_count == 0 and control_count == 0:
            break
    return best_text.lstrip("\ufeff")


def jsonl_line_separator_for_sample(sample: bytes) -> bytes:
    encoding = looks_utf16(sample)
    if encoding == "utf-16-le":
        return b"\n\x00"
    if encoding == "utf-16-be":
        return b"\x00\n"
    return b"\n"


def iter_decoded_jsonl_lines(path: Path | str) -> Iterator[tuple[int, int, str]]:
    resolved = Path(path)
    with open(resolved, "rb") as f:
        sample = f.read(4096)
        line_sep = jsonl_line_separator_for_sample(sample)
        f.seek(0)
        if line_sep == b"\n":
            while True:
                start = f.tell()
                raw = f.readline()
                if not raw:
                    break
                end = f.tell()
                yield start, end, decode_text_bytes(raw, at_file_start=start == 0)
            return

        buffer = b""
        buffer_start = f.tell()
        while True:
            chunk = f.read(64 * 1024)
            if not chunk:
                break
            buffer += chunk
            while True:
                sep_index = buffer.find(line_sep)
                if sep_index < 0:
                    break
                line_end = sep_index + len(line_sep)
                raw = buffer[:line_end]
                start = buffer_start
                end = buffer_start + line_end
                yield start, end, decode_text_bytes(raw, at_file_start=start == 0)
                buffer = buffer[line_end:]
                buffer_start = end
        if buffer:
            start = buffer_start
            end = buffer_start + len(buffer)
            yield start, end, decode_text_bytes(buffer, at_file_start=start == 0)

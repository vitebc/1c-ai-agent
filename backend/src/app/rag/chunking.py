"""Нарезка markdown-текста на чанки для RAG.

Простой детерминированный сплиттер без зависимостей: режет по пустым строкам,
пакует блоки до max_chars, к каждому чанку prepend'ит последний заголовок
для контекста, соседние чанки пересекаются на overlap символов.
"""

from __future__ import annotations

import re

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def split_markdown(text: str, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []

    blocks: list[tuple[str | None, str]] = []  # (heading, block)
    heading: str | None = None
    for raw in re.split(r"\n\s*\n", text):
        block = raw.strip()
        if not block:
            continue
        m = re.match(r"^(#{1,3})\s+(.+)$", block, re.M)
        if m and len(block.splitlines()) == 1:
            heading = m.group(2).strip()
            continue
        blocks.append((heading, block))

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    current_heading: str | None = None

    def flush() -> None:
        if current:
            prefix = f"{current_heading}\n\n" if current_heading else ""
            chunks.append(prefix + "\n\n".join(current))

    for blk_heading, block in blocks:
        if blk_heading != current_heading and current:
            flush()
            current, current_len = [], 0
        current_heading = blk_heading
        prefix_len = len(current_heading) + 2 if current_heading else 0
        for piece in _split_oversized(block, max_chars - prefix_len):
            if current_len + len(piece) + 2 > max_chars and current:
                flush()
                current, current_len = [], 0
            current.append(piece)
            current_len += len(piece) + 2
    flush()

    return _apply_overlap(chunks, overlap)


def _split_oversized(block: str, limit: int) -> list[str]:
    if len(block) <= limit:
        return [block]
    pieces: list[str] = []
    for sent in _SENTENCE_END.split(block):
        if len(sent) <= limit:
            pieces.append(sent)
        else:  # одно длинное предложение/строка — рубим по символам
            pieces.extend(sent[i : i + limit] for i in range(0, len(sent), limit))
    # Перепаковка мелких кусков обратно в лимит
    packed: list[str] = []
    buf = ""
    for p in pieces:
        if len(buf) + len(p) + 1 <= limit:
            buf = f"{buf} {p}".strip()
        else:
            if buf:
                packed.append(buf)
            buf = p
    if buf:
        packed.append(buf)
    return packed


def _apply_overlap(chunks: list[str], overlap: int) -> list[str]:
    if overlap <= 0 or len(chunks) < 2:
        return chunks
    out = [chunks[0]]
    for chunk in chunks[1:]:
        tail = out[-1][-overlap:]
        cut = tail.find(" ")
        tail = tail[cut + 1 :] if cut != -1 else tail
        out.append(f"{tail}\n\n{chunk}" if tail else chunk)
    return out

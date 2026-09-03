from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date


@dataclass
class Chunk:
    text: str
    chunk_index: int
    published_at: date | None


_SENTENCE_END = re.compile(r"(?<=[.!?。])\s+")


def chunk_text(text: str, published_at: date | None) -> list[Chunk]:
    """Split text into chunks of 50–500 characters.

    1. Split on paragraph boundaries (blank lines).
    2. Paragraphs longer than 500 chars are further split at sentence boundaries.
    3. Segments shorter than 50 chars are discarded.
    """
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    segments: list[str] = []

    for para in paragraphs:
        if len(para) <= 500:
            segments.append(para)
        else:
            parts = _SENTENCE_END.split(para)
            current = ""
            for part in parts:
                if len(current) + len(part) + 1 <= 500:
                    current = (current + " " + part).strip() if current else part
                else:
                    if current:
                        segments.append(current)
                    current = part
            if current:
                segments.append(current)

    chunks: list[Chunk] = []
    for i, seg in enumerate(segments):
        if len(seg) >= 50:
            chunks.append(Chunk(text=seg, chunk_index=i, published_at=published_at))

    return chunks

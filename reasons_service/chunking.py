"""Chunk markdown documents for FTS RAG."""

import re


def _hard_split(text: str, max_chars: int) -> list[str]:
    """Split text that exceeds max_chars on sentence boundaries, else mid-word."""
    if len(text) <= max_chars:
        return [text]
    pieces = []
    while text:
        if len(text) <= max_chars:
            pieces.append(text)
            break
        # Try to split at last sentence boundary within budget
        cut = text[:max_chars]
        split_at = max(cut.rfind(". "), cut.rfind(".\n"), cut.rfind("? "), cut.rfind("! "))
        if split_at > max_chars // 2:
            split_at += 1  # include the punctuation
        else:
            # Fall back to last space
            split_at = cut.rfind(" ")
            if split_at < max_chars // 2:
                split_at = max_chars  # no good break point, hard cut
        pieces.append(text[:split_at].rstrip())
        text = text[split_at:].lstrip()
    return pieces


def chunk_markdown(content: str, max_chars: int = 1000) -> list[dict]:
    """Split markdown into chunks by ## headers, then paragraphs, hard-capped at max_chars.

    Returns list of {"section": str, "text": str, "chunk_index": int}.
    """
    # Split on ## headers, keeping the header text
    parts = re.split(r"^(##\s+.+)$", content, flags=re.MULTILINE)

    chunks: list[dict] = []
    current_section = ""

    for part in parts:
        if part.startswith("## "):
            current_section = part.lstrip("# ").strip()
            continue

        # Split long sections by double newlines (paragraphs)
        paragraphs = part.split("\n\n")
        buffer = ""
        for para in paragraphs:
            if len(buffer) + len(para) > max_chars and buffer.strip():
                for piece in _hard_split(buffer.strip(), max_chars):
                    chunks.append({
                        "section": current_section,
                        "text": piece,
                        "chunk_index": len(chunks),
                    })
                buffer = para
            else:
                buffer = buffer + "\n\n" + para if buffer else para
        if buffer.strip():
            for piece in _hard_split(buffer.strip(), max_chars):
                chunks.append({
                    "section": current_section,
                    "text": piece,
                    "chunk_index": len(chunks),
                })

    return chunks

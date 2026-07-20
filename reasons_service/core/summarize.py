"""Summarize source documents into entries using LLM.

Ported from expert_build/summarize.py — replaces CLI invocation with LangChain ChatModel,
replaces filesystem writes with DB inserts.
"""

import hashlib
import re

from reasons_service.llm.provider import get_chat_model
from reasons_service.llm.prompts import SUMMARIZE


def strip_frontmatter(content: str) -> str:
    """Strip YAML frontmatter from markdown content."""
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            return content[end + 3:].strip()
    return content


def generate_entry_id(topic: str, content: str) -> str:
    """Generate a deterministic entry ID from topic and content."""
    h = hashlib.sha256(f"{topic}:{content[:200]}".encode()).hexdigest()
    return h[:12]


def extract_title(summary: str, fallback: str) -> str:
    """Extract a title from the summary or use fallback."""
    title_match = re.search(r"^#+ (.+)$", summary, re.MULTILINE)
    if title_match:
        return title_match.group(1)
    return fallback.replace("-", " ").title()


def summarize_source(content: str, domain: str = "general", model: str | None = None) -> str:
    """Summarize a single source document using LLM.

    Args:
        content: Source document markdown content (frontmatter stripped).
        domain: Domain context for the summary.
        model: Model name to use.

    Returns:
        Summary markdown text.
    """
    # Truncate very long documents
    if len(content) > 30000:
        content = content[:30000] + "\n\n[Truncated — original was longer]"

    prompt = SUMMARIZE.format(content=content, domain=domain)
    chat_model = get_chat_model(model)
    response = chat_model.invoke(prompt)
    return response.content


def summarize_batch(
    sources: list[dict],
    domain: str = "general",
    model: str | None = None,
    on_progress: callable = None,
) -> list[dict]:
    """Summarize a batch of sources into entries.

    Args:
        sources: List of {id, slug, content} dicts.
        domain: Domain context for summaries.
        model: Model name to use.
        on_progress: Callback(source_slug, status, count).

    Returns:
        List of {id, topic, title, content, source_id} entry dicts.
    """
    entries = []

    for source in sources:
        content = strip_frontmatter(source["content"])
        if not content.strip():
            if on_progress:
                on_progress(source["slug"], "skip", len(entries))
            continue

        try:
            summary = summarize_source(content, domain=domain, model=model)
        except Exception as e:
            if on_progress:
                on_progress(source["slug"], "error", len(entries))
            continue

        topic = source["slug"]
        title = extract_title(summary, topic)
        entry_id = generate_entry_id(topic, summary)

        entries.append({
            "id": entry_id,
            "topic": topic,
            "title": title,
            "content": summary,
            "source_id": source.get("id"),
        })

        if on_progress:
            on_progress(source["slug"], "done", len(entries))

    return entries

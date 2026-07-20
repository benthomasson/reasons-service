"""Propose beliefs from entries using LLM.

Ported from expert_build/propose.py — replaces CLI invocation with LangChain ChatModel,
replaces file-based output with structured dicts for DB storage.
"""

import re

from reasons_service.llm.provider import get_chat_model
from reasons_service.llm.prompts import PROPOSE_BELIEFS


def parse_proposals(text: str) -> list[dict]:
    """Parse LLM output into list of proposed belief dicts.

    Handles both formats:
        ### [ACCEPT] belief-id           ### [ACCEPT] belief-id
        claim text                       claim text
        - Source: path                   Source: path
    """
    beliefs = []
    pattern = re.compile(
        r"### \[(ACCEPT|REJECT)\]\s+(\S+)\s*\n"
        r"(.+?)\n"
        r"(?:\n\s*)?(?:- )?[Ss]ource:\s*(.+?)(?:\n|$)",
    )

    for match in pattern.finditer(text):
        status, belief_id, claim_text, source = match.groups()
        beliefs.append({
            "id": belief_id.strip(),
            "text": claim_text.strip(),
            "source": source.strip(),
            "llm_suggestion": status.upper(),
        })

    return beliefs


def propose_from_entries(
    entries: list[dict],
    model: str | None = None,
    batch_size: int = 5,
    on_progress: callable = None,
) -> list[dict]:
    """Extract belief candidates from entries using LLM.

    Args:
        entries: List of {id, topic, title, content} dicts.
        model: Model name to use.
        batch_size: Number of entries per LLM call.
        on_progress: Callback(batch_num, total_batches, beliefs_so_far).

    Returns:
        List of {id, text, source, llm_suggestion} dicts.
    """
    if not entries:
        return []

    # Batch entries together
    batches = []
    current_batch = []
    for entry in entries:
        content = entry.get("content", "")
        if len(content) > 10000:
            content = content[:10000] + "\n[Truncated]"
        current_batch.append(
            f"--- ENTRY: {entry.get('topic', 'unknown')} ---\n{content}"
        )
        if len(current_batch) >= batch_size:
            batches.append("\n\n".join(current_batch))
            current_batch = []
    if current_batch:
        batches.append("\n\n".join(current_batch))

    # Process each batch through LLM
    chat_model = get_chat_model(model)
    all_beliefs = []

    for i, batch_text in enumerate(batches):
        prompt = PROPOSE_BELIEFS.format(entries=batch_text)

        try:
            response = chat_model.invoke(prompt)
            beliefs = parse_proposals(response.content)
            all_beliefs.extend(beliefs)
        except Exception:
            continue

        if on_progress:
            on_progress(i + 1, len(batches), len(all_beliefs))

    return all_beliefs

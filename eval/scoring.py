"""Scoring: MC exact-match and LLM-as-judge for open-ended."""

import asyncio
import json
import os
import re
from dataclasses import dataclass


def extract_answer(response: str) -> str:
    """Extract the answer letter from LLM response.

    Ported from expert-agent-builder/expert_build/exam.py.
    """
    # Look for ANSWER: line
    match = re.search(r"ANSWER:\s*(.+)", response, re.IGNORECASE)
    if match:
        ans = match.group(1).strip()
        # Extract letter from formats like "b)", "b.", "b:", "b ", "b**", "**b**"
        letter_match = re.match(r"\*{0,2}([a-d])\*{0,2}[.):\s*]", ans, re.IGNORECASE)
        if letter_match:
            return letter_match.group(1).lower()
        # Plain letter possibly with trailing markdown
        clean = re.sub(r"[*_`]", "", ans).strip()
        if len(clean) == 1 and clean.lower() in "abcd":
            return clean.lower()
        return ans

    # Fallback: look for a single letter on its own line
    lines = response.strip().split("\n")
    for line in reversed(lines):
        line = re.sub(r"[*_`]", "", line).strip()
        if re.match(r"^[a-d]$", line, re.IGNORECASE):
            return line.lower()

    return response.strip()[:100]


@dataclass
class MCScore:
    question_id: str
    expected: str
    extracted: str
    correct: bool
    objective: str | None = None


def score_mc(question: dict, response: str) -> MCScore:
    """Score a multiple-choice question."""
    extracted = extract_answer(response)
    expected = question["correct"].strip().lower()
    return MCScore(
        question_id=question["id"],
        expected=expected,
        extracted=extracted,
        correct=extracted == expected,
        objective=question.get("objective"),
    )


@dataclass
class OpenEndedScore:
    question_id: str
    correctness: int
    correctness_max: int
    completeness: int
    completeness_max: int
    citation_quality: int
    citation_max: int = 3
    justifications: dict | None = None

    @property
    def total(self) -> int:
        return self.correctness + self.completeness + self.citation_quality

    @property
    def total_max(self) -> int:
        return self.correctness_max + self.completeness_max + self.citation_max


JUDGE_PROMPT = """You are evaluating an AI system's answer to a domain question about Ansible Automation Platform 2.6.

QUESTION: {question}

RUBRIC:
- Correctness criteria: {correctness}
- Completeness criteria: {completeness}
- Key facts that should be mentioned: {key_facts}
- Maximum score: {max_score}

SYSTEM RESPONSE:
{response}

Score this response on three dimensions. For each, provide a score and one-sentence justification.

1. CORRECTNESS (0-{max_score}): Are the stated facts accurate? Any hallucinations?
2. COMPLETENESS (0-{max_score}): Does it cover the key facts listed in the rubric?
3. CITATION_QUALITY (0-3): Does it reference specific entries, beliefs, source documents, or documentation sections?

Format your response EXACTLY as:
CORRECTNESS: <score>/{max_score} — <justification>
COMPLETENESS: <score>/{max_score} — <justification>
CITATION_QUALITY: <score>/3 — <justification>"""


async def judge_open_ended(question: dict, response: str) -> OpenEndedScore:
    """Use claude -p as LLM judge for open-ended questions."""
    rubric = question["rubric"]
    max_score = rubric.get("max_score", 10)

    prompt = JUDGE_PROMPT.format(
        question=question["text"],
        correctness=rubric.get("correctness", ""),
        completeness=rubric.get("completeness", ""),
        key_facts=json.dumps(rubric.get("key_facts", [])),
        max_score=max_score,
        response=response,
    )

    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", prompt,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
    judge_text = stdout.decode()

    # Parse scores
    justifications = {}

    def parse_dim(name: str, max_val: int) -> int:
        m = re.search(rf"{name}:\s*(\d+)/{max_val}", judge_text, re.IGNORECASE)
        if m:
            # Capture justification
            full = re.search(rf"{name}:\s*\d+/{max_val}\s*[—-]\s*(.+)", judge_text, re.IGNORECASE)
            if full:
                justifications[name.lower()] = full.group(1).strip()
            return min(int(m.group(1)), max_val)
        return 0

    correctness = parse_dim("CORRECTNESS", max_score)
    completeness = parse_dim("COMPLETENESS", max_score)
    citation = parse_dim("CITATION_QUALITY", 3)

    return OpenEndedScore(
        question_id=question["id"],
        correctness=correctness,
        correctness_max=max_score,
        completeness=completeness,
        completeness_max=max_score,
        citation_quality=citation,
        justifications=justifications,
    )

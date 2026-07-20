"""Scoring for meta-expert synthesis quality — CIAK dimensions."""

import asyncio
import json
import os
import re
from dataclasses import dataclass, field


@dataclass
class CIAKScore:
    question_id: str
    correctness: float  # 0.0-1.0
    integration: float  # 0.0-1.0
    attribution: float  # 0.0-1.0
    completeness: float  # 0.0-1.0 (required facts found / total)
    facts_found: list[str] = field(default_factory=list)
    facts_missing: list[str] = field(default_factory=list)
    justifications: dict = field(default_factory=dict)

    @property
    def composite(self) -> float:
        """Weighted CIAK composite score. Integration weighted higher — it's the meta-expert's unique value."""
        return (
            0.25 * self.correctness
            + 0.35 * self.integration
            + 0.15 * self.attribution
            + 0.25 * self.completeness
        )


def score_completeness(answer: str, required_facts: list[str]) -> tuple[float, list[str], list[str]]:
    """Score completeness by checking which required facts appear in the answer.

    Each fact is a string with alternatives separated by ' or '.
    A fact is present if any alternative appears (case-insensitive).
    """
    answer_lower = answer.lower()
    found = []
    missing = []

    for fact in required_facts:
        alternatives = [alt.strip().lower() for alt in fact.split(" or ")]
        if any(alt in answer_lower for alt in alternatives):
            found.append(fact)
        else:
            missing.append(fact)

    rate = len(found) / len(required_facts) if required_facts else 1.0
    return rate, found, missing


CIAK_JUDGE_PROMPT = """You are evaluating a meta-expert AI system's synthesized answer. The meta-expert consults multiple domain experts and combines their answers.

QUESTION: {question}

GROUND TRUTH (reference answer):
{ground_truth}

EXPERTS CONSULTED: {experts_consulted}

META-EXPERT'S ANSWER:
{answer}

Score this synthesized answer on three dimensions. For each, give a score from 0.0 to 1.0 and a one-sentence justification.

1. CORRECTNESS: Are the stated facts from each domain accurate? Is anything hallucinated or wrong?
   - 1.0 = all facts accurate, no hallucinations
   - 0.5 = mostly accurate with minor errors
   - 0.0 = major factual errors or hallucinations

2. INTEGRATION: Are the domain perspectives properly combined into a coherent answer? Or are they just concatenated as separate sections?
   - 1.0 = seamlessly woven together, shows how domains interact
   - 0.5 = some integration but mostly separate sections
   - 0.0 = just pasted expert answers side by side with no synthesis

3. ATTRIBUTION: Is it clear which domain or expert contributed which information? Can the reader tell what came from which knowledge base?
   - 1.0 = clear attribution throughout (e.g., "According to the RHEL expert..." or domain-specific sections)
   - 0.5 = some attribution but inconsistent
   - 0.0 = no indication of information sources

Format your response EXACTLY as (use decimal scores like 0.8, not fractions):
CORRECTNESS: <score> — <justification>
INTEGRATION: <score> — <justification>
ATTRIBUTION: <score> — <justification>"""


async def judge_ciak(
    question: dict,
    answer: str,
    experts_consulted: list[str],
    judge_model: str = "sonnet",
) -> tuple[float, float, float, dict]:
    """Use LLM-as-judge to score C, I, A dimensions.

    Returns (correctness, integration, attribution, justifications).
    """
    prompt = CIAK_JUDGE_PROMPT.format(
        question=question["question"],
        ground_truth=question["ground_truth"],
        experts_consulted=", ".join(experts_consulted) if experts_consulted else "(none)",
        answer=answer,
    )

    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", "--model", judge_model, prompt,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
    judge_text = stdout.decode()

    justifications = {}

    def parse_dim(name: str) -> float:
        m = re.search(rf"{name}:\s*([\d.]+)", judge_text, re.IGNORECASE)
        if m:
            full = re.search(rf"{name}:\s*[\d.]+\s*[—-]\s*(.+)", judge_text, re.IGNORECASE)
            if full:
                justifications[name.lower()] = full.group(1).strip()
            return min(float(m.group(1)), 1.0)
        return 0.0

    correctness = parse_dim("CORRECTNESS")
    integration = parse_dim("INTEGRATION")
    attribution = parse_dim("ATTRIBUTION")

    return correctness, integration, attribution, justifications


async def score_synthesis(
    question: dict,
    answer: str,
    experts_consulted: list[str],
    judge_model: str = "sonnet",
) -> CIAKScore:
    """Full CIAK scoring for a synthesis question."""
    # Deterministic: keyword-based completeness
    completeness, found, missing = score_completeness(answer, question["required_facts"])

    # LLM-as-judge: C, I, A
    correctness, integration, attribution, justifications = await judge_ciak(
        question, answer, experts_consulted, judge_model
    )

    return CIAKScore(
        question_id=question["id"],
        correctness=correctness,
        integration=integration,
        attribution=attribution,
        completeness=completeness,
        facts_found=found,
        facts_missing=missing,
        justifications=justifications,
    )


def aggregate_synthesis_scores(scores: list[CIAKScore]) -> dict:
    """Aggregate CIAK scores across questions."""
    n = len(scores)
    if not n:
        return {}

    return {
        "count": n,
        "avg_correctness": round(sum(s.correctness for s in scores) / n, 4),
        "avg_integration": round(sum(s.integration for s in scores) / n, 4),
        "avg_attribution": round(sum(s.attribution for s in scores) / n, 4),
        "avg_completeness": round(sum(s.completeness for s in scores) / n, 4),
        "avg_composite": round(sum(s.composite for s in scores) / n, 4),
        "perfect_completeness": sum(1 for s in scores if s.completeness == 1.0),
    }

"""LLM prompt templates — ported from expert-agent-builder."""

SUMMARIZE = """You are an expert analyst creating a structured knowledge entry.

Given the following document, create a comprehensive summary covering:

## Overview
A 2-3 sentence overview of what this document covers.

## Key Concepts
The most important concepts, terms, and ideas. For each, provide a brief explanation.

## Commands and Syntax
Any commands, configuration syntax, or code examples mentioned.

## Relationships
How this topic relates to other topics in the domain: {domain}

## Exam-Relevant Points
Key facts that would be important for a certification exam.

---

DOCUMENT:
{content}
"""

PROPOSE_BELIEFS = """You are extracting factual claims from knowledge entries.

Review the following entries and extract clear, verifiable beliefs.
Each belief should be:
- A single factual claim (not an opinion)
- Specific enough to be verified against documentation
- Independent (understandable without context)

Format each belief as:

### [ACCEPT] belief-id-in-kebab-case
The factual claim text.

Source: entries/path/to/source.md

---

If a claim is uncertain or likely wrong, use:
### [REJECT] belief-id
Reason for rejection.

---

ENTRIES:
{entries}
"""

EXAM_ANSWER = """You are an expert in {domain}.

Answer the following exam question using ONLY the provided beliefs/knowledge.
Give the letter of the correct answer.

BELIEFS:
{beliefs}

QUESTION:
{question}

{choices}

Answer with just the letter (a, b, c, or d) and a brief explanation.
"""

CERT_MATCH = """You are matching certification objectives to a knowledge base.

Given this certification objective:
{objective}

And these beliefs:
{beliefs}

Which beliefs are relevant to this objective? List the belief IDs that cover this objective.
If no beliefs match, say "NO MATCH".
"""

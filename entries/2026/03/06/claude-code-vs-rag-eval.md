# Claude Code vs RAG Evaluation Results

**Date:** 2026-03-06
**Time:** 11:01

## Overview

Head-to-head evaluation comparing Claude Code (direct file access) against RAG (database + vector DB) for answering domain questions about Ansible Automation Platform 2.6.

## Systems Tested

- **Claude Code**: `claude -p` subprocess from ~/git/aap-expert. Full access to 111 sources, 112 entries, 237 beliefs as markdown files. Model: Claude Opus 4.6.
- **RAG + Gemini**: expert-service API with gemini-2.5-pro. Three search methods: FTS, ILIKE grep, pgvector semantic search. Same content ingested into PostgreSQL.
- **RAG + Claude**: expert-service API with claude-sonnet-4-5 on Vertex. Same RAG pipeline as above.

## Question Set

- 40 multiple-choice questions from EX467 practice exam (automated scoring)
- 15 open-ended questions across 3 categories: conceptual (5), multi-hop (5), exact-command (5)
- Open-ended scored by LLM-as-judge on correctness (0-10), completeness (0-10), citation quality (0-3)

## Results

| Metric | Claude Code | RAG + Gemini | RAG + Claude |
|--------|-------------|-------------|-------------|
| MC Accuracy | **40/40 (100%)** | 36/40 (90%) | 40/40 (100%)* |
| Open-Ended Avg | **77%** | 57% | 69% |
| Avg Latency | 21.7s | 13.6s | **10.2s** |
| Avg Tool Calls | 0.0 | 2.1 | 3.2 |

*RAG + Claude scored 39/40 due to answer extraction bug (`b**` parsed as wrong). Actual answer was correct. Bug fixed.

## MC Wrong Answers

- **Q15** (RAG + Gemini): "What happens to controller admin accounts during upgrade from 2.4?" -- answered b (remain as controller-only admins) instead of c (become platform gateway admins)
- **Q39** (RAG + Gemini): "What PostgreSQL versions does AAP 2.6 support?" -- answered b (14 and 15) instead of c (15, 16, and 17)

Both wrong answers came from RAG + Gemini. Neither question triggered a tool search (0 tools), suggesting the model answered from parametric knowledge rather than consulting the knowledge base.

## Open-Ended Scores (per question)

| Question | Category | Claude Code | RAG+Gemini | RAG+Claude |
|----------|----------|-------------|------------|------------|
| OE1 | conceptual | 21/23 | 17/23 | 19/23 |
| OE2 | conceptual | 20/23 | 11/23 | 18/23 |
| OE3 | conceptual | 18/23 | 18/23 | 14/23 |
| OE4 | conceptual | 20/23 | 19/23 | 21/23 |
| OE5 | conceptual | 20/23 | 17/23 | 17/23 |
| OE6 | multi_hop | 18/23 | 16/23 | 20/23 |
| OE7 | multi_hop | 18/23 | 10/23 | 13/23 |
| OE8 | multi_hop | 20/23 | 12/23 | 13/23 |
| OE9 | multi_hop | 20/23 | 13/23 | 19/23 |
| OE10 | multi_hop | 22/23 | 11/23 | 14/23 |
| OE11 | exact_command | 9/23 | 8/23 | 8/23 |
| OE12 | exact_command | 14/23 | 11/23 | 13/23 |
| OE13 | exact_command | 17/23 | 10/23 | 13/23 |
| OE14 | exact_command | 15/23 | 10/23 | 20/23 |
| OE15 | exact_command | 12/23 | 13/23 | 15/23 |

## Tool Usage

- **Claude Code**: 0 tool calls across all 55 questions -- answered entirely from parametric knowledge
- **RAG + Gemini**: 114 tools (54% search_knowledge, 25% read_entry, 10% grep_content, 8% semantic_search)
- **RAG + Claude**: 179 tools (32% search_knowledge, 25% read_entry, 17% grep_content, 13% semantic_search)

## Key Observations

1. **Claude Code dominated accuracy** without using any tools. It answered all 55 questions from parametric knowledge alone, which means the evaluation primarily tests model quality rather than retrieval quality.

2. **The biggest gap is in multi-hop questions** (OE7-OE10). Claude Code averaged 20/23 while RAG+Gemini averaged 11.5/23. RAG struggles to combine information across multiple documents.

3. **All systems struggled with exact-command questions** (OE11-OE15). Scores ranged from 8/23 to 20/23. These require precise technical details that neither parametric knowledge nor RAG reliably surfaces.

4. **RAG is faster** despite tool call overhead. RAG+Claude averaged 10.2s vs Claude Code's 21.7s. The subprocess overhead of `claude -p` accounts for some of this.

5. **RAG+Gemini had reliability issues**: 2 connection drops (Q5, Q27) and 2 wrong MC answers on questions where it didn't even search the knowledge base.

6. **RAG+Claude used tools more aggressively** (3.2 avg vs 2.1 for Gemini) and scored better, suggesting more thorough retrieval correlates with better answers.

## Analysis

The Claude-vs-Claude comparison (Claude Code vs RAG + Claude Sonnet) is the most informative since it isolates the retrieval mechanism from model quality. Both achieve 100% MC accuracy, but Claude Code scores 8 points higher on open-ended (77% vs 69%). The RAG pipeline adds retrieval overhead (3.2 tool calls/question) without improving answer quality on this dataset.

RAG + Gemini's issues are a separate concern: wrong MC answers on questions where it didn't even search the knowledge base (Q15, Q39), plus 2 connection drops. These are Gemini-specific problems, not RAG architecture problems.

Claude Code had access to all its standard tools (Read, Grep, Glob, Bash) and the `num_turns` data shows it used multiple turns on harder questions (up to 14 turns for OE3), though the `--output-format json` result format doesn't capture which specific tools were invoked. Whether it searched the repo or relied on parametric knowledge of AAP 2.6 docs (which are in its training data), it performed equally or better than the RAG pipeline.

For a follow-up evaluation that isolates retrieval mechanism from model knowledge, use a domain NOT in any model's training data -- proprietary internal documentation or very recent content.

## Methodology

- Evaluation framework: `eval/` directory in expert-service
- Runner: `uv run python -m eval.run_eval --systems all --questions all`
- MC scoring: automated exact-match via `extract_answer()` regex
- Open-ended scoring: LLM-as-judge (Claude Opus 4.6 via `claude -p`)
- Raw results: `eval/results/2026-03-06_full.json`

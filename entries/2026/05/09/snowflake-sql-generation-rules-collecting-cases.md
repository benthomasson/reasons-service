# Snowflake SQL Generation Rules — Collecting Cases

**Date:** 2026-05-09
**Time:** 05:18

## Problem

The Snowflake connector generates SQL from natural language via an LLM (now Sonnet, upgraded from Haiku which couldn't handle the prompt complexity). The LLM produces correct SQL structurally, but misses domain-specific patterns that a human analyst would know — like joining to resolve foreign key UUIDs into human-readable names.

## Example: Manager UUID Not Resolved

When asked "Who is Josh Boyer?", the generated SQL returns:
- `MANAGER_ID`: `77628396-0d75-11e7-b358-28d244ea5a6d`

A human would self-join `RHAI_ROVER_PEOPLE_DETAIL` to resolve that:
```sql
SELECT e.*, m.PREFERRED_NAME AS manager_name
FROM RHAI_ROVER_PEOPLE_DETAIL e
LEFT JOIN RHAI_ROVER_PEOPLE_DETAIL m ON e.MANAGER_ID = m.PERSON_ID
WHERE ...
```

The LLM doesn't know to do this because the schema doesn't document the FK relationship or the convention that UUIDs should be resolved to names.

## Design Direction

Add an extensible rules system to expert-snowflake's SQL generation prompt. Rules are domain-specific hints that accumulate over time as we encounter cases where the LLM generates technically correct but practically unhelpful SQL.

Rules would cover things like:
- FK resolution patterns ("MANAGER_ID refers to PERSON_ID in the same table — always self-join to get the name")
- Column interpretation ("COST_CENTER is a code, join to X for the label")
- Query patterns ("for headcount questions, COUNT DISTINCT on PERSON_ID, not rows")
- Data quality ("TERMINATION_DATE null means active employee")

## Cases to Collect

| # | Question | Issue | Rule Needed |
|---|----------|-------|-------------|
| 1 | Who is Josh Boyer? | MANAGER_ID returned as raw UUID | Self-join RHAI_ROVER_PEOPLE_DETAIL on MANAGER_ID = PERSON_ID |
| | | | |
| | | | |

Add cases to this table as they come up. Once we have 5-10, implement the rules system in expert-snowflake/sql_gen.py.

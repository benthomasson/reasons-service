# Adding personas to reasons-service

**Date:** 2026-10-27
**Time:** 20:31

## Overview

Adding personas to reasons-service as a layer above domains. A persona is a named collection of EEM domains that an agent can search across during chat. Instead of selecting a single domain, users can select a persona and chat with an agent that has access to multiple knowledge bases.

This implements the concept from `beliefs-pi/entries/2026/10/27/personas-as-human-readable-eem-collections.md` — personas compress domain collections into intuitive, human-readable identities. "Ask the infrastructure specialist" is more actionable than "query redhat-expert + awx-expert + aap-expert."

## Design

**Data model:**
- `personas` table: id, name, description, system_prompt (optional), created_at, updated_at
- `persona_domains` join table: persona_id → domains.id

**API:**
- CRUD endpoints under `/api/personas`
- Chat endpoint extended to accept `persona_id` — searches across all linked domains for RAG context

**UI:**
- Personas sit alongside domain selection, not replacing it
- Single-domain chat remains available for focused work
- Persona chat aggregates search results from all member domains

**Key behaviors:**
- Same beliefs can appear in multiple personas (many-to-many)
- Chat RAG searches all persona domains and merges results
- Persona system_prompt overrides the default chat system prompt when set
- Domain-level access control still applies per-domain within a persona

## What this enables

- Human-readable routing: users pick "infrastructure specialist" not a domain list
- Negative knowledge: users intuit what a persona doesn't know from its name
- Trust calibration: users develop reliability intuitions per persona
- Cross-domain answers: questions that span multiple knowledge bases get grounded context from all of them


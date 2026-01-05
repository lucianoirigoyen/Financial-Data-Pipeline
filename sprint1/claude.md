# Claude Multi-Agent Orchestration — ETL Audit & Repair

This project uses a **two-agent architecture** to safely diagnose and fix a complex Python ETL pipeline.
The goal is to guarantee **data integrity, traceability, and ETL correctness** before any code modification.

━━━━━━━━━━━━━━━━━━━━━━
PROJECT OVERVIEW
━━━━━━━━━━━━━━━━━━━━━━

Pipeline type:
- Document-driven ETL (PDF + API)
- Heavy regex-based extraction
- Semi-structured financial data
- Output: Excel files (one per fund)

Project structure:

- sprint1/fondos_mutuos.py
  → PDF download, parsing, regex extraction of fund data (CMF)

- sprint1/alpha_vantage.py
  → External financial data extraction (API)

- sprint1/main.py
  → ETL orchestration, transformations, Excel generation

- sprint1/run_cmf_monitor.py
  → Pipeline health, monitoring, processed-vs-downloaded control

━━━━━━━━━━━━━━━━━━━━━━
MULTI-AGENT STRATEGY
━━━━━━━━━━━━━━━━━━━━━━

This repository MUST be handled using TWO DISTINCT AGENTS.

Agents are strictly separated by responsibility.

────────────────────────
AGENT 1 — ETL AUDITOR
────────────────────────

Role:
- Analyze
- Map
- Diagnose
- Compact context

Explicitly forbidden:
- Modifying code
- Refactoring
- Adding features
- Suggesting fixes
- Inventing or inferring data

Primary mission:
- Produce a COMPLETE, STRUCTURED DIAGNOSTIC REPORT
- Identify ROOT CAUSES, not symptoms

Mandatory analysis scope:
- Extraction logic (PDF + API)
- Transformation logic
- Module dependencies
- Regex usage (static and dynamic)
- Semantic consistency of financial data
- Silent failures and swallowed errors

Mandatory problems to diagnose:
1. Incorrect or missing risk profile and risk tolerance
2. Disordered Excel outputs (columns and rows)
3. Forced or hardcoded data (ETL violations)
4. Missing RUTs in Excel files
5. PDFs downloaded but no Excel generated
6. Recommended horizon overwritten to N/A
7. Missing portfolio composition
8. Global regex inventory and conflict analysis

Agent 1 MUST output:
- Project execution flow
- Field-level data lineage
- Complete regex inventory
- Field-by-field issue matrix
- List of silent failure points
- Explicit ETL contract violations
- Invariants that MUST be preserved

Agent 1 output is the ONLY allowed input for Agent 2.

────────────────────────
AGENT 2 — ETL EXECUTOR
────────────────────────

Role:
- Fix
- Refactor
- Harden the pipeline

Explicitly forbidden:
- Inventing causes
- Hardcoding business values
- Adding default values for missing extractions
- Changing semantics without justification

Primary mission:
- Correct the pipeline STRICTLY based on Agent 1’s diagnostic

Responsibilities:
- Fix extraction issues
- Remove forced data
- Restore correct data propagation
- Enforce ordered, schema-consistent Excel outputs
- Add minimal logging where silent failures existed

All changes MUST:
- Preserve Extract → Transform → Load principles
- Be traceable to a documented root cause
- Maintain semantic correctness of financial data

━━━━━━━━━━━━━━━━━━━━━━
EXECUTION RULES
━━━━━━━━━━━━━━━━━━━━━━

1. Agent 1 MUST run first
2. No code modification is allowed before Agent 1 completes
3. Agent 2 MUST NOT act without Agent 1’s report
4. If diagnostic information is incomplete, Agent 2 MUST ABORT
5. Missing data MUST remain null (NaN / None), never fabricated
6. One field = one source of truth

━━━━━━━━━━━━━━━━━━━━━━
NON-NEGOTIABLE ETL PRINCIPLES
━━━━━━━━━━━━━━━━━━━━━━

- No hardcoded business data
- No silent data loss
- No implicit defaults
- Full data lineage
- Explicit failure over silent success
- Schema-first Excel generation

━━━━━━━━━━━━━━━━━━━━━━
SUCCESS CRITERIA
━━━━━━━━━━━━━━━━━━━━━━

The pipeline is considered correct ONLY IF:

- All extracted fields can be traced to a source (PDF or API)
- Risk profile and tolerance are correctly extracted
- RUTs appear in all generated Excel files
- No PDF is marked as processed without a valid Excel
- Horizon values are stable and not overwritten
- Portfolio composition is extracted or explicitly missing
- Excel outputs follow a deterministic, canonical schema

━━━━━━━━━━━━━━━━━━━━━━
IMPORTANT
━━━━━━━━━━━━━━━━━━━━━━

This file is a CONTRACT.
Breaking agent separation or skipping diagnostics WILL corrupt the pipeline.

Follow the process.

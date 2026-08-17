# PRGI Title Verification Prototype (SIH 2026 — PSS06)

## 1. What PSS06 asks us to build

Problem Statement PSS06 (Press Registrar General of India) asks for a system that
automatically verifies new periodical title submissions against a database of
existing registered titles (PRGI maintains roughly 160,000 of them). The system
must decide whether a proposed title is sufficiently distinct and complies with
title-verification guidelines, including:

- Detecting exact and near-identical titles (spelling variations, small
  modifications), including phonetic similarity (e.g. Soundex/Metaphone).
- Flagging problematic generic prefixes/suffixes (e.g. "The", "India",
  "Samachar", "News") against a configurable list.
- Enforcing guideline rules: disallowed words, titles formed by combining
  existing titles, titles with equivalent meaning in another language, and
  titles that merely add a periodicity word (Daily/Weekly/Monthly) to an
  existing title.
- Producing a similarity percentage and a corresponding verification
  probability (e.g. ~80% similarity should correspond to a verification
  probability of no more than ~20%).
- Explaining a likely rejection to the user, showing the conflicting titles
  and similarity evidence, and allowing edit-and-resubmit.
- Scaling to the full title database and accounting for currently pending
  applications, not just already-registered titles.

## 2. Intended prototype flow

```
PRGI title data
  → preprocessing (normalization, cleaning)
  → candidate retrieval (narrow ~160k titles down to a relevant shortlist)
  → similarity / rule evidence (independent deterministic checks)
  → LLM (interprets the evidence, does not invent it)
  → structured result (decision, probability, violations, similar titles, explanation)
```

Each stage is intentionally decoupled: the evidence-generating stage is plain
deterministic code, and the LLM only ever reasons over evidence it is handed.

## 3. Dataset

The prototype will initially be built on the **PRGI registered-title dataset**
(publicly downloadable, ~82k+ titles at present). This repository does not yet
contain the dataset — it will be placed under `data/raw/` once downloaded. No
assumptions are made yet about its exact schema (columns, encoding, language
fields, etc.); that will be documented here once the raw export has been
inspected.

## 4. Role of the LLM

The LLM layer is a **decision/explanation layer, not a similarity engine**. It
receives a structured evidence bundle (scores and flags already computed by
deterministic code — exact match, fuzzy similarity, phonetic similarity,
prefix/suffix matches, rule violations, etc.) along with the relevant
candidate titles, and returns a strictly structured result (decision,
verification probability, violations, similar titles, explanation). It is not
permitted to invent similarity scores or evidence that wasn't supplied to it.

## Project structure

```
data/raw/        # PRGI CSV exports go here once downloaded (gitignored)
data/processed/  # Cleaned/combined data derived from data/raw (gitignored)
src/             # Application code (not yet implemented)
tests/           # Tests (not yet implemented)
.env.example     # Template for LLM provider API keys
requirements.txt # Python dependencies (added incrementally)
```

## Status

Repository scaffolding only. No preprocessing, retrieval, similarity, LLM
integration, or UI code has been implemented yet. Dataset has not been
downloaded yet.

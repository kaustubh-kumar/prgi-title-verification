# PRGI Title Verification Prototype (SIH 2026 — PSS06)

## 1. What PSS06 asks us to build

Problem Statement PSS06 (Press Registrar General of India) asks for a system that
automatically verifies new periodical title submissions against a database of
existing registered titles (PRGI maintains roughly 82,000+ of them, publicly
listed at prgi.gov.in). The system must decide whether a proposed title is
sufficiently distinct and complies with title-verification guidelines, including:

- Detecting exact and near-identical titles (spelling variations, small
  modifications), including phonetic similarity (Soundex/Double Metaphone).
- Flagging problematic generic prefixes/suffixes (e.g. "The", "India",
  "Samachar", "News") against a configurable list.
- Enforcing guideline rules: disallowed words, titles formed by combining
  existing titles, and titles that merely add a periodicity word
  (Daily/Weekly/Monthly) to an existing title.
- Producing a similarity percentage and a corresponding verification
  probability (e.g. ~80% similarity should correspond to a verification
  probability of no more than ~20%).
- Explaining a likely rejection, showing the conflicting titles and evidence.

## 2. Quickstart

```bash
pip install -r requirements.txt
python3 -m unittest discover -s tests -v   # sanity check - should all pass, no API key needed
```

Try each layer directly from the command line (all operate on the already-processed
corpus at `data/processed/prgi_titles.csv`, which is committed to this repo):

```bash
python3 -m src.matching.retrieval "AAJ SAMAJ"          # lexical candidates only
python3 -m src.matching.phonetic "AAJ SAMAJ"            # + phonetic evidence
python3 -m src.rules.rules "AAJ SAMAJ DAILY"             # + deterministic rule evidence
python3 -m src.evidence.builder "AAJ SAMAJ DAILY"        # full evidence bundle (JSON)
```

The Gemini decision/explanation layer additionally needs an API key:

```bash
cp .env.example .env        # then fill in GEMINI_API_KEY (get one at aistudio.google.com/apikey)
export $(grep -v '^#' .env | xargs)
python3 -m src.llm.provider "AAJ SAMAJ DAILY"
```

Nothing else in the repo requires an API key - retrieval, phonetic evidence, rule
evidence, the evidence bundle, and the deterministic scoring layer
(`src/llm/scoring.py`, which computes `verification_probability` - the LLM never
does) all run offline against the committed corpus.

## 3. Pipeline

```
PRGI title data (data/raw/, data/processed/ - already collected & committed)
  → preprocessing (src/data/preprocess.py)
  → candidate retrieval (src/matching/retrieval.py - RapidFuzz)
  → phonetic evidence (src/matching/phonetic.py - Soundex/Double Metaphone)
  → rule evidence (src/rules/rules.py - periodicity/generic/disallowed/combination)
  → evidence bundle (src/evidence/builder.py - combines the above, JSON-serializable)
  → deterministic scoring (src/llm/scoring.py - owns verification_probability)
  → LLM (src/llm/ - Gemini interprets evidence, explains, decides; never invents
     evidence or the probability)
  → structured result (decision, verification_probability, violations,
     similar_titles, explanation)
```

Each stage is decoupled and independently runnable/testable (see Quickstart above).
The LLM only ever reasons over evidence already computed by earlier stages.

## 4. Dataset

`data/raw/` contains 24 real CSV exports collected from the PRGI public listing
(prgi.gov.in), sampled across the full ~82,284-record range (see
`data/MANIFEST.csv` for exactly which pages/ranges each file covers) - 11,784
raw records total. `data/processed/prgi_titles.csv` is the deduplicated,
normalized output of `src/data/preprocess.py` (11,777 records) and is what every
other module actually queries.

To regenerate `data/processed/prgi_titles.csv` from the raw files yourself:

```bash
python3 -m src.data.preprocess
```

## 5. Role of the LLM

The LLM layer (`src/llm/`) is a **decision/explanation layer, not a similarity
engine and not a scoring engine**. It receives the full evidence bundle (lexical,
phonetic, and rule evidence already computed deterministically) and returns a
structured decision + explanation. It is constrained by:
- Structured output (Gemini's `response_json_schema`), not just prompt wording.
- A system prompt (`src/llm/prompt.py`) that establishes the evidence hierarchy,
  flags which rule lists are prototype/placeholder data (not official PRGI rules),
  and forbids inventing evidence, candidates, or scores.
- `verification_probability` is deliberately **excluded** from what the LLM is
  even allowed to return - it's computed separately by `src/llm/scoring.py` and
  merged in afterward. The LLM cannot influence it.

## 6. Project structure

```
data/raw/         # 24 raw PRGI CSV exports (committed)
data/processed/   # Preprocessed corpus, prgi_titles.csv (committed)
data/MANIFEST.csv # Provenance of every raw file (page/SN range)
src/data/         # Preprocessing pipeline
src/matching/     # Lexical retrieval (RapidFuzz) + phonetic evidence
src/rules/        # Deterministic PRGI rule evidence + config.json word lists
src/evidence/     # Combines the above into one evidence bundle
src/llm/          # Gemini provider, prompt, schema, deterministic scoring
tests/            # Mocked-LLM and scoring tests (no API key required)
.env.example      # Template for GEMINI_API_KEY
requirements.txt  # Python dependencies
```

## 7. Status

Working end-to-end: preprocessing, retrieval, phonetic evidence, rule evidence,
evidence bundling, deterministic scoring, and the Gemini decision/explanation
layer are all implemented and tested. **Not yet built**: UI, API, embeddings/
semantic similarity, multilingual/cross-script matching.

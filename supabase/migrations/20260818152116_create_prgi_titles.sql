-- ============================================================================
-- PSS06 prototype: PRGI title corpus storage + candidate retrieval
-- ============================================================================
--
-- SCOPE: this migration replaces ONLY the corpus storage/retrieval portion of
-- the pipeline (previously data/processed/prgi_titles.csv, read by
-- src/matching/retrieval.py). It does not implement, and must never
-- implement, RapidFuzz character/token similarity, phonetic matching, rule
-- evaluation, scoring, or the LLM call - all of that stays in Python,
-- unchanged, in src/matching/, src/rules/, src/llm/.
--
-- Postgres's job here is CANDIDATE GENERATION ONLY: given a submitted title
-- (already normalized and tokenized by Python, exactly as
-- src/data/preprocess.normalize_title()/tokenize_title() already do it),
-- cheaply narrow ~82,000 rows down to a small candidate set. Python then
-- computes the authoritative RapidFuzz/phonetic/rule evidence over that
-- small set, exactly as it does today over the in-memory CSV. Any similarity
-- number produced by Postgres in this migration (trgm_similarity, below) is
-- a ranking/blocking hint only, never treated as final evidence.
--
-- Schema was written by inspecting the actual current processed dataset
-- (data/processed/prgi_titles.csv, 11,777 rows) rather than assumed:
--   - title, normalized_title, title_tokens, and registration_number had 0
--     missing values across all 11,777 rows, hence NOT NULL below.
--   - language (7 rows), periodicity (2 rows), and publication_district
--     (1 row) were genuinely blank in the source PRGI data for some
--     records - hence NULLABLE below, preserving those gaps as SQL NULL
--     rather than inventing a placeholder value that was never in the
--     source. publication_state had 0 missing values, hence NOT NULL.
--   - registration_number was unique across all 11,777 processed rows (0
--     duplicates, 0 empty) - see the constraint note below for exactly how
--     confident that makes us for the full ~82,284-record target.
--   - Registration Date in the source CSVs is DD-MM-YYYY text (e.g.
--     "10-04-1982"), not ISO - the eventual data-import step (not part of
--     this migration) will need to parse that into the `date` column below.
-- ============================================================================

-- pg_trgm gives trigram (3-character n-gram) similarity for text, plus the
-- `%` operator and `similarity()` function used below. It's the standard,
-- lightweight PostgreSQL-native way to do fuzzy "find similar strings"
-- candidate generation without standing up any separate search
-- infrastructure (no Elasticsearch, no vector DB) - appropriate for ~82k
-- short title strings.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================================
-- Table: prgi_titles
-- ============================================================================
-- One row per REGISTRATION RECORD, not per unique title. PRGI legitimately
-- issues multiple registration numbers for the same title text (verified in
-- this dataset: e.g. "AAJ SAMAJ" has 16 separate registration records, one
-- per publisher/district). normalized_title is intentionally NOT unique and
-- NOT the primary key - see the "AAJ SAMAJ" case, which must remain 16
-- independently retrievable rows.
CREATE TABLE IF NOT EXISTS prgi_titles (
    id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Core title fields. normalized_title is what candidate retrieval and
    -- exact-match checks actually query against; title is preserved
    -- verbatim for display/evidence (original casing/punctuation).
    title                   text NOT NULL,
    normalized_title        text NOT NULL,

    -- Token array, produced by Python's tokenize_title() (Unicode word
    -- tokenization - works for Latin and Indian scripts alike, no
    -- transliteration, no stopword removal, exactly as today). Stored as a
    -- native Postgres array (not jsonb) specifically so a GIN index can
    -- accelerate token-overlap ("&&") queries - see the index notes below.
    title_tokens            text[] NOT NULL DEFAULT '{}',

    -- registration_number is PRGI's own stable identifier for a
    -- registration record (this is what src/data/preprocess.py already
    -- treats as record identity, as opposed to SN., which is documented
    -- there as source/display ordering only, never identity).
    registration_number     text NOT NULL,

    -- Stored as `date`, not text - the source CSVs use DD-MM-YYYY text
    -- ("10-04-1982"); a separate import step (not part of this migration)
    -- must parse that format. Nullable because we have not yet verified
    -- registration_date is populated for all ~82,284 target records, only
    -- for the current 11,777-row sample (where it always was).
    registration_date       date,

    -- Kept as free text, matching the source data exactly (e.g. "Hindi",
    -- "HINDI", "English, Hindi" all occur as literal values in this
    -- corpus - see prior inspection). Python's normalize_language()/
    -- normalize_periodicity() already handle casing/whitespace
    -- normalization and multi-value splitting at evidence-computation
    -- time, applied to whatever this column returns - there is
    -- deliberately no separate normalized_language/normalized_periodicity
    -- column here, to avoid storing a second copy of logic that already
    -- lives in Python and would need to be kept in sync.
    --
    -- NULLABLE (not NOT NULL): validated against the actual 11,777-row
    -- processed sample and found genuinely blank in the source PRGI data
    -- for some records (7 rows with blank Language, e.g. registration
    -- number 4380 "KOUMODOKI"; 2 rows with blank Periodicity, e.g.
    -- registration number 37670 "VIDYARTHI SAHAYAK SAMITI SAMACHAR").
    -- These are preserved as SQL NULL, not a placeholder string such as
    -- 'UNKNOWN'/'N/A' - a placeholder would be fabricated data that was
    -- never in the source, and would also silently corrupt any future
    -- equality/grouping query on this column (e.g. "titles with unknown
    -- language" would wrongly conflate "genuinely unknown" with "PRGI
    -- listed it as literally the string N/A", which does not occur in
    -- this data).
    language                text,
    periodicity              text,

    -- NOT NULL: validated against the same sample with 0 missing values
    -- for Publication State specifically (unlike District, below).
    publication_state       text NOT NULL,

    -- NULLABLE: 1 row in the validated sample has a blank Publication
    -- District (registration number UPHIN/2000/01070, "TARAI ATANK") -
    -- same reasoning as language/periodicity above: preserved as NULL,
    -- not a fabricated placeholder.
    publication_district    text,

    -- Everything else worth preserving from the source PRGI export
    -- (Publisher, Owner, the original SN. display-ordering value, which
    -- source CSV batch it came from) without creating a dedicated column
    -- per field. None of the current Python pipeline reads this column -
    -- it exists for provenance/future use. Suggested keys, populated by
    -- the eventual import step (not part of this migration):
    --   {"publisher": ..., "owner": ..., "sn": ..., "source_file": ...}
    metadata                jsonb NOT NULL DEFAULT '{}'::jsonb,

    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),

    -- registration_number was unique across all 11,777 rows actually
    -- inspected (0 duplicates, 0 blanks) and PRGI registration numbers are
    -- structurally a state/language/year/sequence identifier
    -- (e.g. "HARHIN/2022/83438"), which is why this is enforced as a real
    -- constraint rather than left as an assumption. This has only been
    -- verified against ~14% of the eventual ~82,284-record corpus (the
    -- current sample), not the full dataset - flagged again in the
    -- covering-note at the end of this file. If the full import ever hits
    -- a genuine duplicate, that is signal the source data needs
    -- investigation, not a reason to silently drop this constraint.
    CONSTRAINT prgi_titles_registration_number_key UNIQUE (registration_number)

    -- Deliberately NOT adding any uniqueness constraint on
    -- title/normalized_title, or on any (title, language, state) tuple -
    -- the source data does not support that (see the "AAJ SAMAJ" x16
    -- case), and the task explicitly says not to invent one.
);

COMMENT ON TABLE prgi_titles IS
    'One row per PRGI title registration record. normalized_title is deliberately not unique - multiple registrations can legitimately share a title. Candidate retrieval only; RapidFuzz/phonetic/rule scoring stays in Python.';
COMMENT ON COLUMN prgi_titles.title_tokens IS
    'Output of Python tokenize_title() - Unicode word tokens, no stopword removal, no transliteration. Used for GIN-indexed token-overlap candidate blocking.';
COMMENT ON COLUMN prgi_titles.metadata IS
    'Preserved source fields not otherwise modeled as columns (publisher, owner, original SN., source CSV file). Not read by the current retrieval/scoring pipeline.';

-- ----------------------------------------------------------------------------
-- updated_at maintenance
-- ----------------------------------------------------------------------------
-- Standard trigger so updated_at reflects the last modification without
-- every caller having to remember to set it manually.
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_prgi_titles_updated_at ON prgi_titles;
CREATE TRIGGER trg_prgi_titles_updated_at
    BEFORE UPDATE ON prgi_titles
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- ============================================================================
-- Indexes
-- ============================================================================

-- 1. Trigram GIN index on normalized_title - the main candidate-retrieval
--    index. Enables the `%` similarity operator and similarity()/word_similarity()
--    functions used in search_prgi_titles() below to be index-accelerated
--    instead of scanning all ~82k rows per request.
--
--    GIN (not GiST) was chosen deliberately: GIN builds slower and is
--    slightly larger, but this table is read-heavy/write-light (a title
--    corpus, not a live-updating feed), and GIN gives faster lookups for
--    the `%` threshold-filter query pattern used below. The tradeoff is
--    that GIN does not accelerate true index-only k-nearest-neighbor
--    ordering via the `<->` distance operator the way GiST does - so
--    search_prgi_titles() below uses `%` to do the actual index-accelerated
--    filtering, and only sorts the resulting (already small) row set by
--    similarity() afterward, rather than relying on `<->` for an
--    index-accelerated ORDER BY. If write volume or KNN-style querying
--    patterns change later, gist_trgm_ops is the natural alternative.
CREATE INDEX IF NOT EXISTS idx_prgi_titles_normalized_title_trgm
    ON prgi_titles
    USING gin (normalized_title gin_trgm_ops);

-- 2. Plain btree index on normalized_title - a separate, cheap index for the
--    exact_normalized_match check (`WHERE normalized_title = $1`), which is
--    a distinct, very common query pattern that a trigram GIN index does
--    not serve efficiently on its own.
CREATE INDEX IF NOT EXISTS idx_prgi_titles_normalized_title_exact
    ON prgi_titles (normalized_title);

-- 3. GIN index on title_tokens (native array ops, not trigram) - supports
--    the `&&` (overlap) operator, i.e. "does this row share at least one
--    token with the submitted title's token array". This is a second,
--    complementary blocking strategy alongside trigram similarity, added
--    specifically because of a real failure mode found earlier in this
--    project: fuzzy/trigram-style ranking can crowd a short but genuinely
--    relevant single-token title (e.g. "AAJ") out of a top-k window when
--    the submitted title is longer (e.g. "AAJ TAJA SAMACHAR") - this is the
--    same reason src/rules/rules.py's combination detector does an exact
--    corpus-wide token lookup rather than relying on the fuzzy candidate
--    list alone. search_prgi_titles() below unions trigram candidates with
--    token-overlap candidates so that failure mode does not reappear at the
--    database layer.
CREATE INDEX IF NOT EXISTS idx_prgi_titles_title_tokens_gin
    ON prgi_titles
    USING gin (title_tokens);

-- 4. Filtering indexes (task requirement 7) - plain btree, one per field
--    that is a plausible future filter dimension, not applied to every
--    column. Not used by the current Python pipeline yet (which does not
--    filter by these), so no functional/expression (e.g. lower()) variants
--    are added pre-emptively - add those if/when case-insensitive filtering
--    on these fields is actually needed, rather than building it now.
CREATE INDEX IF NOT EXISTS idx_prgi_titles_language
    ON prgi_titles (language);
CREATE INDEX IF NOT EXISTS idx_prgi_titles_publication_state
    ON prgi_titles (publication_state);
CREATE INDEX IF NOT EXISTS idx_prgi_titles_publication_district
    ON prgi_titles (publication_district);
CREATE INDEX IF NOT EXISTS idx_prgi_titles_periodicity
    ON prgi_titles (periodicity);

-- ============================================================================
-- Candidate retrieval function
-- ============================================================================
-- Conceptual usage (matches the task's own example call shape):
--   SELECT * FROM search_prgi_titles('aaj samaj daily', 50);
--
-- IMPORTANT: p_normalized_title MUST already be normalized by Python's
-- normalize_title() (NFKC, casefolded, whitespace/punctuation normalized)
-- before being passed in - this function does only a cheap defensive
-- lower(trim(...)), which is not a substitute for that. Normalization stays
-- single-sourced in Python (src/data/preprocess.py), per the task's own
-- instruction not to re-implement application logic in SQL.
--
-- p_title_tokens is optional: pass Python's tokenize_title() output for
-- exact token-overlap blocking (recommended - avoids re-deriving tokens in
-- SQL); if omitted, a simple whitespace split of the (already
-- punctuation-normalized) input is used as an approximation - adequate for
-- blocking purposes, since Python re-tokenizes candidates authoritatively
-- afterward regardless.
--
-- Returns the UNION of trigram-similar rows and token-overlapping rows,
-- deduplicated by id, capped at p_limit, best-effort ordered by trigram
-- similarity. That ordering is a ranking HINT for readability only - it is
-- not RapidFuzz char/token similarity and must not be treated as such by
-- any caller. Python computes the real evidence over whatever rows come
-- back here, exactly as it does today over the CSV-loaded candidate list.
CREATE OR REPLACE FUNCTION search_prgi_titles(
    p_normalized_title  text,
    p_limit             integer DEFAULT 50,
    p_title_tokens       text[] DEFAULT NULL
)
RETURNS TABLE (
    id                      bigint,
    title                   text,
    normalized_title        text,
    title_tokens            text[],
    registration_number     text,
    registration_date       date,
    language                text,
    periodicity             text,
    publication_state       text,
    publication_district    text,
    metadata                jsonb,
    trgm_similarity         real
)
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
    WITH normalized_input AS (
        SELECT lower(trim(p_normalized_title)) AS q
    ),
    input_tokens AS (
        SELECT COALESCE(
            p_title_tokens,
            regexp_split_to_array(trim((SELECT q FROM normalized_input)), '\s+')
        ) AS tokens
    ),
    trigram_candidates AS (
        SELECT
            t.*,
            similarity(t.normalized_title, (SELECT q FROM normalized_input)) AS trgm_similarity
        FROM prgi_titles t
        WHERE t.normalized_title % (SELECT q FROM normalized_input)
    ),
    token_candidates AS (
        SELECT
            t.*,
            similarity(t.normalized_title, (SELECT q FROM normalized_input)) AS trgm_similarity
        FROM prgi_titles t
        WHERE t.title_tokens && (SELECT tokens FROM input_tokens)
    ),
    combined AS (
        SELECT * FROM trigram_candidates
        UNION
        SELECT * FROM token_candidates
    )
    SELECT
        combined.id,
        combined.title,
        combined.normalized_title,
        combined.title_tokens,
        combined.registration_number,
        combined.registration_date,
        combined.language,
        combined.periodicity,
        combined.publication_state,
        combined.publication_district,
        combined.metadata,
        combined.trgm_similarity
    FROM combined
    ORDER BY combined.trgm_similarity DESC NULLS LAST
    LIMIT p_limit;
$$;

COMMENT ON FUNCTION search_prgi_titles IS
    'Candidate generation ONLY (trigram + token-overlap blocking via indexes above). trgm_similarity is a ranking hint, not final evidence - RapidFuzz char/token similarity, phonetic matching, and rule evaluation happen in Python over this function''s output, exactly as they do today over the CSV-loaded candidate list.';

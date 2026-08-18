"""Database-backed corpus access, adapting the existing CSV-shaped corpus
contract to Postgres without touching retrieval.py, phonetic.py, rules.py,
or evidence/builder.py.

Two distinct queries exist here because they serve two distinct needs
that must NOT be conflated (this is the exact requirement flagged when
moving to a database: don't recreate the earlier combination-detection
bug where a real component title got crowded out of a fuzzy top-k):

1. fetch_candidates() - calls search_prgi_titles() (the migration's
   trigram + token-overlap blocking function) to get a bounded candidate
   set for fuzzy/phonetic ranking. This becomes the `corpus` argument to
   src.matching.retrieval.search_title() / src.evidence.builder
   .build_evidence_bundle(), completely unchanged - Postgres does
   blocking, RapidFuzz (in Python, untouched) does the actual ranking
   over whatever this returns.

2. fetch_light_corpus_for_index() - a separate, lightweight query
   (normalized_title/title/registration_number only) covering every row
   in the table, used only to build the title_index that
   src.rules.rules.detect_combination() needs for its corpus-wide exact
   lookup. This is intentionally NOT limited to the fuzzy candidate set -
   combination detection must be able to find a short single-token
   component title (e.g. "AAJ") even when it would never appear in a
   fuzzy top-k for a longer query, exactly as it already worked against
   the in-memory CSV corpus. At the current ~11.8k-row scale this full
   fetch is cheap; if/when the corpus grows to the full ~82k it should be
   revisited (e.g. batched exact-match queries for just the submitted
   title's own candidate spans), but the *contract* - a dict-like
   structure covering the whole corpus, independent of any top-k - must
   be preserved either way.

Both functions return data shaped exactly like the rows
src.matching.retrieval.load_corpus() used to return from the CSV, so
every downstream function is unmodified.
"""

import json

from src.rules.rules import build_title_index

# Candidate blocking set size fetched from Postgres, before Python's own
# RapidFuzz re-ranks down to the caller's requested top_k. Larger than
# top_k on purpose - this is the "give fuzzy/phonetic analysis enough to
# work with" pool, not the final answer.
DEFAULT_BLOCKING_LIMIT = 200

# retrieval.py's CANDIDATE_FIELDS, i.e. the exact keys every downstream
# function (retrieval/phonetic/rules/evidence builder) expects on a
# candidate row. Kept here only as a mapping target, not re-implementing
# any of their logic.
_NULL_SAFE_TEXT_FIELDS = ("language", "periodicity", "publication_state", "publication_district")


def _row_to_candidate(row):
    """Map one search_prgi_titles() row to the CSV-row shape retrieval.py
    and friends expect. NULL columns become "" (not None) specifically
    because that matches the CSV-era contract exactly - the original CSV
    corpus never had real None values, only empty strings, and downstream
    code (e.g. rules.py calling normalize_title() on these fields) assumes
    a string. Coercing here is the one adapter-layer detail required to
    connect the database without changing that downstream code.

    title_tokens is re-serialized to a JSON string on purpose:
    src.matching.retrieval.search_title() does
    `json.loads(row["title_tokens"])`, matching the CSV column's format
    exactly (src/data/preprocess.py wrote it with json.dumps()). Postgres
    hands this back as a native list (title_tokens is a real text[]
    column), so it has to be re-encoded here to satisfy that exact
    contract without touching retrieval.py itself - discovered by actually
    running the pipeline against real DB rows, not assumed upfront.
    """
    return {
        "Title": row["title"],
        "Registration Number": row["registration_number"],
        "Language": row["language"] or "",
        "Periodicity": row["periodicity"] or "",
        "Publication State": row["publication_state"] or "",
        "Publication District": row["publication_district"] or "",
        "normalized_title": row["normalized_title"],
        "title_tokens": json.dumps(row["title_tokens"] or []),
    }


def fetch_candidates(conn, normalized_title, tokens=None, limit=DEFAULT_BLOCKING_LIMIT):
    """Fetch a bounded candidate set via the migration's search_prgi_titles()
    function. normalized_title and tokens must already be produced by
    src.data.preprocess.normalize_title()/tokenize_title() - this function
    does not normalize or tokenize anything itself.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM search_prgi_titles(%s, %s, %s)",
            (normalized_title, limit, tokens),
        )
        rows = cur.fetchall()
    return [_row_to_candidate(r) for r in rows]


def fetch_light_title_index(conn):
    """Build the same title_index shape src.rules.rules.build_title_index()
    has always produced, sourced from a lightweight full-table query
    instead of the in-memory CSV corpus. Reuses build_title_index()
    unchanged - only the corpus feeding it is different.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT title, registration_number, normalized_title FROM prgi_titles")
        rows = cur.fetchall()
    light_corpus = [
        {
            "Title": r["title"],
            "Registration Number": r["registration_number"],
            "normalized_title": r["normalized_title"],
        }
        for r in rows
    ]
    return build_title_index(light_corpus)


def count_rows(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM prgi_titles")
        return cur.fetchone()["n"]

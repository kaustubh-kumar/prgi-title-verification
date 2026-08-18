"""Candidate retrieval and lexical evidence for submitted PRGI titles.

Brute-force search over the processed PRGI corpus using RapidFuzz. This
module only retrieves candidates and reports raw, separate similarity
evidence per candidate - it does not rank algorithms against each other,
combine scores into one number, or make an accept/reject decision. Those
are later components.
"""

import argparse
import csv
import json
import os
import sys

from rapidfuzz import fuzz, process

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from src.data.preprocess import normalize_title, tokenize_title  # noqa: E402

DEFAULT_CORPUS_PATH = "data/processed/prgi_titles.csv"
DEFAULT_TOP_K = 10

CANDIDATE_FIELDS = [
    "Title",
    "Registration Number",
    "Language",
    "Periodicity",
    "Publication State",
    "Publication District",
]


def load_corpus(corpus_path=DEFAULT_CORPUS_PATH):
    """Load the processed corpus produced by src/data/preprocess.py."""
    with open(corpus_path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def search_title(submitted_title, corpus, top_k=DEFAULT_TOP_K):
    """Retrieve the top_k corpus records most similar to submitted_title.

    Uses the exact same normalize_title/tokenize_title functions as the
    preprocessing pipeline, so submitted titles are compared on equal
    footing with corpus records. Candidates are selected and ordered
    using RapidFuzz's token_sort_ratio.

    token_sort_ratio was chosen over WRatio after testing: WRatio's
    partial-match component gives short generic titles (e.g. "AAJ") the
    same near-perfect score as the true longer match (e.g. "AAJ SAMAJ")
    when the query is that longer match plus an extra word, since both
    look like a full substring/subset match to it. That let the correct
    candidate get crowded out of the top-k by short unrelated titles -
    exactly the "existing title plus a periodicity word" gaming pattern
    this system needs to surface, not bury. token_sort_ratio does not
    have that blind spot. The ranking scorer's value is not itself
    returned as evidence; it is the same measure reported separately as
    token_similarity below.

    Duplicate corpus rows that share a Title but have different
    Registration Numbers are preserved as distinct candidates, since
    ranking operates per corpus row, not per unique title string.
    """
    submitted_normalized = normalize_title(submitted_title)
    submitted_tokens = set(tokenize_title(submitted_normalized))

    choices = [row["normalized_title"] for row in corpus]
    matches = process.extract(
        submitted_normalized,
        choices,
        scorer=fuzz.token_sort_ratio,
        limit=top_k,
    )

    candidates = []
    for _, _, idx in matches:
        row = corpus[idx]
        candidate_normalized = row["normalized_title"]
        candidate_tokens = set(json.loads(row["title_tokens"]))

        evidence = {field: row[field] for field in CANDIDATE_FIELDS}
        evidence["normalized_title"] = candidate_normalized
        evidence["char_similarity"] = round(fuzz.ratio(submitted_normalized, candidate_normalized), 2)
        evidence["token_similarity"] = round(fuzz.token_sort_ratio(submitted_normalized, candidate_normalized), 2)
        evidence["exact_normalized_match"] = submitted_normalized == candidate_normalized
        evidence["shared_tokens"] = sorted(submitted_tokens & candidate_tokens)
        evidence["submitted_only_tokens"] = sorted(submitted_tokens - candidate_tokens)
        evidence["candidate_only_tokens"] = sorted(candidate_tokens - submitted_tokens)
        candidates.append(evidence)

    return {
        "submitted_title": submitted_title,
        "submitted_normalized_title": submitted_normalized,
        "submitted_tokens": sorted(submitted_tokens),
        "candidates": candidates,
    }


def print_result(result):
    print(f"Submitted title: {result['submitted_title']!r}")
    print(f"Normalized:      {result['submitted_normalized_title']!r}")
    print(f"Tokens:          {result['submitted_tokens']}")
    print(f"\nTop {len(result['candidates'])} candidates:\n")
    for i, c in enumerate(result["candidates"], 1):
        print(f"  [{i}] {c['Title']!r}  (Reg No: {c['Registration Number']})")
        print(f"      normalized_title: {c['normalized_title']!r}")
        print(
            f"      Language: {c['Language']} | Periodicity: {c['Periodicity']} | "
            f"State: {c['Publication State']} | District: {c['Publication District']}"
        )
        print(
            f"      char_similarity: {c['char_similarity']}  "
            f"token_similarity: {c['token_similarity']}  "
            f"exact_normalized_match: {c['exact_normalized_match']}"
        )
        print(f"      shared_tokens: {c['shared_tokens']}")
        print(f"      submitted_only_tokens: {c['submitted_only_tokens']}")
        print(f"      candidate_only_tokens: {c['candidate_only_tokens']}")
        print()


def main():
    parser = argparse.ArgumentParser(description="Search the processed PRGI corpus for similar titles.")
    parser.add_argument("title", help="Submitted title to check.")
    parser.add_argument("--corpus", default=DEFAULT_CORPUS_PATH, help="Path to the processed corpus CSV.")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help="Number of candidates to retrieve.")
    args = parser.parse_args()

    corpus = load_corpus(args.corpus)
    result = search_title(args.title, corpus, top_k=args.top_k)
    print_result(result)


if __name__ == "__main__":
    main()

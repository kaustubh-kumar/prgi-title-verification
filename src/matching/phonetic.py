"""Phonetic evidence layer for submitted PRGI titles.

Adds token-level phonetic similarity evidence (Soundex, Double Metaphone)
on top of the existing lexical retrieval evidence from
src/matching/retrieval.py, without altering any of the lexical fields
already computed there. This module never asserts an accept/reject
decision or a single combined final score - phonetic evidence is
reported as its own separate signal, and a phonetic match is never
reported as if it were an exact textual match.
"""

import argparse
import os
import sys

import jellyfish
from metaphone import doublemetaphone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from src.data.preprocess import tokenize_title  # noqa: E402
from src.matching.retrieval import (  # noqa: E402
    DEFAULT_CORPUS_PATH,
    DEFAULT_TOP_K,
    load_corpus,
    print_result as print_lexical_result,
    search_title,
)


def soundex_code(token):
    return jellyfish.soundex(token) if token else ""


def double_metaphone_codes(token):
    """Return (primary, secondary) Double Metaphone codes for a token.

    Either element may be an empty string if the algorithm has no code
    (short/purely-vowel tokens, etc.). The underlying metaphone package
    occasionally returns codes with trailing whitespace; that is
    stripped here so equality comparisons behave correctly.
    """
    if not token:
        return ("", "")
    primary, secondary = doublemetaphone(token)
    return (primary.strip(), secondary.strip())


def token_phonetic_codes(token):
    primary, secondary = double_metaphone_codes(token)
    return {
        "token": token,
        "soundex": soundex_code(token),
        "double_metaphone_primary": primary,
        "double_metaphone_secondary": secondary,
    }


def phonetic_algorithms_matched(codes_a, codes_b):
    """Return which phonetic algorithms consider two tokens' codes equivalent.

    Soundex: codes equal and non-empty.
    Double Metaphone: any of (primary, secondary) from one token equals
    any of (primary, secondary) from the other, both non-empty - this is
    the standard way to compare Double Metaphone codes, since a token
    can have two valid pronunciations.
    """
    matched = []
    if codes_a["soundex"] and codes_a["soundex"] == codes_b["soundex"]:
        matched.append("soundex")

    dm_a = {c for c in (codes_a["double_metaphone_primary"], codes_a["double_metaphone_secondary"]) if c}
    dm_b = {c for c in (codes_b["double_metaphone_primary"], codes_b["double_metaphone_secondary"]) if c}
    if dm_a & dm_b:
        matched.append("double_metaphone")

    return matched


def compute_phonetic_evidence(submitted_tokens, candidate_tokens):
    """Compute token-level phonetic evidence between two token lists.

    Matching is greedy one-to-one: each candidate token can satisfy at
    most one submitted token, so the resulting score behaves like a
    Dice/token-overlap coefficient but over phonetic equivalence rather
    than exact text equality. This intentionally never treats a
    phonetic-only match as an exact textual match: each matched pair is
    tagged with also_exact_text_match, and phonetic matching happens
    independently of (and does not read) the lexical shared_tokens
    already computed by retrieval.search_title.
    """
    submitted_tokens = list(submitted_tokens)
    candidate_tokens = list(candidate_tokens)

    submitted_codes = {t: token_phonetic_codes(t) for t in set(submitted_tokens)}
    candidate_codes = {t: token_phonetic_codes(t) for t in set(candidate_tokens)}

    remaining_candidates = list(candidate_tokens)
    matches = []

    for s_tok in submitted_tokens:
        best = None
        for c_tok in remaining_candidates:
            algos = phonetic_algorithms_matched(submitted_codes[s_tok], candidate_codes[c_tok])
            if algos and (best is None or len(algos) > len(best["algorithms_matched"])):
                best = {
                    "submitted_token": s_tok,
                    "candidate_token": c_tok,
                    "algorithms_matched": algos,
                    "also_exact_text_match": s_tok == c_tok,
                }
        if best is not None:
            matches.append(best)
            remaining_candidates.remove(best["candidate_token"])

    denom = len(submitted_tokens) + len(candidate_tokens)
    score = round(200.0 * len(matches) / denom, 2) if denom else 0.0

    return {
        "score": score,
        "matching_tokens": matches,
        "submitted_token_codes": list(submitted_codes.values()),
        "candidate_token_codes": list(candidate_codes.values()),
    }


def search_title_with_phonetics(submitted_title, corpus, top_k=DEFAULT_TOP_K):
    """Run lexical retrieval, then attach phonetic evidence to each candidate.

    All existing lexical fields (char_similarity, token_similarity,
    exact_normalized_match, shared_tokens, submitted_only_tokens,
    candidate_only_tokens) are left exactly as produced by
    retrieval.search_title. A new "phonetic" key is added per candidate.
    """
    result = search_title(submitted_title, corpus, top_k=top_k)
    submitted_tokens = result["submitted_tokens"]

    for candidate in result["candidates"]:
        candidate_tokens = tokenize_title(candidate["normalized_title"])
        candidate["phonetic"] = compute_phonetic_evidence(submitted_tokens, candidate_tokens)

    return result


def print_result(result):
    print_lexical_result(result)
    print("Phonetic evidence per candidate:\n")
    for i, c in enumerate(result["candidates"], 1):
        p = c["phonetic"]
        print(f"  [{i}] {c['Title']!r}  phonetic score: {p['score']}")
        if p["matching_tokens"]:
            for m in p["matching_tokens"]:
                exact_note = " (also exact text match)" if m["also_exact_text_match"] else ""
                print(
                    f"      {m['submitted_token']!r} ~ {m['candidate_token']!r} "
                    f"via {m['algorithms_matched']}{exact_note}"
                )
        else:
            print("      (no phonetically matching tokens)")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Search the processed PRGI corpus and report lexical + phonetic evidence."
    )
    parser.add_argument("title", help="Submitted title to check.")
    parser.add_argument("--corpus", default=DEFAULT_CORPUS_PATH, help="Path to the processed corpus CSV.")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help="Number of candidates to retrieve.")
    args = parser.parse_args()

    corpus = load_corpus(args.corpus)
    result = search_title_with_phonetics(args.title, corpus, top_k=args.top_k)
    print_result(result)


if __name__ == "__main__":
    main()

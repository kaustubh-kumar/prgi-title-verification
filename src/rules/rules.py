"""Deterministic PRGI rule/evidence layer.

Inspects a submitted title against retrieved candidate records and
returns explicit, structured evidence per rule category: periodicity
modification, generic prefix/suffix components, disallowed words,
title combination, and token-level structure. This module never
computes a combined score, weighs evidence against other evidence, or
makes an ACCEPT/REJECT decision - it only reports evidence for a later
scoring/LLM layer to interpret. It also never treats phonetic evidence
as authoritative on its own (see src/matching/phonetic.py) - this layer
does not consume phonetic scores at all, only lexical/token evidence.

All word lists (periodicity vocabulary, generic components, disallowed
words) live in src/rules/config.json, not in this code, so they can be
edited/replaced without touching logic. Several are explicitly marked
PROTOTYPE in that file because the real PRGI guideline data was not
available in this repository - see the "status" field on each list.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from src.data.preprocess import normalize_title, tokenize_title  # noqa: E402
from src.matching.phonetic import print_result as print_phonetic_result  # noqa: E402
from src.matching.phonetic import search_title_with_phonetics  # noqa: E402
from src.matching.retrieval import DEFAULT_CORPUS_PATH, DEFAULT_TOP_K, load_corpus  # noqa: E402

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def load_config(config_path=CONFIG_PATH):
    with open(config_path, encoding="utf-8") as fh:
        return json.load(fh)


def _find_subsequence(haystack, needle):
    """Return [start, end) if needle appears as a contiguous run in haystack, else None."""
    n = len(needle)
    if n == 0 or n > len(haystack):
        return None
    for i in range(len(haystack) - n + 1):
        if haystack[i:i + n] == needle:
            return [i, i + n]
    return None


def detect_periodicity_modification(submitted_tokens, candidate, config):
    """Detect submitted_title == candidate_title + periodicity term(s).

    Only fires when the candidate's own tokens are fully contained in the
    submission (candidate is the "base" being modified) and the leftover
    submitted tokens look like a periodicity qualifier. "Looks like" is
    judged two ways, since PRGI periodicity values are free text:
      1. the leftover token is in the configurable periodicity vocabulary, or
      2. the leftover token also appears in this specific candidate's own
         actual Periodicity field (e.g. a submission adding "friday" to a
         title whose real Periodicity is "Daily (Monday to Friday)").
    """
    candidate_tokens = tokenize_title(candidate["normalized_title"])
    candidate_token_set = set(candidate_tokens)
    submitted_token_set = set(submitted_tokens)

    candidate_is_subset = bool(candidate_token_set) and candidate_token_set.issubset(submitted_token_set)
    leftover = submitted_token_set - candidate_token_set

    result = {
        "detected": False,
        "terms": [],
        "candidate_title": candidate["Title"],
        "candidate_periodicity": candidate.get("Periodicity", ""),
    }
    if not candidate_is_subset or not leftover:
        return result

    vocab = set(config["periodicity_terms"]["terms"])
    candidate_periodicity_tokens = set(tokenize_title(normalize_title(candidate.get("Periodicity", ""))))

    matched = sorted(t for t in leftover if t in vocab or t in candidate_periodicity_tokens)
    result["detected"] = bool(matched)
    result["terms"] = matched
    return result


def detect_generic_components(submitted_tokens, candidate, config):
    """Report generic/problematic components (config-driven) added or removed
    relative to this candidate. This is reporting only - it does not judge
    whether the presence of these components is acceptable.
    """
    generic = set(config["generic_components"]["terms"])
    submitted_set = set(submitted_tokens)
    candidate_tokens = set(tokenize_title(candidate["normalized_title"]))

    added = sorted((submitted_set - candidate_tokens) & generic)
    removed = sorted((candidate_tokens - submitted_set) & generic)

    return {
        "detected": bool(added or removed),
        "added_relative_to_candidate": added,
        "removed_relative_to_candidate": removed,
        "present_in_submitted_title": sorted(submitted_set & generic),
        "present_in_candidate_title": sorted(candidate_tokens & generic),
    }


def detect_disallowed_words(submitted_tokens, config):
    """Check the submitted title's tokens against the configured disallowed-word
    list. Not candidate-dependent - this is a property of the submitted title
    itself, so it is computed once per submission, not once per candidate.
    """
    matches = []
    for entry in config["disallowed_words"]["terms"]:
        term_tokens = tokenize_title(normalize_title(entry["term"]))
        span = _find_subsequence(submitted_tokens, term_tokens)
        if span is not None:
            matches.append({
                "term": entry["term"],
                "category": entry.get("category", ""),
                "token_position": span[0],
            })

    return {
        "detected": bool(matches),
        "matches": matches,
        "list_status": config["disallowed_words"]["status"],
    }


def build_title_index(corpus):
    """Map normalized_title -> corpus rows, for exact component lookups."""
    index = {}
    for row in corpus:
        index.setdefault(row["normalized_title"], []).append(row)
    return index


def detect_combination(submitted_tokens, title_index, config):
    """Detect whether the submitted title looks like >=2 distinct existing
    titles concatenated together.

    Deliberately simple, as scoped: this is an EXACT lookup, not fuzzy
    matching. For every contiguous, proper (strictly shorter than the
    whole submission) span of submitted tokens, check whether that exact
    span - joined back into a normalized title - exists as a real title
    in the processed corpus. This intentionally does not depend on the
    top-k window of the earlier fuzzy retrieval: a short single-token
    component title (e.g. "AAJ") can legitimately be a real component of
    a combination even when it would not itself score highly enough to
    appear in a fuzzy top-k search for the whole longer submitted title,
    so combination detection is checked against the full title index
    instead. Among all matching spans, a simple greedy longest-span-first,
    non-overlapping selection is used to report one clean combination
    reading, and the submission is flagged only when that reading is made
    of two or more distinct existing titles.
    """
    n = len(submitted_tokens)
    found = []
    for length in range(1, n):  # proper components only: 1 <= length < n
        for start in range(0, n - length + 1):
            span_tokens = submitted_tokens[start:start + length]
            rows = title_index.get(" ".join(span_tokens))
            if rows:
                row = rows[0]
                found.append({
                    "candidate_title": row["Title"],
                    "registration_number": row["Registration Number"],
                    "matched_tokens": span_tokens,
                    "submitted_token_span": [start, start + length],
                })

    # Greedy: prefer longer, then earlier, non-overlapping spans.
    found.sort(key=lambda m: (-(m["submitted_token_span"][1] - m["submitted_token_span"][0]), m["submitted_token_span"][0]))
    covered = [False] * n
    chosen = []
    for m in found:
        s, e = m["submitted_token_span"]
        if not any(covered[s:e]):
            chosen.append(m)
            for i in range(s, e):
                covered[i] = True

    coverage_ratio = round(sum(covered) / n, 2) if n else 0.0

    return {
        "detected": len(chosen) >= 2,
        "component_matches": chosen,
        "submitted_token_coverage_ratio": coverage_ratio,
    }


def structural_evidence(candidate):
    """Token-level structure, reusing the shared/submitted_only/candidate_only
    fields already computed by src/matching/retrieval.py rather than
    recomputing set differences.
    """
    return {
        "shared_tokens": candidate["shared_tokens"],
        "submitted_only_tokens": candidate["submitted_only_tokens"],
        "candidate_only_tokens": candidate["candidate_only_tokens"],
        "candidate_is_subset_of_submitted": len(candidate["candidate_only_tokens"]) == 0,
        "submitted_is_subset_of_candidate": len(candidate["submitted_only_tokens"]) == 0,
    }


def evaluate_rules(submitted_title, candidates, title_index, config=None):
    """Attach a "rules" evidence block to each candidate and return the
    submission-level evidence alongside it. Does not modify any existing
    lexical or phonetic fields already present on the candidates.

    title_index is the full corpus title index from build_title_index(),
    used only for exact-lookup combination detection - it is not a fresh
    fuzzy search and does not affect which candidates were retrieved.
    """
    config = config or load_config()
    submitted_normalized = normalize_title(submitted_title)
    submitted_tokens = tokenize_title(submitted_normalized)

    disallowed_words = detect_disallowed_words(submitted_tokens, config)
    combination = detect_combination(submitted_tokens, title_index, config)

    for candidate in candidates:
        candidate["rules"] = {
            "periodicity": detect_periodicity_modification(submitted_tokens, candidate, config),
            "generic_components": detect_generic_components(submitted_tokens, candidate, config),
            "disallowed_words": disallowed_words,
            "combination": combination,
            "structure": structural_evidence(candidate),
        }

    return {
        "submitted_title": submitted_title,
        "submitted_normalized_title": submitted_normalized,
        "submitted_tokens": submitted_tokens,
        "disallowed_words": disallowed_words,
        "combination": combination,
        "candidates": candidates,
    }


def print_result(result):
    print_phonetic_result(result)

    print("=" * 60)
    print("Submission-level rule evidence")
    print("=" * 60)
    dw = result["disallowed_words"]
    print(f"\nDisallowed words: detected={dw['detected']}")
    for m in dw["matches"]:
        print(f"    '{m['term']}' (category: {m['category']}, position {m['token_position']})")
    print(f"    list_status: {dw['list_status']}")

    comb = result["combination"]
    print(f"\nCombination: detected={comb['detected']}  "
          f"submitted_token_coverage_ratio={comb['submitted_token_coverage_ratio']}")
    for m in comb["component_matches"]:
        print(f"    {m['candidate_title']!r} (Reg No: {m['registration_number']}) "
              f"matched tokens {m['matched_tokens']} at span {m['submitted_token_span']}")

    print("\nPer-candidate rule evidence:\n")
    for i, c in enumerate(result["candidates"], 1):
        r = c["rules"]
        print(f"  [{i}] {c['Title']!r}  (Reg No: {c['Registration Number']})")
        print(f"      periodicity: {r['periodicity']}")
        print(f"      generic_components: {r['generic_components']}")
        print(f"      structure: {r['structure']}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Search the processed PRGI corpus and report lexical + phonetic + rule evidence."
    )
    parser.add_argument("title", help="Submitted title to check.")
    parser.add_argument("--corpus", default=DEFAULT_CORPUS_PATH, help="Path to the processed corpus CSV.")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help="Number of candidates to retrieve.")
    parser.add_argument("--config", default=CONFIG_PATH, help="Path to the rules config JSON.")
    args = parser.parse_args()

    corpus = load_corpus(args.corpus)
    config = load_config(args.config)
    title_index = build_title_index(corpus)
    lexical_and_phonetic = search_title_with_phonetics(args.title, corpus, top_k=args.top_k)
    result = evaluate_rules(args.title, lexical_and_phonetic["candidates"], title_index, config=config)
    print_result(result)


if __name__ == "__main__":
    main()

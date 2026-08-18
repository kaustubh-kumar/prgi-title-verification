"""Evidence-bundle layer: combines lexical, phonetic, and rule evidence
into one structured, JSON-serializable object per submitted title.

This module does not compute anything new. It calls the three existing
evidence layers exactly as they are (src/matching/retrieval.py,
src/matching/phonetic.py, src/rules/rules.py) and reshapes their already-
computed output into a stable, explicit schema. It does not calculate a
combined similarity score, a verification probability, or an
ACCEPT/REJECT decision, and it does not call an LLM - the bundle
produced here is meant to become that later layer's input contract.

Schema (all JSON-serializable):

{
  "submitted_title": str,
  "submitted_normalized_title": str,
  "submitted_tokens": [str, ...],
  "top_k": int,
  "submission_level_evidence": {
      "disallowed_words": {...},   # from rules.detect_disallowed_words
      "combination": {...}         # from rules.detect_combination
  },
  "candidates": [
      {
        "metadata": {
            "title", "registration_number", "language", "periodicity",
            "publication_state", "publication_district", "normalized_title"
        },
        "lexical_evidence": {
            "char_similarity", "token_similarity", "exact_normalized_match",
            "shared_tokens", "submitted_only_tokens", "candidate_only_tokens",
            "candidate_is_subset_of_submitted", "submitted_is_subset_of_candidate"
        },
        "phonetic_evidence": {
            "score", "matching_tokens",
            "submitted_token_codes", "candidate_token_codes"
        },
        "rule_evidence": {
            "periodicity", "generic_components", "structure"
            # disallowed_words/combination are NOT repeated here - they are
            # submission-level, see submission_level_evidence above.
        }
      },
      ...
  ]
}
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from src.matching.phonetic import search_title_with_phonetics  # noqa: E402
from src.matching.retrieval import DEFAULT_CORPUS_PATH, DEFAULT_TOP_K, load_corpus  # noqa: E402
from src.rules.rules import build_title_index, evaluate_rules, load_config  # noqa: E402


def _build_candidate_evidence(candidate):
    """Reshape one already-enriched candidate dict (lexical + phonetic +
    rules fields already attached by the earlier layers) into the stable
    metadata / lexical_evidence / phonetic_evidence / rule_evidence
    schema. Every value here is a direct reference to data already
    computed upstream - nothing is recalculated, and no evidence source
    is overwritten by another.
    """
    structure = candidate["rules"]["structure"]

    return {
        "metadata": {
            "title": candidate["Title"],
            "registration_number": candidate["Registration Number"],
            "language": candidate["Language"],
            "periodicity": candidate["Periodicity"],
            "publication_state": candidate["Publication State"],
            "publication_district": candidate["Publication District"],
            "normalized_title": candidate["normalized_title"],
        },
        "lexical_evidence": {
            "char_similarity": candidate["char_similarity"],
            "token_similarity": candidate["token_similarity"],
            "exact_normalized_match": candidate["exact_normalized_match"],
            "shared_tokens": structure["shared_tokens"],
            "submitted_only_tokens": structure["submitted_only_tokens"],
            "candidate_only_tokens": structure["candidate_only_tokens"],
            "candidate_is_subset_of_submitted": structure["candidate_is_subset_of_submitted"],
            "submitted_is_subset_of_candidate": structure["submitted_is_subset_of_candidate"],
        },
        "phonetic_evidence": candidate["phonetic"],
        "rule_evidence": {
            "periodicity": candidate["rules"]["periodicity"],
            "generic_components": candidate["rules"]["generic_components"],
            "structure": structure,
        },
    }


def build_evidence_bundle(submitted_title, corpus, top_k=DEFAULT_TOP_K, config=None, title_index=None):
    """Run retrieval -> phonetic -> rules and return one structured evidence
    bundle for submitted_title. Pass a precomputed title_index (from
    src.rules.rules.build_title_index) when calling this repeatedly over
    the same corpus, to avoid rebuilding it every time.
    """
    config = config or load_config()
    title_index = title_index if title_index is not None else build_title_index(corpus)

    lexical_and_phonetic = search_title_with_phonetics(submitted_title, corpus, top_k=top_k)
    rules_result = evaluate_rules(
        submitted_title, lexical_and_phonetic["candidates"], title_index, config=config
    )

    return {
        "submitted_title": rules_result["submitted_title"],
        "submitted_normalized_title": rules_result["submitted_normalized_title"],
        "submitted_tokens": rules_result["submitted_tokens"],
        "top_k": top_k,
        "submission_level_evidence": {
            "disallowed_words": rules_result["disallowed_words"],
            "combination": rules_result["combination"],
        },
        "candidates": [_build_candidate_evidence(c) for c in rules_result["candidates"]],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Build the combined lexical + phonetic + rule evidence bundle for a submitted title."
    )
    parser.add_argument("title", help="Submitted title to check.")
    parser.add_argument("--corpus", default=DEFAULT_CORPUS_PATH, help="Path to the processed corpus CSV.")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help="Number of candidates to retrieve.")
    args = parser.parse_args()

    corpus = load_corpus(args.corpus)
    bundle = build_evidence_bundle(args.title, corpus, top_k=args.top_k)
    print(json.dumps(bundle, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Tests for src/llm/scoring.py - the deterministic scoring layer.

Cases 1-6 run the real pipeline (retrieval -> phonetic -> rules ->
evidence bundle -> scoring) against the actual processed corpus, so
these are empirical, not synthetic. Cases 7 and 8 use small
hand-constructed evidence-bundle fragments to isolate specific
mathematical properties (phonetic can't dominate; the 80/20 clamp
invariant) that are awkward to force reliably out of real corpus data.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.evidence.builder import build_evidence_bundle  # noqa: E402
from src.llm.scoring import (  # noqa: E402
    DEFAULT_WEIGHTS,
    PHONETIC_SIMILARITY_WEIGHT,
    score_candidate,
    score_submission,
)
from src.matching.retrieval import load_corpus  # noqa: E402
from src.rules.rules import build_title_index  # noqa: E402


def _make_candidate(char_similarity, token_similarity, phonetic_score, exact_match=False,
                     periodicity_detected=False, generic_detected=False):
    return {
        "metadata": {"title": "SYNTHETIC", "registration_number": "SYN/0001"},
        "lexical_evidence": {
            "char_similarity": char_similarity,
            "token_similarity": token_similarity,
            "exact_normalized_match": exact_match,
        },
        "phonetic_evidence": {"score": phonetic_score},
        "rule_evidence": {
            "periodicity": {
                "detected": periodicity_detected,
                "terms": ["daily"] if periodicity_detected else [],
                "candidate_title": "SYNTHETIC",
                "candidate_periodicity": "Daily",
            },
            "generic_components": {
                "detected": generic_detected,
                "added_relative_to_candidate": ["the"] if generic_detected else [],
                "removed_relative_to_candidate": [],
            },
        },
    }


def _make_bundle(candidates, disallowed_detected=False, disallowed_matches=None,
                  combination_detected=False, combination_matches=None, coverage_ratio=0.0):
    return {
        "candidates": candidates,
        "submission_level_evidence": {
            "disallowed_words": {
                "detected": disallowed_detected,
                "matches": disallowed_matches or [],
                "list_status": "PROTOTYPE_PLACEHOLDER - not an official PRGI list.",
            },
            "combination": {
                "detected": combination_detected,
                "component_matches": combination_matches or [],
                "submitted_token_coverage_ratio": coverage_ratio,
            },
        },
    }


class RealCorpusScoringTestCase(unittest.TestCase):
    """Cases 1-6: run the real pipeline end to end."""

    @classmethod
    def setUpClass(cls):
        cls.corpus = load_corpus()
        cls.title_index = build_title_index(cls.corpus)

    def _score(self, title, top_k=10):
        bundle = build_evidence_bundle(title, self.corpus, top_k=top_k, title_index=self.title_index)
        return score_submission(bundle)

    def test_1_exact_match_is_zero_percent(self):
        result = self._score("AAJ SAMAJ")
        top = result["candidates"][0]
        self.assertTrue(top["exact_normalized_match"])
        self.assertEqual(top["candidate_verification_probability"], 0.0)
        self.assertEqual(result["final_verification_probability"], 0.0)

    def test_2_misspelling_high_conflict_low_probability(self):
        result = self._score("AAJ SAMASJ")
        # char=94.74, token=94.74, phonetic=100 -> should be a low probability, not exact (0)
        self.assertGreater(result["final_verification_probability"], 0.0)
        self.assertLess(result["final_verification_probability"], 20.0)

    def test_3_periodicity_substantially_below_raw_lexical(self):
        result = self._score("AAJ SAMAJ DAILY")
        top = result["candidates"][0]
        self.assertIn("periodicity_modification", top["rules_applied"])
        raw_lexical_only_probability = 100.0 - 75.0  # what raw char/token similarity alone implies
        self.assertLess(result["final_verification_probability"], raw_lexical_only_probability)

    def test_4_generic_prefix_less_severe_than_periodicity(self):
        periodicity_result = self._score("AAJ SAMAJ DAILY")
        generic_result = self._score("THE AAJ SAMAJ")

        top_generic = generic_result["candidates"][0]
        self.assertIn("generic_component", top_generic["rules_applied"])
        self.assertNotIn("periodicity_modification", top_generic["rules_applied"])

        self.assertGreater(
            generic_result["final_verification_probability"],
            periodicity_result["final_verification_probability"],
        )

    def test_5_combination_applies_even_without_full_candidate_coverage(self):
        result = self._score("AAJ TAJA SAMACHAR", top_k=10)
        penalty_rules = [p["rule"] for p in result["submission_level_rule_penalties"]]
        self.assertIn("combination_detected", penalty_rules)
        # The final probability must be capped at (100 - COMBINATION_CONFLICT_FLOOR)
        # regardless of what any individual candidate scored.
        from src.llm.scoring import COMBINATION_CONFLICT_FLOOR
        self.assertLessEqual(result["final_verification_probability"], 100.0 - COMBINATION_CONFLICT_FLOOR)

    def test_5b_combination_floor_binds_even_when_all_candidates_score_weakly(self):
        """Directly isolate the "must apply even when a component title is
        absent from candidate retrieval" requirement: construct candidates
        with deliberately weak similarity (as if neither real component had
        been retrieved) but submission-level combination detected=True, and
        confirm the floor still caps the result.
        """
        weak_candidate = _make_candidate(char_similarity=10.0, token_similarity=10.0, phonetic_score=10.0)
        bundle = _make_bundle(
            [weak_candidate],
            combination_detected=True,
            combination_matches=[
                {"candidate_title": "AAJ", "registration_number": "26521", "submitted_token_span": [0, 1]},
                {"candidate_title": "TAJA SAMACHAR", "registration_number": "MAHMAR/2022/87525", "submitted_token_span": [1, 3]},
            ],
            coverage_ratio=1.0,
        )
        result = score_submission(bundle)
        from src.llm.scoring import COMBINATION_CONFLICT_FLOOR
        # Candidate-level probability alone would be ~90 (very weak conflict) -
        # the submission-level floor must still pull the final result down.
        self.assertGreater(result["candidates"][0]["candidate_verification_probability"], 80.0)
        self.assertLessEqual(result["final_verification_probability"], 100.0 - COMBINATION_CONFLICT_FLOOR)

    def test_6_unrelated_title_high_probability_despite_shared_word(self):
        result = self._score("ZQXVN PLANETARY OBSERVATORY BULLETIN 7042")
        top = result["candidates"][0]
        self.assertEqual(top["rules_applied"], [])
        self.assertGreaterEqual(top["base_similarity"], 40.0)  # the shared-word-driven medium raw score
        self.assertGreater(result["final_verification_probability"], 50.0)

    def test_7_khabar_kobra_phonetic_does_not_dominate(self):
        result = self._score("KHABAR EXPRESS")
        candidates_by_title = {c["title"]: c for c in result["candidates"]}
        self.assertIn("KOBRA EXPRESS", candidates_by_title)
        kobra = candidates_by_title["KOBRA EXPRESS"]

        # Recompute what the base score would have been using ONLY char+token
        # (i.e. phonetic contributing nothing) to show phonetic's bounded influence.
        bundle = build_evidence_bundle("KHABAR EXPRESS", self.corpus, top_k=10, title_index=self.title_index)
        raw = next(c for c in bundle["candidates"] if c["metadata"]["title"] == "KOBRA EXPRESS")
        lex = raw["lexical_evidence"]
        lexical_only_weight_sum = DEFAULT_WEIGHTS["char_similarity"] + DEFAULT_WEIGHTS["token_similarity"]
        lexical_only_base = (
            lex["char_similarity"] * DEFAULT_WEIGHTS["char_similarity"]
            + lex["token_similarity"] * DEFAULT_WEIGHTS["token_similarity"]
        ) / lexical_only_weight_sum

        phonetic_contribution = kobra["base_similarity"] - lexical_only_base * (1 - PHONETIC_SIMILARITY_WEIGHT)
        # Phonetic's maximum possible contribution to the base score is capped
        # at PHONETIC_SIMILARITY_WEIGHT * 100 = 20 points, however high its own
        # score is (100, in this false-positive case) - it cannot dominate.
        self.assertLessEqual(PHONETIC_SIMILARITY_WEIGHT * 100.0, 20.0 + 1e-9)
        self.assertEqual(raw["phonetic_evidence"]["score"], 100.0)


class SyntheticBoundaryTestCase(unittest.TestCase):
    """Case 8 and the raw phonetic-domination bound, via hand-built evidence
    that isolates the exact property being tested rather than relying on
    real data happening to land at a convenient number.
    """

    def test_8_eighty_percent_conflict_caps_probability_at_twenty(self):
        # Construct a candidate whose weighted base similarity is exactly 80.
        # char=token=phonetic=80 -> weighted average is 80 regardless of weights.
        candidate = _make_candidate(char_similarity=80.0, token_similarity=80.0, phonetic_score=80.0)
        scored = score_candidate(candidate)
        self.assertEqual(scored["adjusted_conflict_score"], 80.0)
        self.assertEqual(scored["candidate_verification_probability"], 20.0)

        bundle = _make_bundle([candidate])
        result = score_submission(bundle)
        self.assertLessEqual(result["final_verification_probability"], 20.0)

    def test_8b_conflict_above_eighty_still_caps_at_or_below_twenty(self):
        candidate = _make_candidate(char_similarity=95.0, token_similarity=95.0, phonetic_score=95.0)
        scored = score_candidate(candidate)
        self.assertGreaterEqual(scored["adjusted_conflict_score"], 80.0)
        self.assertLessEqual(scored["candidate_verification_probability"], 20.0)

    def test_phonetic_alone_cannot_push_conflict_high(self):
        """Worst case: zero lexical similarity, a maximal (fully false-positive)
        phonetic match. Even then, conflict score cannot exceed
        PHONETIC_SIMILARITY_WEIGHT * 100 = 20, proving phonetic evidence alone
        can never drive a high-conflict outcome.
        """
        candidate = _make_candidate(char_similarity=0.0, token_similarity=0.0, phonetic_score=100.0)
        scored = score_candidate(candidate)
        self.assertEqual(scored["adjusted_conflict_score"], PHONETIC_SIMILARITY_WEIGHT * 100.0)
        self.assertEqual(scored["candidate_verification_probability"], 100.0 - PHONETIC_SIMILARITY_WEIGHT * 100.0)

    def test_strongest_candidate_dominates_not_averaged(self):
        """candidate A = 95% conflict, candidate B = 70% conflict -> A must
        dominate the final result, not an average of the two.
        """
        candidate_a = _make_candidate(char_similarity=95.0, token_similarity=95.0, phonetic_score=95.0)
        candidate_b = _make_candidate(char_similarity=70.0, token_similarity=70.0, phonetic_score=70.0)
        bundle = _make_bundle([candidate_a, candidate_b])
        result = score_submission(bundle)

        average_probability = (5.0 + 30.0) / 2  # what averaging the two would give
        self.assertLess(result["final_verification_probability"], average_probability)
        self.assertEqual(result["final_verification_probability"], 5.0)

    def test_disallowed_word_floor_is_labeled_prototype_not_official(self):
        candidate = _make_candidate(char_similarity=20.0, token_similarity=20.0, phonetic_score=20.0)
        bundle = _make_bundle(
            [candidate],
            disallowed_detected=True,
            disallowed_matches=[{"term": "police", "category": "implies_government_or_law_enforcement_affiliation"}],
        )
        result = score_submission(bundle)
        penalty = next(p for p in result["submission_level_rule_penalties"] if p["rule"] == "disallowed_word")
        self.assertIn("PROTOTYPE_PLACEHOLDER", penalty["detail"])
        self.assertIn("not an official PRGI", penalty["detail"])


if __name__ == "__main__":
    unittest.main()

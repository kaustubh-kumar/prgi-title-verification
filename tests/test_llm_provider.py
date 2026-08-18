"""Tests for src/llm/provider.py using mocked LLM responses.

None of these tests require GEMINI_API_KEY or network access: the LLM
call is replaced with a fixed mock function via build_verification_result's
generate_fn parameter. They exercise the real evidence pipeline (against
the actual processed corpus) plus schema validation and the
verification_probability placeholder - only the network call is faked.
"""

import os
import sys
import unittest

import jsonschema

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.llm.provider import build_verification_result  # noqa: E402
from src.llm.schema import LLM_RESPONSE_SCHEMA  # noqa: E402
from src.matching.retrieval import load_corpus  # noqa: E402
from src.rules.rules import build_title_index  # noqa: E402


def make_mock_response(decision, confidence=0.8, violations=None, similar_titles=None, explanation="mock explanation"):
    return {
        "decision": decision,
        "confidence": confidence,
        "violations": violations or [],
        "similar_titles": similar_titles or [],
        "explanation": explanation,
    }


class LLMProviderTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = load_corpus()
        cls.title_index = build_title_index(cls.corpus)

    def _run(self, title, mock_response, top_k=5):
        calls = []

        def mock_generate(system_prompt, user_prompt):
            calls.append((system_prompt, user_prompt))
            return mock_response

        output = build_verification_result(
            title,
            self.corpus,
            top_k=top_k,
            title_index=self.title_index,
            generate_fn=mock_generate,
        )
        return output, calls

    def test_exact_title(self):
        mock = make_mock_response(
            "LIKELY_REJECT",
            confidence=0.95,
            violations=[{"type": "exact_normalized_match", "evidence": "Identical to an existing registered title."}],
            similar_titles=[{"title": "AAJ SAMAJ", "registration_number": "HARHIN/2022/83438", "similarity": 100.0}],
        )
        output, calls = self._run("AAJ SAMAJ", mock)

        self.assertEqual(len(calls), 1)
        self.assertGreater(len(output["evidence_bundle"]["candidates"]), 0)
        self.assertEqual(output["evidence_bundle"]["candidates"][0]["lexical_evidence"]["char_similarity"], 100.0)

        jsonschema.validate(instance=mock, schema=LLM_RESPONSE_SCHEMA)
        self.assertEqual(output["result"]["decision"], "LIKELY_REJECT")
        # verification_probability is now owned by src.llm.scoring (see
        # tests/test_scoring.py), not a None placeholder - an exact match
        # deterministically scores 0.0, regardless of what the mocked LLM said.
        self.assertEqual(output["result"]["verification_probability"], 0.0)
        self.assertEqual(output["result"]["confidence"], 0.95)

    def test_misspelled_title(self):
        mock = make_mock_response(
            "LIKELY_REJECT",
            confidence=0.7,
            violations=[{"type": "phonetic_match", "evidence": "Matches 'AAJ SAMAJ' phonetically despite a spelling difference."}],
            similar_titles=[{"title": "AAJ SAMAJ", "registration_number": "HARHIN/2022/83438", "similarity": 94.74}],
        )
        output, _ = self._run("AAJ SAMASJ", mock)

        top = output["evidence_bundle"]["candidates"][0]
        self.assertFalse(top["lexical_evidence"]["exact_normalized_match"])
        self.assertEqual(top["phonetic_evidence"]["score"], 100.0)
        self.assertEqual(output["result"]["decision"], "LIKELY_REJECT")
        # Deterministic scoring layer, not the mocked LLM, owns this value.
        self.assertIsNotNone(output["result"]["verification_probability"])
        self.assertLess(output["result"]["verification_probability"], 20.0)

    def test_title_plus_periodicity_word(self):
        mock = make_mock_response(
            "LIKELY_REJECT",
            confidence=0.85,
            violations=[{"type": "periodicity_modification", "evidence": "Adds 'daily' to the existing title 'AAJ SAMAJ'."}],
            similar_titles=[{"title": "AAJ SAMAJ", "registration_number": "HARHIN/2022/83438", "similarity": 75.0}],
        )
        output, _ = self._run("AAJ SAMAJ DAILY", mock)

        top = output["evidence_bundle"]["candidates"][0]
        self.assertTrue(top["rule_evidence"]["periodicity"]["detected"])
        self.assertEqual(output["result"]["decision"], "LIKELY_REJECT")

    def test_generic_prefix_title(self):
        mock = make_mock_response(
            "REVIEW",
            confidence=0.5,
            violations=[{"type": "generic_component_added", "evidence": "Adds the generic prefix 'the' to 'AAJ SAMAJ'."}],
            similar_titles=[{"title": "AAJ SAMAJ", "registration_number": "HARHIN/2022/83438", "similarity": 81.82}],
        )
        output, _ = self._run("THE AAJ SAMAJ", mock)

        top = output["evidence_bundle"]["candidates"][0]
        self.assertTrue(top["rule_evidence"]["generic_components"]["detected"])
        self.assertEqual(output["result"]["decision"], "REVIEW")

    def test_combination_title(self):
        mock = make_mock_response(
            "LIKELY_REJECT",
            confidence=0.75,
            violations=[{
                "type": "combination_detected",
                "evidence": "Formed by combining existing titles 'AAJ' and 'TAJA SAMACHAR'.",
            }],
            similar_titles=[
                {"title": "TAJA SAMACHAR", "registration_number": "MAHMAR/2022/87525", "similarity": 86.67},
            ],
        )
        output, _ = self._run("AAJ TAJA SAMACHAR", mock, top_k=10)

        self.assertTrue(output["evidence_bundle"]["submission_level_evidence"]["combination"]["detected"])
        self.assertEqual(output["result"]["decision"], "LIKELY_REJECT")

    def test_unrelated_title(self):
        mock = make_mock_response(
            "LIKELY_ACCEPT",
            confidence=0.9,
            violations=[],
            similar_titles=[],
            explanation="No material lexical, phonetic, or rule evidence of conflict with any retrieved candidate.",
        )
        output, _ = self._run("ZQXVN PLANETARY OBSERVATORY BULLETIN 7042", mock)

        top = output["evidence_bundle"]["candidates"][0]
        self.assertLess(top["lexical_evidence"]["char_similarity"], 60)
        self.assertEqual(output["result"]["decision"], "LIKELY_ACCEPT")
        # Deterministic scoring layer correctly reads this as low conflict.
        self.assertGreater(output["result"]["verification_probability"], 50.0)

    def test_invalid_mock_response_fails_schema_validation(self):
        """Schema validation must actually reject a malformed LLM response,
        e.g. an out-of-enum decision or a missing required field.
        """
        bad_mock = {
            "decision": "MAYBE",  # not in the allowed enum
            "confidence": 0.5,
            "violations": [],
            "similar_titles": [],
            "explanation": "bad",
        }

        def bad_generate(system_prompt, user_prompt):
            return bad_mock

        with self.assertRaises(jsonschema.ValidationError):
            build_verification_result(
                "AAJ SAMAJ",
                self.corpus,
                top_k=3,
                title_index=self.title_index,
                generate_fn=bad_generate,
            )


if __name__ == "__main__":
    unittest.main()

"""Deterministic verification-probability scoring.

Consumes the evidence bundle produced by src.evidence.builder exactly as
it is - no retrieval, phonetic, rule, or evidence-builder logic is
duplicated or modified here. This module owns verification_probability;
the LLM layer (src/llm/provider.py) never computes or alters it.

DESIGN PRINCIPLE: similarity evidence and structural/rule evidence are
NOT treated as one undifferentiated score.

  A. Similarity evidence (continuous, weighted into a base score):
     char_similarity, token_similarity, phonetic_similarity.
     Weights are named constants (SimilarityWeights below) so they are
     easy to find and change. Token similarity is weighted highest and
     phonetic lowest, specifically because real-corpus testing found
     phonetic false positives on transliterated Indian words (e.g.
     "khabar" vs "kobra" collide under Soundex/Double Metaphone) - see
     PHONETIC_SIMILARITY_WEIGHT below. Because char+token together carry
     80% of the weight, phonetic evidence alone can shift the base score
     by at most PHONETIC_SIMILARITY_WEIGHT * 100 = 20 points, however
     high its own score is - it contributes, it cannot dominate.

  B. Structural/rule evidence (discrete, applied AFTER the base score,
     as adjustments/floors, not blended into the weighted average):
     exact_normalized_match, periodicity modification, generic
     components, disallowed words, combination detection.

Everything in this module is an explicit, transparent, hand-set
prototype constant, not a statistically calibrated model. It is a
deterministic function of the supplied evidence, not a probability in
the statistical sense - the docstrings and code below say so
deliberately and repeatedly, per the task's own instruction not to call
it "calibrated."

SUBMISSION-LEVEL VS CANDIDATE-LEVEL EVIDENCE:
disallowed_words and combination detection live only in
bundle["submission_level_evidence"], not inside any single candidate
(see src/evidence/builder.py - this was a deliberate choice there to
avoid repeating submission-wide facts once per candidate). This module
reads that key directly. In particular, combination detection is a
capped conflict floor applied at the submission level: a combination
title can be flagged even when one of its component titles never made
it into the fuzzy top-k candidate list (this was observed empirically
with "AAJ TAJA SAMACHAR", whose "AAJ" component only shows up via the
corpus-wide exact lookup in src/rules/rules.py, never as a retrieved
candidate) - so the penalty must not depend on iterating candidates.

Candidates are scored independently and never averaged together. The
final submission-level verification_probability is driven by whichever
single candidate or submission-level rule signal implies the strongest
conflict (the minimum probability), matching the requirement that a 95%
conflict candidate must dominate a 70% conflict candidate rather than
being diluted by it.
"""

# --- A. Similarity evidence weights -----------------------------------
# Must sum to 1.0. Kept as named constants, not buried in a formula, so
# they are trivial to find and retune later.
TOKEN_SIMILARITY_WEIGHT = 0.45
CHAR_SIMILARITY_WEIGHT = 0.35
PHONETIC_SIMILARITY_WEIGHT = 0.20

DEFAULT_WEIGHTS = {
    "token_similarity": TOKEN_SIMILARITY_WEIGHT,
    "char_similarity": CHAR_SIMILARITY_WEIGHT,
    "phonetic_similarity": PHONETIC_SIMILARITY_WEIGHT,
}

# --- B. Structural/rule adjustments (applied after the base score) ----
# Candidate-level additive adjustments, in conflict-score points (0-100 scale).
PERIODICITY_MODIFICATION_BOOST = 20.0
GENERIC_COMPONENT_BOOST = 5.0

# Submission-level conflict FLOORS (not additive - they cap how high
# verification_probability is allowed to go, applied via
# min(candidate_probability, 100 - floor), independent of any one
# candidate's own score). Disallowed-word evidence is currently only a
# PROTOTYPE_PLACEHOLDER list (see src/rules/config.json) - the floor is
# still applied as a strong prototype signal, but every adjustment record
# for it explicitly carries that PROTOTYPE_PLACEHOLDER status so nothing
# downstream can present it as official PRGI policy.
DISALLOWED_WORD_CONFLICT_FLOOR = 70.0
COMBINATION_CONFLICT_FLOOR = 60.0


def _clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


def score_candidate(candidate, weights=None):
    """Score one candidate independently. Returns the detailed per-candidate
    scoring evidence described in the task's requirement 6.
    """
    weights = weights or DEFAULT_WEIGHTS
    lex = candidate["lexical_evidence"]
    phon = candidate["phonetic_evidence"]
    rule = candidate["rule_evidence"]
    meta = candidate["metadata"]

    exact_match = bool(lex["exact_normalized_match"])
    rule_adjustments = []

    if exact_match:
        # Requirement 1: exact normalized match is always maximum conflict,
        # regardless of what the weighted similarity blend would say.
        base_similarity = 100.0
        adjusted_conflict_score = 100.0
        rule_adjustments.append({
            "rule": "exact_normalized_match",
            "points": None,
            "detail": "Submitted title is identical to this candidate after normalization - treated as maximum conflict, overriding the weighted similarity blend.",
        })
    else:
        base_similarity = (
            lex["char_similarity"] * weights["char_similarity"]
            + lex["token_similarity"] * weights["token_similarity"]
            + phon["score"] * weights["phonetic_similarity"]
        )
        conflict_score = base_similarity

        periodicity = rule["periodicity"]
        if periodicity["detected"]:
            conflict_score += PERIODICITY_MODIFICATION_BOOST
            rule_adjustments.append({
                "rule": "periodicity_modification",
                "points": PERIODICITY_MODIFICATION_BOOST,
                "detail": (
                    f"Submitted title appears to add periodicity term(s) {periodicity['terms']} to "
                    f"existing title '{periodicity['candidate_title']}' (its actual Periodicity is "
                    f"{periodicity['candidate_periodicity']!r}). Treated as a strong conflict signal, "
                    "per the PSS06 requirement to detect periodicity-word gaming."
                ),
            })

        generic = rule["generic_components"]
        if generic["detected"]:
            conflict_score += GENERIC_COMPONENT_BOOST
            rule_adjustments.append({
                "rule": "generic_component",
                "points": GENERIC_COMPONENT_BOOST,
                "detail": (
                    f"Generic component(s) differ relative to this candidate - added: "
                    f"{generic['added_relative_to_candidate']}, removed: "
                    f"{generic['removed_relative_to_candidate']}. This is evidence only, weighted "
                    "lightly, and does not by itself cause rejection."
                ),
            })

        adjusted_conflict_score = _clamp(conflict_score)

    candidate_verification_probability = _clamp(100.0 - adjusted_conflict_score)

    return {
        "title": meta["title"],
        "registration_number": meta["registration_number"],
        "exact_normalized_match": exact_match,
        "base_similarity": round(base_similarity, 2),
        "rule_adjustments": rule_adjustments,
        "rules_applied": [a["rule"] for a in rule_adjustments],
        "adjusted_conflict_score": round(adjusted_conflict_score, 2),
        "candidate_verification_probability": round(candidate_verification_probability, 2),
    }


def score_submission(evidence_bundle, weights=None):
    """Score every candidate independently, apply submission-level rule
    floors from bundle["submission_level_evidence"], and return the full
    detailed scoring result (requirement 6): per-candidate evidence plus
    submission-level strongest-candidate/penalties/final probability.

    Candidates are never averaged. The final verification_probability is
    the minimum (i.e. strongest-conflict) probability across all
    candidate-level results and all submission-level conflict floors.
    """
    weights = weights or DEFAULT_WEIGHTS

    candidate_scores = [score_candidate(c, weights) for c in evidence_bundle["candidates"]]

    submission_evidence = evidence_bundle["submission_level_evidence"]
    submission_rule_penalties = []
    conflict_floor = 0.0

    disallowed = submission_evidence["disallowed_words"]
    if disallowed["detected"]:
        conflict_floor = max(conflict_floor, DISALLOWED_WORD_CONFLICT_FLOOR)
        submission_rule_penalties.append({
            "rule": "disallowed_word",
            "conflict_floor": DISALLOWED_WORD_CONFLICT_FLOOR,
            "detail": (
                f"Submitted title matches disallowed-word list entries: "
                f"{[m['term'] for m in disallowed['matches']]}. "
                f"IMPORTANT: {disallowed['list_status']}"
            ),
        })

    combination = submission_evidence["combination"]
    if combination["detected"]:
        conflict_floor = max(conflict_floor, COMBINATION_CONFLICT_FLOOR)
        component_titles = [m["candidate_title"] for m in combination["component_matches"]]
        submission_rule_penalties.append({
            "rule": "combination_detected",
            "conflict_floor": COMBINATION_CONFLICT_FLOOR,
            "detail": (
                f"Submitted title appears to combine existing titles {component_titles} "
                f"(submitted-token coverage {combination['submitted_token_coverage_ratio']:.0%}). "
                "Applied at submission level - this holds even if not every component title was "
                "returned by the fuzzy candidate search."
            ),
        })

    if candidate_scores:
        strongest = min(candidate_scores, key=lambda s: s["candidate_verification_probability"])
        candidate_min_probability = strongest["candidate_verification_probability"]
        strongest_conflict_score = strongest["adjusted_conflict_score"]
        strongest_summary = {
            "title": strongest["title"],
            "registration_number": strongest["registration_number"],
            "candidate_verification_probability": candidate_min_probability,
        }
    else:
        candidate_min_probability = 100.0
        strongest_conflict_score = 0.0
        strongest_summary = None

    submission_floor_probability = _clamp(100.0 - conflict_floor)
    final_verification_probability = round(min(candidate_min_probability, submission_floor_probability), 2)

    return {
        "candidates": candidate_scores,
        "strongest_candidate": strongest_summary,
        "strongest_conflict_score": strongest_conflict_score,
        "submission_level_rule_penalties": submission_rule_penalties,
        "final_verification_probability": final_verification_probability,
        "weights_used": dict(weights),
        "note": (
            "Deterministic prototype score derived from supplied evidence, using transparent "
            "hand-set constants. Not a statistically calibrated probability."
        ),
    }


def calculate_verification_probability(evidence_bundle, llm_response=None):
    """Entry point used by src.llm.provider.build_verification_result().

    Signature is unchanged from the previous placeholder so no other
    module needs to change. llm_response is accepted for interface
    compatibility/future context only and is never used to influence the
    result - the LLM does not get a vote on verification_probability.
    """
    return score_submission(evidence_bundle)["final_verification_probability"]

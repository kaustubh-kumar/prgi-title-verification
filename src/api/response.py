"""Shapes the API response the frontend expects, by combining data already
produced by src.llm.provider.build_verification_result() and
src.llm.scoring.score_submission() - no new evidence, scores, or rules are
computed here. This is pure response assembly/enrichment:

  - similar_titles from the LLM response only has title/registration_number/
    similarity; this adds language/periodicity/publication_state/
    publication_district by matching registration_number against the
    evidence bundle's candidate metadata (exactly the enrichment the
    frontend's mock service already documented as "what the real API layer
    will need to do" - see frontend/js/mockApi.js).
  - evidence exposes the strongest candidate's lexical/token/phonetic
    breakdown and rule count, read from score_submission()'s output -
    the same fields the frontend's mock evidence panel already expects.
"""


def _find_candidate_metadata(evidence_bundle, registration_number):
    for candidate in evidence_bundle["candidates"]:
        if candidate["metadata"]["registration_number"] == registration_number:
            return candidate["metadata"]
    return None


def _find_candidate_evidence(evidence_bundle, registration_number):
    for candidate in evidence_bundle["candidates"]:
        if candidate["metadata"]["registration_number"] == registration_number:
            return candidate
    return None


def _enrich_similar_titles(similar_titles, evidence_bundle):
    enriched = []
    for entry in similar_titles:
        meta = _find_candidate_metadata(evidence_bundle, entry["registration_number"]) or {}
        enriched.append({
            "title": entry["title"],
            "registration_number": entry["registration_number"],
            "similarity": entry["similarity"],
            "language": meta.get("language") or None,
            "periodicity": meta.get("periodicity") or None,
            "publication_state": meta.get("publication_state") or None,
            "publication_district": meta.get("publication_district") or None,
        })
    return enriched


def _build_evidence_panel(evidence_bundle, score_result):
    strongest = score_result["strongest_candidate"]
    if not strongest:
        return {
            "strongest_candidate": None,
            "lexical_similarity": 0,
            "token_similarity": 0,
            "phonetic_similarity": 0,
            "exact_match": False,
            "rule_evidence_count": 0,
        }

    scored_candidate = next(
        (c for c in score_result["candidates"] if c["registration_number"] == strongest["registration_number"]),
        None,
    )
    eb_candidate = _find_candidate_evidence(evidence_bundle, strongest["registration_number"])

    return {
        "strongest_candidate": {
            "title": strongest["title"],
            "registration_number": strongest["registration_number"],
        },
        "lexical_similarity": eb_candidate["lexical_evidence"]["char_similarity"] if eb_candidate else None,
        "token_similarity": eb_candidate["lexical_evidence"]["token_similarity"] if eb_candidate else None,
        "phonetic_similarity": eb_candidate["phonetic_evidence"]["score"] if eb_candidate else None,
        "exact_match": bool(scored_candidate["exact_normalized_match"]) if scored_candidate else False,
        "rule_evidence_count": len(scored_candidate["rules_applied"]) if scored_candidate else 0,
    }


def build_api_response(submitted_title, verification_output, score_result):
    """verification_output is the return value of
    src.llm.provider.build_verification_result() (has "evidence_bundle"
    and "result"). score_result is the return value of a separate
    src.llm.scoring.score_submission(evidence_bundle) call over the same
    bundle - used only for the richer per-candidate breakdown the
    verification_probability-only result value doesn't carry.
    """
    evidence_bundle = verification_output["evidence_bundle"]
    result = verification_output["result"]

    return {
        "submitted_title": submitted_title,
        "decision": result["decision"],
        "verification_probability": result["verification_probability"],
        "confidence": result["confidence"],
        "violations": result["violations"],
        "similar_titles": _enrich_similar_titles(result["similar_titles"], evidence_bundle),
        "explanation": result["explanation"],
        "evidence": _build_evidence_panel(evidence_bundle, score_result),
    }

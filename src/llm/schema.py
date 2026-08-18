"""Structured-output schema for the LLM decision/explanation layer.

LLM_RESPONSE_SCHEMA is what the LLM is constrained to produce - it is
passed to Gemini as response_json_schema (so the API itself enforces the
shape, not just prompt wording) and is validated again locally with the
jsonschema library after the response comes back.

It deliberately does NOT include verification_probability. Per the task
requirements, that field must come from a deterministic scoring module
(see src/llm/scoring.py - currently a placeholder), never from the LLM,
so it is not even a field the LLM is allowed to fill in.

FINAL_RESULT_SCHEMA describes the complete result returned by
src.llm.provider.build_verification_result(), i.e. the LLM's response
plus verification_probability merged in afterwards by our own code.
"""

DECISIONS = ["LIKELY_ACCEPT", "LIKELY_REJECT", "REVIEW"]

_VIOLATION_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "description": "Short label for the evidence category, e.g. 'periodicity_modification'."},
        "evidence": {"type": "string", "description": "One-line grounding in the actual supplied evidence."},
    },
    "required": ["type", "evidence"],
}

_SIMILAR_TITLE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "registration_number": {"type": "string"},
        "similarity": {
            "type": "number",
            "description": (
                "Must be copied exactly from that candidate's lexical_evidence.char_similarity "
                "in the supplied evidence bundle - never computed or estimated."
            ),
        },
    },
    "required": ["title", "registration_number", "similarity"],
}

LLM_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": DECISIONS},
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "The model's own qualitative judgement of evidence strength/completeness, in [0, 1].",
        },
        "violations": {"type": "array", "items": _VIOLATION_SCHEMA},
        "similar_titles": {"type": "array", "items": _SIMILAR_TITLE_SCHEMA},
        "explanation": {"type": "string"},
    },
    "required": ["decision", "confidence", "violations", "similar_titles", "explanation"],
}

FINAL_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": DECISIONS},
        "verification_probability": {
            "type": ["number", "null"],
            "description": "Computed by src.llm.scoring, not the LLM. Currently always null (placeholder, unimplemented).",
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "violations": {"type": "array", "items": _VIOLATION_SCHEMA},
        "similar_titles": {"type": "array", "items": _SIMILAR_TITLE_SCHEMA},
        "explanation": {"type": "string"},
    },
    "required": [
        "decision", "verification_probability", "confidence",
        "violations", "similar_titles", "explanation",
    ],
}

"""LLM provider selection + orchestration for the PSS06 verification prototype.

Selects a provider implementation via the LLM_PROVIDER environment
variable (default: "gemini"). Provider-specific code lives in its own
module (src/llm/gemini.py for Gemini) so a different provider can be
added later as a sibling module (e.g. src/llm/openai.py) without
touching this file's orchestration logic.

This module does not duplicate the evidence pipeline - it calls
src.evidence.builder.build_evidence_bundle() exactly as-is and only adds
the LLM call, JSON-schema validation, and merging in the (currently
placeholder) deterministic verification_probability.
"""

import argparse
import json
import os
import sys

import jsonschema

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from src.evidence.builder import build_evidence_bundle  # noqa: E402
from src.llm import scoring  # noqa: E402
from src.llm.prompt import build_system_prompt, build_user_prompt  # noqa: E402
from src.llm.schema import LLM_RESPONSE_SCHEMA  # noqa: E402
from src.matching.retrieval import DEFAULT_CORPUS_PATH, DEFAULT_TOP_K, load_corpus  # noqa: E402
from src.rules.rules import build_title_index  # noqa: E402

SUPPORTED_PROVIDERS = ("gemini",)


def get_provider(name=None):
    """Return a generate_verification(system_prompt, user_prompt) callable
    for the requested provider. Provider modules are imported lazily so
    e.g. the google-genai SDK is only touched when Gemini is actually used.
    """
    name = (name or os.environ.get("LLM_PROVIDER", "gemini")).lower()
    if name == "gemini":
        from src.llm import gemini
        return gemini.generate_verification
    raise ValueError(f"Unsupported LLM_PROVIDER: {name!r}. Supported providers: {SUPPORTED_PROVIDERS}.")


def build_verification_result(
    submitted_title,
    corpus,
    top_k=DEFAULT_TOP_K,
    provider_name=None,
    title_index=None,
    generate_fn=None,
):
    """Build the evidence bundle, ask the LLM to interpret it, validate the
    response against LLM_RESPONSE_SCHEMA, and merge in
    verification_probability (currently always None - see
    src/llm/scoring.py).

    generate_fn overrides provider selection entirely when supplied; this
    is how tests inject a mocked LLM response without needing an API key
    or touching the network.

    Returns {"evidence_bundle": ..., "result": ...} - the evidence bundle
    is included so callers/tests can inspect exactly what the LLM saw.
    """
    evidence_bundle = build_evidence_bundle(submitted_title, corpus, top_k=top_k, title_index=title_index)

    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(evidence_bundle)

    generate = generate_fn or get_provider(provider_name)
    llm_response = generate(system_prompt, user_prompt)

    jsonschema.validate(instance=llm_response, schema=LLM_RESPONSE_SCHEMA)

    result = {
        "decision": llm_response["decision"],
        "verification_probability": scoring.calculate_verification_probability(evidence_bundle, llm_response),
        "confidence": llm_response["confidence"],
        "violations": llm_response["violations"],
        "similar_titles": llm_response["similar_titles"],
        "explanation": llm_response["explanation"],
    }

    return {"evidence_bundle": evidence_bundle, "result": result}


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Build the evidence bundle for a submitted title, send it to the configured LLM "
            "provider, validate the structured response, and print the result. Requires "
            "GEMINI_API_KEY (or the configured provider's key) to be set."
        )
    )
    parser.add_argument("title", help="Submitted title to check.")
    parser.add_argument("--corpus", default=DEFAULT_CORPUS_PATH, help="Path to the processed corpus CSV.")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help="Number of candidates to retrieve.")
    parser.add_argument("--provider", default=None, help="Override LLM_PROVIDER for this run.")
    args = parser.parse_args()

    corpus = load_corpus(args.corpus)
    title_index = build_title_index(corpus)

    output = build_verification_result(
        args.title, corpus, top_k=args.top_k, provider_name=args.provider, title_index=title_index
    )

    print(f"Evidence bundle: {len(output['evidence_bundle']['candidates'])} candidates retrieved for {args.title!r}\n")
    print(json.dumps(output["result"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

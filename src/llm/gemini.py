"""Gemini provider for the LLM decision/explanation layer.

Isolated so a different provider (e.g. OpenAI) can be added later as its
own sibling module without touching src/llm/provider.py's orchestration
logic or any other provider's code.

The API key is read only from the GEMINI_API_KEY environment variable -
never hardcoded, never committed (see .env.example). The model name is
configurable via GEMINI_MODEL so it can be updated without a code change
if a newer/cheaper model becomes the better default.

Structured output is enforced by the Gemini API itself via
response_json_schema + response_mime_type="application/json" (using
LLM_RESPONSE_SCHEMA from src/llm/schema.py), not only by prompt wording.
"""

import json
import os

from google import genai
from google.genai import types

from src.llm.schema import LLM_RESPONSE_SCHEMA

DEFAULT_MODEL = "gemini-3.6-flash"


def generate_verification(system_prompt, user_prompt, model=None):
    """Call Gemini and return the parsed JSON response (a dict).

    Raises RuntimeError if GEMINI_API_KEY is not set - this is only
    called from the real-API code path (src.llm.provider's CLI or a
    caller that didn't inject a mock generate_fn); tests never reach
    this function.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Copy .env.example to .env and set a real key, "
            "or export GEMINI_API_KEY in your shell, to call the real Gemini API."
        )

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        response_mime_type="application/json",
        response_json_schema=LLM_RESPONSE_SCHEMA,
        temperature=0,
    )

    response = client.models.generate_content(
        model=model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL),
        contents=user_prompt,
        config=config,
    )

    return json.loads(response.text)

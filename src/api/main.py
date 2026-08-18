"""HTTP API for the PRGI title verification pipeline.

Thin wrapper around the existing, unmodified pipeline:
normalize_title/tokenize_title -> Postgres candidate retrieval
(src.db.corpus) -> src.evidence.builder / src.llm.provider
(retrieval/phonetic/rules/scoring/Gemini, all untouched) -> API response.

Run locally:
    uvicorn src.api.main:app --reload --port 8000

Required environment variables (see .env.example):
    SUPABASE_DB_URL   Postgres connection string (local or Supabase).
    GEMINI_API_KEY    Gemini API key.
Optional:
    FRONTEND_ORIGIN   Comma-separated allowed CORS origins for the
                       frontend. Defaults to common local dev origins.
    VERIFY_TOP_K       Number of candidates used for evidence/scoring
                       (default 10 - see the module docstring note in
                       src/db/corpus.py about DEFAULT_BLOCKING_LIMIT vs
                       this value: Postgres blocks a larger set, Python
                       re-ranks down to this many for the actual evidence
                       bundle, exactly as it always has against the CSV).
"""

import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("prgi_verify_api")

from src.data.preprocess import normalize_title, tokenize_title  # noqa: E402
from src.db.connection import get_connection  # noqa: E402
from src.db.corpus import DEFAULT_BLOCKING_LIMIT, fetch_candidates, fetch_light_title_index  # noqa: E402
from src.llm.provider import build_verification_result  # noqa: E402
from src.llm.scoring import score_submission  # noqa: E402
from src.api.response import build_api_response  # noqa: E402

VERIFY_TOP_K = int(os.environ.get("VERIFY_TOP_K", "10"))
MAX_TITLE_LENGTH = 300

DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:8765",
    "http://127.0.0.1:8765",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def _allowed_origins():
    raw = os.environ.get("FRONTEND_ORIGIN", "")
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    return origins or DEFAULT_ALLOWED_ORIGINS


app = FastAPI(title="PRGI Title Verification API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class VerifyRequest(BaseModel):
    title: str = Field(..., description="Proposed publication title.")


@app.get("/health")
def health():
    """Liveness/readiness check. Verifies DB connectivity without leaking
    connection details - only a boolean and, on failure, a generic reason.
    """
    db_ok = True
    db_detail = "ok"
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        finally:
            conn.close()
    except Exception:
        logger.exception("Health check: database connectivity failed")
        db_ok = False
        db_detail = "unavailable"

    return {"status": "ok" if db_ok else "degraded", "database": db_detail}


@app.post("/api/verify")
def verify(request: VerifyRequest):
    title = request.title.strip()

    if not title:
        raise HTTPException(status_code=400, detail="title must not be empty.")
    if len(title) > MAX_TITLE_LENGTH:
        raise HTTPException(status_code=400, detail=f"title must be at most {MAX_TITLE_LENGTH} characters.")

    try:
        conn = get_connection()
    except RuntimeError as exc:
        # Missing SUPABASE_DB_URL - a configuration error, safe to surface
        # as-is (it names the env var, not a credential value).
        logger.error("Verify request failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception:
        logger.exception("Verify request failed: could not connect to the database")
        raise HTTPException(status_code=503, detail="Database is currently unavailable. Please try again shortly.")

    try:
        normalized = normalize_title(title)
        tokens = tokenize_title(normalized)

        candidates = fetch_candidates(conn, normalized, tokens, limit=DEFAULT_BLOCKING_LIMIT)
        title_index = fetch_light_title_index(conn)

        try:
            output = build_verification_result(
                title, candidates, top_k=VERIFY_TOP_K, title_index=title_index
            )
        except RuntimeError as exc:
            # e.g. GEMINI_API_KEY not set - configuration error, safe to surface.
            logger.error("Verify request failed (LLM configuration): %s", exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except Exception:
            logger.exception("Verify request failed: LLM provider call failed")
            raise HTTPException(
                status_code=502, detail="The verification model is currently unavailable. Please try again shortly."
            )

        score_result = score_submission(output["evidence_bundle"])
        return build_api_response(title, output, score_result)
    finally:
        conn.close()

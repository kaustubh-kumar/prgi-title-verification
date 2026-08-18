"""Vercel Python entry point.

This file exists ONLY because Vercel's Python runtime expects a function
under api/. It does not define or duplicate any route, request handling,
or verification logic - it re-exports the existing, unmodified FastAPI
app from src/api/main.py exactly as-is. vercel.json routes /health and
/api/* to this file; main.py's own @app.get("/health") and
@app.post("/api/verify") handle everything from there, unchanged.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.api.main import app  # noqa: E402,F401

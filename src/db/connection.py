"""Postgres/Supabase connection handling.

Reads the connection string exclusively from the SUPABASE_DB_URL
environment variable - never hardcoded, never committed. This is a
direct Postgres connection string (e.g. Supabase's "Connection string"
under Project Settings -> Database, or a local Postgres URL during
development), not the Supabase REST/anon-key client - the backend talks
to Postgres directly so it can call the search_prgi_titles() SQL
function and read prgi_titles with a normal SQL driver (psycopg).

The Supabase service-role key and anon key are NOT used here and must
never be given to the frontend - see src/api/main.py and
frontend/js/realApi.js for where the actual trust boundary is drawn.
"""

import os

import psycopg
from psycopg.rows import dict_row

ENV_VAR = "SUPABASE_DB_URL"


def get_dsn():
    dsn = os.environ.get(ENV_VAR)
    if not dsn:
        raise RuntimeError(
            f"{ENV_VAR} is not set. Copy .env.example to .env and set it to a Postgres "
            "connection string (a local Postgres URL for development, or your Supabase "
            "project's connection string for production)."
        )
    return dsn


def get_connection():
    """Return a new psycopg connection with dict-shaped rows.

    Callers are responsible for closing the connection (or using it as a
    context manager) - this module does not maintain a pool. For the
    current prototype's request volume, opening one connection per
    request is simple and adequate; introducing a pool (e.g.
    psycopg_pool) would be the natural next step under real load.
    """
    return psycopg.connect(get_dsn(), row_factory=dict_row)

"""Import the processed PRGI CSV corpus into Postgres (prgi_titles).

Idempotent: safe to rerun. Upserts on registration_number (the same
identity column src/data/preprocess.py already treats as record identity,
and which the migration enforces as UNIQUE) - rerunning with the same CSV
overwrites each row with identical data; rerunning after the CSV changes
updates existing rows and inserts new ones without creating duplicates.
created_at is preserved across reruns (only set on first insert);
updated_at is maintained by the migration's trigger.

Does not invent placeholder values: a blank source field (Language,
Periodicity, Publication District, Registration Date) is imported as SQL
NULL, matching the migration's nullable columns exactly - never a string
like "UNKNOWN"/"N/A". Duplicate normalized titles (e.g. 16 different
"AAJ SAMAJ" registration records) are NOT deduplicated - each has its own
registration_number and becomes its own row, exactly as before.
"""

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime

from src.db.connection import get_connection

DEFAULT_CSV_PATH = "data/processed/prgi_titles.csv"


def load_rows(csv_path):
    with open(csv_path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def build_report(rows):
    total = len(rows)
    regno_counts = Counter(r["Registration Number"] for r in rows)
    duplicate_regnos = {k: v for k, v in regno_counts.items() if v > 1}

    empty_counts = {}
    for field in (
        "Title", "normalized_title", "Registration Number", "Registration Date",
        "Language", "Periodicity", "Publication State", "Publication District", "title_tokens",
    ):
        empty_counts[field] = sum(1 for r in rows if not r.get(field, "").strip())

    norm_counts = Counter(r["normalized_title"] for r in rows)
    duplicate_norm_titles = {k: v for k, v in norm_counts.items() if v > 1}

    return {
        "total_rows": total,
        "unique_registration_numbers": len(regno_counts),
        "duplicate_registration_numbers": duplicate_regnos,
        "empty_field_counts": empty_counts,
        "duplicate_normalized_title_count": len(duplicate_norm_titles),
        "duplicate_normalized_title_examples": sorted(
            duplicate_norm_titles.items(), key=lambda kv: -kv[1]
        )[:5],
    }


def print_report(report):
    print("=== Pre-import validation report ===")
    print(f"Total rows: {report['total_rows']}")
    print(f"Unique registration numbers: {report['unique_registration_numbers']}")
    print(f"Duplicate registration numbers: {len(report['duplicate_registration_numbers'])}")
    for regno, count in report["duplicate_registration_numbers"].items():
        print(f"  {regno!r}: {count} occurrences")
    print("Empty/missing field counts:")
    for field, count in report["empty_field_counts"].items():
        print(f"  {field}: {count}")
    print(f"Normalized titles with more than one registration record: {report['duplicate_normalized_title_count']}")
    print("Top examples (title: record count):")
    for title, count in report["duplicate_normalized_title_examples"]:
        print(f"  {title!r}: {count}")
    print()


def _blank_to_none(value):
    value = (value or "").strip()
    return value if value else None


def _parse_date(value):
    value = (value or "").strip()
    if not value:
        return None
    return datetime.strptime(value, "%d-%m-%Y").date()


def row_to_record(row):
    """Map one processed-CSV row to the exact column set/order the upsert
    below inserts. Blank source fields become None (SQL NULL) - never a
    placeholder string.
    """
    title_tokens = json.loads(row["title_tokens"])
    metadata = {
        "publisher": _blank_to_none(row.get("Publisher", "")),
        "owner": _blank_to_none(row.get("Owner", "")),
        "sn": _blank_to_none(row.get("SN.", "")),
        "source_file": _blank_to_none(row.get("source_file", "")),
    }
    return {
        "title": row["Title"],
        "normalized_title": row["normalized_title"],
        "title_tokens": title_tokens,
        "registration_number": row["Registration Number"],
        "registration_date": _parse_date(row.get("Registration Date", "")),
        "language": _blank_to_none(row.get("Language", "")),
        "periodicity": _blank_to_none(row.get("Periodicity", "")),
        "publication_state": row["Publication State"],
        "publication_district": _blank_to_none(row.get("Publication District", "")),
        "metadata": json.dumps(metadata),
    }


UPSERT_SQL = """
INSERT INTO prgi_titles (
    title, normalized_title, title_tokens, registration_number,
    registration_date, language, periodicity, publication_state,
    publication_district, metadata
) VALUES (
    %(title)s, %(normalized_title)s, %(title_tokens)s, %(registration_number)s,
    %(registration_date)s, %(language)s, %(periodicity)s, %(publication_state)s,
    %(publication_district)s, %(metadata)s
)
ON CONFLICT (registration_number) DO UPDATE SET
    title = EXCLUDED.title,
    normalized_title = EXCLUDED.normalized_title,
    title_tokens = EXCLUDED.title_tokens,
    registration_date = EXCLUDED.registration_date,
    language = EXCLUDED.language,
    periodicity = EXCLUDED.periodicity,
    publication_state = EXCLUDED.publication_state,
    publication_district = EXCLUDED.publication_district,
    metadata = EXCLUDED.metadata
    -- created_at intentionally omitted: preserved across reruns.
    -- updated_at is maintained by the trg_prgi_titles_updated_at trigger.
"""


def import_rows(conn, rows):
    records = [row_to_record(r) for r in rows]
    with conn.cursor() as cur:
        cur.executemany(UPSERT_SQL, records)
    conn.commit()
    return len(records)


def main():
    parser = argparse.ArgumentParser(description="Import the processed PRGI CSV corpus into Postgres.")
    parser.add_argument("--csv", default=DEFAULT_CSV_PATH, help="Path to the processed corpus CSV.")
    parser.add_argument("--report-only", action="store_true", help="Print the validation report and exit without importing.")
    args = parser.parse_args()

    rows = load_rows(args.csv)
    report = build_report(rows)
    print_report(report)

    if args.report_only:
        return

    conn = get_connection()
    try:
        imported = import_rows(conn, rows)
        print(f"Imported/updated {imported} rows.")

        actual_count = None
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM prgi_titles")
            actual_count = cur.fetchone()["n"]
        print(f"SELECT COUNT(*) FROM prgi_titles -> {actual_count}")
        if actual_count != report["total_rows"]:
            print(
                f"WARNING: row count mismatch - CSV had {report['total_rows']} rows, "
                f"table now has {actual_count}. This is expected if the table already "
                f"contained other rows before this import; investigate otherwise.",
                file=sys.stderr,
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()

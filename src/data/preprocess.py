"""Preprocessing pipeline for raw PRGI title CSV exports.

Loads every CSV in data/raw/, concatenates them, deduplicates exact
duplicate records (keyed on all original fields except SN.), and adds
normalized derived fields needed by later similarity/rule stages. No
similarity scoring, embeddings, or LLM calls happen here.
"""

import argparse
import csv
import glob
import json
import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

ORIGINAL_COLUMNS = [
    "SN.",
    "Title",
    "Registration Number",
    "Registration Date",
    "Language",
    "Periodicity",
    "Publisher",
    "Owner",
    "Publication State",
    "Publication District",
]

# SN. is source/display ordering only, never part of record identity.
DEDUP_COLUMNS = [c for c in ORIGINAL_COLUMNS if c != "SN."]

DERIVED_COLUMNS = [
    "normalized_title",
    "normalized_language",
    "language_list",
    "normalized_periodicity",
    "title_tokens",
]

OUTPUT_COLUMNS = ["source_file"] + ORIGINAL_COLUMNS + DERIVED_COLUMNS

# Unicode punctuation that commonly varies without being a meaningful
# difference between titles (curly quotes, em/en dash, minus sign).
_PUNCT_MAP = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-",
})

_WHITESPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def load_raw_csvs(raw_dir):
    """Load and concatenate all PRGI CSV exports in raw_dir, preserving originals."""
    rows = []
    for path in sorted(glob.glob(os.path.join(raw_dir, "*.csv"))):
        with open(path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for record in reader:
                row = {col: (record.get(col) or "").strip() for col in ORIGINAL_COLUMNS}
                row["source_file"] = os.path.basename(path)
                rows.append(row)
    return rows


def dedupe_exact(rows):
    """Drop rows that are complete duplicates of an earlier row.

    Two rows are duplicates only when every original field (other than
    SN., which is just export ordering) matches. A shared Registration
    Number with any differing field is kept as-is, not merged.
    """
    seen = set()
    deduped = []
    for row in rows:
        key = tuple(row[c] for c in DEDUP_COLUMNS)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def normalize_title(title):
    """Unicode-normalize, casefold, and whitespace/punctuation-normalize a title.

    Does not strip generic words (the/india/news/daily/...) or transliterate.
    """
    text = unicodedata.normalize("NFKC", title)
    text = text.translate(_PUNCT_MAP)
    text = text.casefold()
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def normalize_language(language):
    """Casefold/whitespace-normalize a (possibly comma-separated) language field.

    Returns (normalized_string, list_of_individual_languages). Does not
    apply any language-name dictionary/canonicalization beyond casing
    and whitespace.
    """
    parts = [
        _WHITESPACE_RE.sub(" ", part.strip().casefold())
        for part in language.split(",")
        if part.strip()
    ]
    normalized = ", ".join(parts)
    return normalized, parts


def normalize_periodicity(periodicity):
    """Casefold/whitespace-normalize a periodicity field without collapsing variants."""
    text = unicodedata.normalize("NFKC", periodicity)
    text = text.casefold()
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def tokenize_title(normalized_title):
    """Tokenize a normalized title on Unicode word boundaries.

    Works for Latin and Indian scripts alike since \\w is Unicode-aware
    in Python 3. No transliteration, no stopword removal.
    """
    return _TOKEN_RE.findall(normalized_title)


def enrich(row):
    """Add derived fields to a row in place, preserving all original fields."""
    normalized_title = normalize_title(row["Title"])
    normalized_language, language_list = normalize_language(row["Language"])
    normalized_periodicity = normalize_periodicity(row["Periodicity"])

    row["normalized_title"] = normalized_title
    row["normalized_language"] = normalized_language
    row["language_list"] = json.dumps(language_list, ensure_ascii=False)
    row["normalized_periodicity"] = normalized_periodicity
    row["title_tokens"] = json.dumps(tokenize_title(normalized_title), ensure_ascii=False)
    return row


@dataclass
class PreprocessReport:
    input_rows: int
    output_rows: int
    duplicate_registration_numbers_input: int
    duplicate_registration_numbers_remaining: int
    duplicate_titles: int
    language_counts: Counter
    periodicity_counts: Counter


def build_report(input_rows, output_rows):
    input_regno_counts = Counter(r["Registration Number"] for r in input_rows)
    output_regno_counts = Counter(r["Registration Number"] for r in output_rows)

    title_counts = Counter(r["normalized_title"] for r in output_rows)

    return PreprocessReport(
        input_rows=len(input_rows),
        output_rows=len(output_rows),
        duplicate_registration_numbers_input=sum(1 for c in input_regno_counts.values() if c > 1),
        duplicate_registration_numbers_remaining=sum(1 for c in output_regno_counts.values() if c > 1),
        duplicate_titles=sum(1 for c in title_counts.values() if c > 1),
        language_counts=Counter(r["normalized_language"] for r in output_rows),
        periodicity_counts=Counter(r["normalized_periodicity"] for r in output_rows),
    )


def run_preprocessing(raw_dir, output_path):
    raw_rows = load_raw_csvs(raw_dir)
    deduped_rows = dedupe_exact(raw_rows)
    processed_rows = [enrich(dict(row)) for row in deduped_rows]

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for row in processed_rows:
            writer.writerow({c: row.get(c, "") for c in OUTPUT_COLUMNS})

    report = build_report(raw_rows, processed_rows)
    return processed_rows, report


def print_report(report):
    print("=== Preprocessing report ===")
    print(f"Input rows: {report.input_rows}")
    print(f"Output rows: {report.output_rows}")
    print(f"Duplicate registration numbers (input, before dedup): {report.duplicate_registration_numbers_input}")
    print(f"Duplicate registration numbers (remaining after dedup - real conflicts): {report.duplicate_registration_numbers_remaining}")
    print(f"Normalized titles with more than one record: {report.duplicate_titles}")

    print("\nLanguage counts (normalized_language):")
    for lang, count in report.language_counts.most_common(20):
        print(f"  {lang}: {count}")

    print("\nPeriodicity counts (normalized_periodicity):")
    for period, count in report.periodicity_counts.most_common(20):
        print(f"  {period}: {count}")


def main():
    parser = argparse.ArgumentParser(description="Preprocess raw PRGI title CSV exports.")
    parser.add_argument("--raw-dir", default="data/raw", help="Directory containing raw PRGI CSV exports.")
    parser.add_argument("--output", default="data/processed/prgi_titles.csv", help="Path to write the processed CSV.")
    args = parser.parse_args()

    _, report = run_preprocessing(args.raw_dir, args.output)
    print_report(report)


if __name__ == "__main__":
    main()

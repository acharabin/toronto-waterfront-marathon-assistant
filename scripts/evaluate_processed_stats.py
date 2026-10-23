"""Check the configured processed runner results for duplicate identifiers/names."""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from marathon_assistant.config import load_project_config, resolve_project_path


ID_COLUMNS = ("place", "bib_number")
NAME_COLUMN = "name"
MAX_EXAMPLES = 10


def duplicate_groups(data: pl.DataFrame, columns: list[str]) -> pl.DataFrame:
    """Return duplicate key groups and their row counts."""
    return (
        data.group_by(columns)
        .agg(pl.len().alias("row_count"))
        .filter(pl.col("row_count") > 1)
        .sort("row_count", descending=True)
    )


def collect_duplicate_warnings(data: pl.DataFrame) -> list[str]:
    """Return warnings for duplicate IDs, normalized names, ID pairs, and rows."""
    required_columns = {*ID_COLUMNS, NAME_COLUMN}
    missing_columns = sorted(required_columns - set(data.columns))
    if missing_columns:
        raise ValueError(f"processed data is missing required columns: {missing_columns}")

    checks = [(f"{column} values", duplicate_groups(data, [column])) for column in ID_COLUMNS]
    normalized_data = data.with_columns(
        pl.col(NAME_COLUMN)
        .cast(pl.String)
        .str.strip_chars()
        .str.replace_all(r"\s+", " ")
        .str.to_lowercase()
        .alias("_normalized_name")
    )
    checks.extend([
        (
            "name values (case/whitespace normalized)",
            duplicate_groups(normalized_data, ["_normalized_name"]),
        ),
        ("(place, bib_number) pairs", duplicate_groups(data, ["place", "bib_number"])),
        ("fully identical rows", duplicate_groups(data, data.columns)),
    ])

    warnings = []
    for label, duplicates in checks:
        if duplicates.is_empty():
            continue
        extra_rows = sum(count - 1 for count in duplicates["row_count"].to_list())
        examples = duplicates.head(MAX_EXAMPLES).to_dicts()
        warnings.append(
            f"{label}: {duplicates.height} duplicate key(s), {extra_rows} extra row(s); "
            f"examples: {examples}"
        )
    return warnings


def main() -> int:
    config = load_project_config()
    results_path = resolve_project_path(config["paths"]["runner_results"])
    if not results_path.is_file():
        print(f"ERROR: processed results file not found: {results_path}")
        return 2

    data = pl.read_parquet(results_path)
    try:
        warnings = collect_duplicate_warnings(data)
    except ValueError as error:
        print(f"ERROR: {results_path} {error}")
        return 2

    print(f"Checking {results_path} ({data.height} rows)")
    for warning in warnings:
        print(f"WARN: {warning}")
    if warnings:
        print("\nDuplicate check failed: one or more duplicate categories were found.")
        return 1

    print("\nDuplicate check passed: no duplicate IDs, names, ID pairs, or rows found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

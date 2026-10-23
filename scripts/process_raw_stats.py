"""Parse scraped runner results, write Parquet, and report data quality issues."""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from marathon_assistant.config import load_project_config, resolve_project_path
from scripts.evaluate_processed_stats import collect_duplicate_warnings


PROJECT_CONFIG = load_project_config()
RAW_DATA_FILE = resolve_project_path(PROJECT_CONFIG["paths"]["raw_results"])
OUTPUT_DATA_FILE = resolve_project_path(PROJECT_CONFIG["paths"]["runner_results"])
DATA_COLUMNS = ["place", "name", "age_group", "bib_number", "time"]


def parse_raw_row(line: str) -> list[str]:
    """Parse one scraper row or raise ValueError when its format is invalid."""
    columns = line.split("|  |")
    if len(columns) != 4:
        raise ValueError("expected four scraped columns")

    place = columns[0].split("|", 1)[0].strip()
    age_group, separator, bib_number = columns[2].partition("Bib:")
    if not separator:
        raise ValueError("missing Bib field")

    time_parts = columns[3].split("|", 1)
    if len(time_parts) != 2:
        raise ValueError("missing time separator")

    return [
        place,
        columns[1].strip(),
        age_group.strip(),
        bib_number.strip(),
        time_parts[1].strip(),
    ]


def main() -> int:
    if not RAW_DATA_FILE.is_file():
        print(f"ERROR: raw results file not found: {RAW_DATA_FILE}")
        return 2

    raw_lines = RAW_DATA_FILE.read_text(encoding="utf-8").splitlines()
    raw_record_count = sum(bool(line.strip()) for line in raw_lines)
    processed_rows = []
    malformed_line_numbers = []

    for line_number, line in enumerate(raw_lines, start=1):
        if not line.strip():
            continue
        try:
            processed_rows.append(parse_raw_row(line))
        except ValueError:
            malformed_line_numbers.append(line_number)

    if not processed_rows:
        print("ERROR: no valid runner rows were parsed; processed output was not changed.")
        if malformed_line_numbers:
            print(f"Malformed raw line numbers: {malformed_line_numbers[:10]}")
        return 1

    processed_data = pl.DataFrame(processed_rows, schema=DATA_COLUMNS)
    print(processed_data.head())

    OUTPUT_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    processed_data.write_parquet(OUTPUT_DATA_FILE)

    warnings = []
    if malformed_line_numbers:
        warnings.append(
            f"{len(malformed_line_numbers)} nonblank raw record(s) could not be parsed; "
            f"line number examples: {malformed_line_numbers[:10]}"
        )
    if processed_data.height != raw_record_count:
        warnings.append(
            f"raw/processed record count mismatch: {raw_record_count} nonblank raw record(s), "
            f"{processed_data.height} processed record(s)"
        )
    warnings.extend(collect_duplicate_warnings(processed_data))

    print("\nData quality checks:")
    if warnings:
        for warning in warnings:
            print(f"WARNING: {warning}")
        return 1

    print(
        f"PASS: {raw_record_count} nonblank raw records match {processed_data.height} processed records; "
        "no duplicate IDs, names, ID pairs, or rows found."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

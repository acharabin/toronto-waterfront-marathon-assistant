"""Loading and embedding runner results."""

from pathlib import Path
from typing import Any

import polars as pl


def load_runner_stats_with_embeddings(
    runner_data_path: str | Path,
    embedding_model: Any,
) -> pl.DataFrame:
    """Load runner results, add name embeddings, and assign stable row IDs."""
    runner_stats = pl.read_parquet(runner_data_path)
    names = runner_stats["name"].to_list()
    name_embeddings = embedding_model.encode(names, convert_to_tensor=True)
    embedding_lists = list(name_embeddings.cpu().numpy())

    return runner_stats.with_columns(
        pl.Series("name_embedding", embedding_lists)
    ).with_row_index(name="corpus_id")

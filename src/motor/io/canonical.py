"""Agrupamento e leitura das tabelas canônicas, sem importar experimentos."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from motor.config import Params


@dataclass(frozen=True)
class CanonicalTables:
    """As quatro tabelas canônicas mais o cache de seleção de subconjunto --
    agrupadas para os consumidores de produto e experimentos."""

    sales: pl.LazyFrame
    items: pl.DataFrame
    suppliers: pl.DataFrame
    stock: pl.DataFrame
    subset_cache_path: Path


def load_canonical_tables(
    params: Params, *, subset_cache_path: Path | None = None
) -> CanonicalTables:
    """Carrega as quatro tabelas canônicas de `params.data.canonical_dir`.

    `subset_cache_path` default (`results/subset_selection.json`) é o mesmo
    arquivo compartilhado pelos consumidores da seleção -- reusar o cache
    já quente evita reselecionar o subconjunto.
    """
    canonical_dir = Path(params.data.canonical_dir)
    return CanonicalTables(
        sales=pl.scan_parquet(canonical_dir / "sales.parquet"),
        items=pl.read_parquet(canonical_dir / "items.parquet"),
        suppliers=pl.read_parquet(canonical_dir / "suppliers.parquet"),
        stock=pl.read_parquet(canonical_dir / "stock.parquet"),
        subset_cache_path=subset_cache_path or Path("results/subset_selection.json"),
    )

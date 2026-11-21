"""Overrides explícitos dos prazos de fornecedor; `None` preserva o cadastro."""

from __future__ import annotations

import polars as pl


def override_supplier_lead_time(suppliers: pl.DataFrame, lead_time_days: int) -> pl.DataFrame:
    """Sobrescreve o prazo de todos os fornecedores, sem alterar o frame original."""
    return suppliers.with_columns(pl.lit(lead_time_days).cast(pl.Int64).alias("lead_time_days"))


def override_supplier_review_period(
    suppliers: pl.DataFrame, review_period_days: int
) -> pl.DataFrame:
    """Sobrescreve a revisão de todos os fornecedores, sem alterar outras colunas."""
    return suppliers.with_columns(
        pl.lit(review_period_days).cast(pl.Int64).alias("review_period_days")
    )


def cell_suppliers(
    suppliers: pl.DataFrame,
    *,
    lead_time_days: int | None,
    review_period_days: int | None,
) -> pl.DataFrame:
    """Compõe os overrides sem defaults de experimento ou alteração do cadastro."""
    result = suppliers
    if lead_time_days is not None:
        result = override_supplier_lead_time(result, lead_time_days)
    if review_period_days is not None:
        result = override_supplier_review_period(result, review_period_days)
    return result

"""Utilitários da regressão do Favorita (Sprint 24, etapa 24.0).

Compartilhados entre o gerador da referência (`build_favorita_baseline.py`) e
o teste (`tests/test_regression_favorita.py`). Vivem em `tests/` de propósito:
a linha de base é instrumento de verificação, não lógica de negócio.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import polars as pl

from motor.config import Params

REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_JSON = Path(__file__).resolve().parent / "favorita_baseline.json"
REFERENCE_RESULTS_DIR = REPO_ROOT / "results" / "baseline_sprint24"
ARMS: tuple[str, ...] = ("erp_baseline", "estatistico_basestock")
CANONICAL_TABLES: tuple[str, ...] = ("sales", "items", "suppliers", "stock")

# Seções de `Params` que NÃO entram no hash: adicionadas por sprints
# posteriores, não são lidas pelos braços 1 e 2 (a 24.1 acrescenta
# `mercado_piloto` ao params.yaml e não pode quebrar a regressão).
EXCLUDED_PARAMS_SECTIONS: frozenset[str] = frozenset({"mercado_piloto"})

EVENTS_KEYS: tuple[str, ...] = ("store_id", "item_id", "day")
ITEM_METRICS_KEYS: tuple[str, ...] = ("item_id",)

REGENERATE_COMMAND = (
    "uv run python -m tests.regression.build_favorita_baseline "
    "(roda os dois braços, ~35 min, e grava results/baseline_sprint24/ + "
    "tests/regression/favorita_baseline.json)"
)


def sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    """sha256 de um arquivo, lido em blocos."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hashes(canonical_dir: Path) -> dict[str, str]:
    """sha256 de cada tabela canônica de entrada."""
    return {t: sha256_file(canonical_dir / f"{t}.parquet") for t in CANONICAL_TABLES}


def params_section_hashes(params: Params) -> dict[str, str]:
    """sha256 do JSON de cada seção de `Params`, exceto `EXCLUDED_PARAMS_SECTIONS`.

    Um hash por seção (e não um só) para que a mensagem de falha diga QUAL
    premissa mudou, antes de se culpar o motor.
    """
    return {
        name: hashlib.sha256(getattr(params, name).model_dump_json().encode("utf-8")).hexdigest()
        for name in sorted(type(params).model_fields)
        if name not in EXCLUDED_PARAMS_SECTIONS
    }


def sorted_frame(frame: pl.DataFrame, keys: tuple[str, ...]) -> pl.DataFrame:
    """Ordena pelas chaves, para comparar conteúdo e não ordem de gravação."""
    return frame.sort(list(keys))


def diff_report(
    expected: pl.DataFrame, actual: pl.DataFrame, keys: tuple[str, ...], *, limit: int = 5
) -> str:
    """Diferença por coluna e por item entre duas tabelas já ordenadas.

    Vazia quando idênticas (comparação exata). Lista, por coluna divergente,
    quantas linhas diferem e as `limit` primeiras chaves com os dois valores.
    """
    if expected.columns != actual.columns:
        return f"colunas diferentes: esperado {expected.columns}, obtido {actual.columns}"
    if expected.height != actual.height:
        return f"número de linhas diferente: esperado {expected.height}, obtido {actual.height}"
    lines: list[str] = []
    for col in expected.columns:
        if col in keys:
            continue
        exp, act = expected[col], actual[col]
        differs = ~((exp == act) | (exp.is_null() & act.is_null()))
        if exp.dtype.is_float():
            differs = differs & ~(exp.is_nan() & act.is_nan())
        n = int(differs.sum())
        if n == 0:
            continue
        lines.append(f"coluna {col!r}: {n} linha(s) divergem")
        sample = pl.DataFrame(
            {
                **{k: expected[k] for k in keys},
                "esperado": exp,
                "obtido": act,
            }
        ).filter(differs)
        lines.extend(f"    {row}" for row in sample.head(limit).iter_rows())
    return "\n".join(lines)

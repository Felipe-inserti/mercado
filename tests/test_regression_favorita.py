"""Regressão do Favorita (Sprint 24, etapa 24.0).

Re-roda os braços 1 (`erp_baseline`) e 2 (`estatistico_basestock`) sobre as
tabelas canônicas reais e compara com a referência congelada antes da Sprint 24
(`tests/regression/favorita_baseline.json` + `results/baseline_sprint24/`).
Segura as etapas 24.4 e 24.5: mudou sem explicação, para.

Lento (~35 min) e depende de `data/`: marcado `regression`, fora do pytest
padrão. Rodar com:

    uv run pytest -m regression --no-cov tests/test_regression_favorita.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from motor.config import load_params
from motor.experiments.run import run_arm_and_save
from tests.regression.favorita import (
    ARMS,
    EVENTS_KEYS,
    ITEM_METRICS_KEYS,
    REFERENCE_JSON,
    REFERENCE_RESULTS_DIR,
    REGENERATE_COMMAND,
    REPO_ROOT,
    canonical_hashes,
    diff_report,
    params_section_hashes,
    sorted_frame,
)

_PARAMS_PATH = REPO_ROOT / "config" / "params.yaml"
_CANONICAL_DIR = REPO_ROOT / "data" / "canonical" / "favorita"

_MISSING = [
    str(p)
    for p in (
        [_CANONICAL_DIR / f"{t}.parquet" for t in ("sales", "items", "suppliers", "stock")]
        + [REFERENCE_JSON, REFERENCE_RESULTS_DIR / "subset_selection.json"]
        + [
            REFERENCE_RESULTS_DIR / arm / f"{f}.parquet"
            for arm in ARMS
            for f in ("events", "item_metrics")
        ]
    )
    if not p.exists()
]

pytestmark = [
    pytest.mark.regression,
    pytest.mark.skipif(
        bool(_MISSING),
        reason=(
            f"insumos ausentes ({', '.join(_MISSING)}) -- data/ e results/ não vêm no "
            f"clone. Gere a referência com: {REGENERATE_COMMAND}"
        ),
    ),
]


def _reference() -> dict[str, object]:
    loaded: dict[str, object] = json.loads(REFERENCE_JSON.read_text())
    return loaded


def test_insumos_nao_mudaram() -> None:
    """Falha ANTES de culpar o motor: tabelas canônicas ou premissas diferentes."""
    ref = _reference()
    params = load_params(_PARAMS_PATH)

    assert canonical_hashes(_CANONICAL_DIR) == ref["canonical_sha256"], (
        "tabelas canônicas mudaram desde a referência -- a comparação não é válida"
    )
    atual = params_section_hashes(params)
    esperado = ref["params_section_sha256"]
    assert isinstance(esperado, dict)
    mudaram = sorted(s for s in esperado if atual.get(s) != esperado[s])
    assert not mudaram, f"seções de params.yaml mudaram desde a referência: {mudaram}"


@pytest.mark.parametrize("arm", ARMS)
def test_braco_identico_a_referencia(arm: str, tmp_path: Path) -> None:
    ref = _reference()
    params = load_params(_PARAMS_PATH)

    # Mesmo subconjunto da referência (o cache é lido, não reselecionado).
    shutil.copy(REFERENCE_RESULTS_DIR / "subset_selection.json", tmp_path / "subset_selection.json")
    manifest = run_arm_and_save(
        arm,
        params,
        sales=pl.scan_parquet(_CANONICAL_DIR / "sales.parquet"),
        items=pl.read_parquet(_CANONICAL_DIR / "items.parquet"),
        suppliers=pl.read_parquet(_CANONICAL_DIR / "suppliers.parquet"),
        stock=pl.read_parquet(_CANONICAL_DIR / "stock.parquet"),
        subset_cache_path=tmp_path / "subset_selection.json",
        canonical_dir=_CANONICAL_DIR,
        results_dir=tmp_path,
    )

    for name, keys in (("events", EVENTS_KEYS), ("item_metrics", ITEM_METRICS_KEYS)):
        esperado = sorted_frame(
            pl.read_parquet(REFERENCE_RESULTS_DIR / arm / f"{name}.parquet"), keys
        )
        obtido = sorted_frame(pl.read_parquet(tmp_path / arm / f"{name}.parquet"), keys)
        try:
            assert_frame_equal(esperado, obtido, check_exact=True)
        except AssertionError as exc:
            pytest.fail(
                f"{arm}/{name} divergiu da referência:\n"
                f"{diff_report(esperado, obtido, keys)}\n{exc}"
            )

    arm_ref = ref["arms"][arm]  # type: ignore[index]
    portfolio = manifest.model_dump(mode="json")["results"]["portfolio"]
    assert portfolio == arm_ref["portfolio"], f"{arm}: métricas do portfólio divergiram"
    assert manifest.n_items == arm_ref["n_items"]

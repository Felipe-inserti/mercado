"""Testes de `motor.experiments.sensitivity` (Sprint 16) -- só as funções
puras (`override_supplier_lead_time`, `build_cell_params`, `cell_dir`).
`run_cell`/`measure_one` rodam o pipeline inteiro (braço 3 inclusive) e são
caros demais para teste automatizado -- exercitados manualmente via CLI
(`--measure-one`), não aqui.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from motor.config import load_params
from motor.experiments.sensitivity import (
    build_cell_params,
    cell_dir,
    override_supplier_lead_time,
)

PARAMS_PATH = Path(__file__).resolve().parent.parent / "config" / "params.yaml"


def _suppliers() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "supplier_id": ["F1", "F2", "F3"],
            "lead_time_days": [3, 3, 3],
            "review_period_days": [7, 7, 7],
            "min_order_value": [0.0, 0.0, 0.0],
            "pack_multiple": [1.0, 1.0, 1.0],
        }
    )


def test_override_supplier_lead_time_sobrescreve_todos_os_fornecedores() -> None:
    suppliers = _suppliers()

    resultado = override_supplier_lead_time(suppliers, 6)

    assert resultado["lead_time_days"].to_list() == [6, 6, 6]
    # nada mais muda -- review_period_days é o eixo 2, não este
    assert resultado["review_period_days"].to_list() == suppliers["review_period_days"].to_list()
    assert resultado["supplier_id"].to_list() == suppliers["supplier_id"].to_list()


def test_override_supplier_lead_time_e_puro_nao_muda_o_frame_original() -> None:
    suppliers = _suppliers()

    override_supplier_lead_time(suppliers, 10)

    assert suppliers["lead_time_days"].to_list() == [3, 3, 3]


def test_build_cell_params_muda_so_default_alpha() -> None:
    params = load_params(PARAMS_PATH)
    alpha_novo = 0.70
    assert params.economics.default_alpha != alpha_novo  # premissa do teste

    cell_params = build_cell_params(params, alpha=alpha_novo)

    assert cell_params.economics.default_alpha == alpha_novo
    # nada mais no resto de Params muda
    assert cell_params.model.quantiles == params.model.quantiles
    assert cell_params.simulation == params.simulation
    assert cell_params.erp_baseline == params.erp_baseline


def test_build_cell_params_alpha_fora_da_grade_levanta_value_error() -> None:
    params = load_params(PARAMS_PATH)
    assert 0.42 not in set(params.model.quantiles)  # premissa do teste

    with pytest.raises(ValueError, match=r"model\.quantiles"):
        build_cell_params(params, alpha=0.42)


def test_cell_dir_formata_lead_time_e_alpha() -> None:
    resultado = cell_dir(Path("results"), lead_time_days=6, alpha=0.85)

    assert resultado == Path("results/sensibilidade/lt6_a0.85")

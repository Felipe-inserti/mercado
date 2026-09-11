"""Testes do modelo Params e do arquivo config/params.yaml do repositório."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from motor.config import Params, load_params

PARAMS_PATH = Path(__file__).resolve().parent.parent / "config" / "params.yaml"


def test_params_yaml_do_repositorio_valida() -> None:
    params = load_params(PARAMS_PATH)
    assert params.subset_selection.n_items_min <= params.subset_selection.n_items_max
    assert len(params.experiments.arms) >= 1


def test_params_rejeita_chave_desconhecida() -> None:
    valid = load_params(PARAMS_PATH)
    raw = valid.model_dump()
    raw["chave_desconhecida"] = 1
    with pytest.raises(ValidationError, match="chave_desconhecida"):
        Params.model_validate(raw)


def test_params_rejeita_fracao_fora_do_intervalo() -> None:
    valid = load_params(PARAMS_PATH)
    raw = valid.model_dump()
    raw["economics"]["default_alpha"] = 1.5
    with pytest.raises(ValidationError, match="default_alpha"):
        Params.model_validate(raw)

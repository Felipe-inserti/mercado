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


# -- alpha tem que bater com a grade de quantis (Sprint 12) -------------------


def test_params_rejeita_default_alpha_fora_da_grade_de_quantis() -> None:
    valid = load_params(PARAMS_PATH)
    raw = valid.model_dump()
    raw["model"]["quantiles"] = [0.5, 0.8, 0.9, 0.95]
    raw["economics"]["default_alpha"] = 0.93  # não está na grade acima
    with pytest.raises(ValidationError, match=r"default_alpha=0\.93.*model\.quantiles"):
        Params.model_validate(raw)


def test_params_rejeita_category_alpha_fora_da_grade_de_quantis() -> None:
    valid = load_params(PARAMS_PATH)
    raw = valid.model_dump()
    raw["model"]["quantiles"] = [0.5, 0.8, 0.9, 0.95]
    raw["economics"]["category_alpha"]["bebidas"] = 0.92  # não está na grade acima
    padrao = r"category_alpha\['bebidas'\]=0\.92.*model\.quantiles"
    with pytest.raises(ValidationError, match=padrao):
        Params.model_validate(raw)


def test_params_aceita_alpha_que_bate_com_a_grade_de_quantis() -> None:
    valid = load_params(PARAMS_PATH)
    raw = valid.model_dump()
    raw["model"]["quantiles"] = [0.5, 0.8, 0.9, 0.95]
    raw["economics"]["default_alpha"] = 0.8
    Params.model_validate(raw)  # não levanta

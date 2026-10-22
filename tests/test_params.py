"""Testes do modelo Params e do arquivo config/params.yaml do repositório."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from motor.config import CensuraParams, MissingParamError, Params, load_params

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


# -- mercado_piloto (Sprint 24, etapa 24.1) ------------------------------------


def test_mercado_piloto_carrega_todas_as_chaves() -> None:
    mp = load_params(PARAMS_PATH).mercado_piloto
    assert mp.censura.janela_dias == 28
    assert mp.censura.dias_sem_entrada_antes == 3
    assert mp.censura.alerta_percentual_dias_censurados == 0.15
    assert mp.qualidade.limite_percentual_critico == 0.02
    assert mp.qualidade.cadastro_minimo_completo == 0.90
    assert mp.qualidade.janela_regularidade_dias == 28
    assert mp.qualidade.percentual_dias_com_venda_regular == 0.80
    assert mp.avaliacao.quantis_cobertura == [0.8, 0.9, 0.95]


def test_censura_ativa_e_false_por_padrao() -> None:
    assert load_params(PARAMS_PATH).mercado_piloto.censura.ativa is False


def test_censura_ativa_tem_default_false_quando_omitida() -> None:
    raw = load_params(PARAMS_PATH).model_dump()["mercado_piloto"]["censura"]
    del raw["ativa"]
    assert CensuraParams.model_validate(raw).ativa is False


def test_campos_null_carregam_como_none() -> None:
    mp = load_params(PARAMS_PATH).mercado_piloto
    assert mp.censura.media_minima_por_dia is None
    assert mp.censura.dias_minimos_com_venda is None
    assert mp.avaliacao.janela_teste_semanas is None


@pytest.mark.parametrize(
    ("secao", "campo"),
    [
        ("censura", "media_minima_por_dia"),
        ("censura", "dias_minimos_com_venda"),
        ("avaliacao", "janela_teste_semanas"),
    ],
)
def test_require_campo_null_levanta_erro_com_nome_da_chave(secao: str, campo: str) -> None:
    section = getattr(load_params(PARAMS_PATH).mercado_piloto, secao)
    with pytest.raises(MissingParamError, match=rf"mercado_piloto\.{secao}\.{campo}.*params\.yaml"):
        section.require(campo)


def test_require_campo_preenchido_devolve_o_valor() -> None:
    raw = load_params(PARAMS_PATH).model_dump()
    raw["mercado_piloto"]["censura"]["media_minima_por_dia"] = 2.5  # provisório de teste
    params = Params.model_validate(raw)
    assert params.mercado_piloto.censura.require("media_minima_por_dia") == 2.5


def test_mercado_piloto_rejeita_chave_desconhecida() -> None:
    raw = load_params(PARAMS_PATH).model_dump()
    raw["mercado_piloto"]["censura"]["chave_desconhecida"] = 1
    with pytest.raises(ValidationError, match="chave_desconhecida"):
        Params.model_validate(raw)


def test_mercado_piloto_rejeita_fracao_fora_do_intervalo() -> None:
    raw = load_params(PARAMS_PATH).model_dump()
    raw["mercado_piloto"]["censura"]["alerta_percentual_dias_censurados"] = 1.5
    with pytest.raises(ValidationError, match="alerta_percentual_dias_censurados"):
        Params.model_validate(raw)


def test_quantis_cobertura_fora_de_model_quantiles_e_rejeitado() -> None:
    raw = load_params(PARAMS_PATH).model_dump()
    raw["mercado_piloto"]["avaliacao"]["quantis_cobertura"] = [0.8, 0.93]  # 0.93 não está na grade
    with pytest.raises(ValidationError, match=r"quantis_cobertura.*0\.93.*model\.quantiles"):
        Params.model_validate(raw)


def test_dias_minimos_com_venda_maior_que_janela_dias_e_rejeitado() -> None:
    raw = load_params(PARAMS_PATH).model_dump()
    raw["mercado_piloto"]["censura"]["janela_dias"] = 28
    raw["mercado_piloto"]["censura"]["dias_minimos_com_venda"] = 29
    with pytest.raises(ValidationError, match=r"dias_minimos_com_venda=29.*janela_dias=28"):
        Params.model_validate(raw)


def test_dias_minimos_com_venda_igual_a_janela_dias_e_aceito() -> None:
    raw = load_params(PARAMS_PATH).model_dump()
    raw["mercado_piloto"]["censura"]["dias_minimos_com_venda"] = 28
    Params.model_validate(raw)  # não levanta

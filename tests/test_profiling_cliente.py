"""Testes de `motor.profiling_cliente` (Sprint 22): o perfil da Sprint 2, sobre o dado do cliente.

O número que decide se o dado serve: a proporção do FATURAMENTO em código
genérico ("diversos") -- se for alta, o dado não serve para reposição, e
isso é um resultado, não uma falha.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import polars as pl
import pytest

from motor.io.loaders_cliente import ClientLoadResult, load_client_tables
from motor.profiling_cliente import generic_revenue_verdict, profile_client, render_profile
from tests.cliente_helpers import (
    CLOSED_DAY,
    FIXTURE_DIR,
    PERIOD_END,
    PERIOD_START,
    STORE_CNPJ,
    STORE_ID,
    client_params,
    read_vendas,
)


@pytest.fixture(scope="module")
def result() -> ClientLoadResult:
    return load_client_tables(
        FIXTURE_DIR, params=client_params(), store_id=STORE_ID, store_cnpj=STORE_CNPJ
    )


@pytest.fixture(scope="module")
def profile(result: ClientLoadResult):
    return profile_client(result, params=client_params())


def test_periodo_e_contagens(profile) -> None:
    assert profile.period_start == PERIOD_START
    assert profile.period_end == PERIOD_END
    assert profile.n_calendar_days == 120
    assert profile.n_items == 15
    assert profile.n_suppliers == 3
    assert profile.n_nfe_files == 3


def test_buracos_de_calendario(profile) -> None:
    assert profile.closed_days == (CLOSED_DAY,)


def test_proporcao_de_dias_com_venda(profile, result: ClientLoadResult) -> None:
    com_venda = result.sales.filter(pl.col("is_operating_day"))
    esperado = (com_venda["units_sold"] > 0).sum() / com_venda.height
    assert profile.share_days_with_sale == pytest.approx(esperado)
    assert 0.0 < profile.share_days_with_sale < 1.0


def test_faturamento_em_codigo_generico(profile) -> None:
    vendas = [r for r in read_vendas() if r.kind == "V"]
    total = sum(r.quantity * r.price for r in vendas)
    generico = sum(r.quantity * r.price for r in vendas if r.code == "9999")
    assert profile.generic_revenue_share == pytest.approx(generico / total, rel=1e-12)
    assert generic_revenue_verdict(profile.generic_revenue_share, warn=0.05) == "ok"


@pytest.mark.parametrize(
    ("share", "esperado"),
    [
        (0.0, "ok"),
        (0.05, "ok"),
        (0.0501, "inadequado_para_reposicao"),
        (0.40, "inadequado_para_reposicao"),
    ],
)
def test_veredito_do_codigo_generico(share: float, esperado: str) -> None:
    assert generic_revenue_verdict(share, warn=0.05) == esperado


def test_relatorio_diz_que_nao_serve_quando_o_generico_e_alto(profile) -> None:
    alto = dataclasses.replace(profile, generic_revenue_share=0.40)
    texto = render_profile(alto, params=client_params())
    assert "não serve para reposição" in texto
    assert "40" in texto


def test_relatorio_do_dado_bom_nao_traz_o_alarme(profile) -> None:
    texto = render_profile(profile, params=client_params())
    assert "não serve para reposição" not in texto
    assert str(date(2024, 3, 31)) in texto  # o buraco de calendário aparece

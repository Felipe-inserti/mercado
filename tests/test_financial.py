"""Testes de `motor.metrics.financial` (Sprint 8).

O teste de aceitação (`test_cenario_deterministico_bate_com_calculo_manual`)
é a condição de pronto da sprint: os valores esperados foram derivados à mão
no desenho da sprint, usando o resultado JÁ PROVADO pela Sprint 6 --
`on_hand_end` médio em regime permanente é `d x (R+1)/2`, não a aproximação
contínua `d x R/2`. Ver a derivação completa no histórico da sprint.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta

import polars as pl
import pytest

from motor.metrics.financial import (
    MissingItemEconomicsError,
    build_item_economics,
    compute_financial_metrics,
    compute_portfolio_metrics,
    daily_net_margin,
)
from motor.simulator.engine import DailyEvent
from tests.fakes import build_analytic_scenario

# -- build_item_economics -----------------------------------------------


def test_build_item_economics_mapeia_categoria_e_aplica_default() -> None:
    items = pl.DataFrame(
        {"item_id": ["A", "B", "C"], "category": ["GROCERY I", "BEVERAGES", "SEM_MAPA"]}
    )
    result = build_item_economics(
        items,
        category_margin_pct={"GROCERY I": 0.18, "BEVERAGES": 0.30},
        default_margin_pct=0.25,
        uniform_unit_price=10.0,
    )
    by_item = {row["item_id"]: row for row in result.to_dicts()}

    assert by_item["A"]["margin_pct"] == pytest.approx(0.18)
    assert by_item["B"]["margin_pct"] == pytest.approx(0.30)
    assert by_item["C"]["margin_pct"] == pytest.approx(0.25)  # sem mapa -> default
    assert all(row["price"] == pytest.approx(10.0) for row in result.to_dicts())


def test_build_item_economics_cost_deriva_de_margin_pct() -> None:
    items = pl.DataFrame({"item_id": ["A"], "category": ["GROCERY I"]})
    result = build_item_economics(
        items,
        category_margin_pct={"GROCERY I": 0.20},
        default_margin_pct=0.25,
        uniform_unit_price=10.0,
    )
    row = result.to_dicts()[0]
    assert row["cost"] == pytest.approx(8.0)  # 10 * (1 - 0.20)


# -- eventos sintéticos para os testes de métricas ---------------------------

D0 = date(2026, 1, 1)


def _events_df(item_id: str, events: list[object]) -> pl.DataFrame:
    rows = [asdict(e) for e in events]  # type: ignore[call-overload]
    return pl.DataFrame(rows).with_columns(pl.lit(item_id).alias("item_id"))


def _economics_df(*, item_id: str, price: float, margin_pct: float) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "item_id": [item_id],
            "price": [price],
            "cost": [price * (1 - margin_pct)],
            "margin_pct": [margin_pct],
        }
    )


# -- cenário determinístico (Sprint 6) -- condição de pronto da sprint ------

_D = 10.0
_L = 3
_R = 7
_WARMUP_CYCLES = 4
_MEASURED_CYCLES = 6
_PRICE = 10.0
_MARGIN_PCT = 0.20
_COST = _PRICE * (1 - _MARGIN_PCT)  # 8.0


def _rodar_cenario_deterministico() -> tuple[pl.DataFrame, pl.DataFrame, date]:
    total_days = (_WARMUP_CYCLES + _MEASURED_CYCLES) * _R
    scenario = build_analytic_scenario(
        daily_demand=_D, lead_time_days=_L, review_period_days=_R, total_days=total_days, start=D0
    )
    eventos = scenario.simulator.run(scenario.start, scenario.end)
    events = _events_df("ITEM_TESTE", eventos)
    economics = _economics_df(item_id="ITEM_TESTE", price=_PRICE, margin_pct=_MARGIN_PCT)
    evaluation_start = D0 + timedelta(days=_WARMUP_CYCLES * _R)
    return events, economics, evaluation_start


def test_cenario_deterministico_bate_com_calculo_manual() -> None:
    events, economics, evaluation_start = _rodar_cenario_deterministico()

    result = compute_financial_metrics(
        events, economics, evaluation_start=evaluation_start, capital_cost_annual=0.15
    )
    assert result.height == 1
    row = result.to_dicts()[0]

    # Valores derivados à mão (ver docstring do módulo e histórico da sprint):
    # on_hand médio em regime permanente = d*(R+1)/2 = 10*8/2 = 40.0 (Sprint 6,
    # não d*R/2 -- essa é a aproximação contínua, não o resultado do loop discreto)
    assert row["capital_medio_rs"] == pytest.approx(320.0)  # 40.0 * 8.0
    assert row["margem_realizada_rs"] == pytest.approx(840.0)  # 42*10*(10-8)
    assert row["ruptura_rs"] == pytest.approx(0.0)
    assert row["perda_rs"] == pytest.approx(0.0)
    assert row["nivel_servico"] == pytest.approx(1.0)
    assert row["decision_metric"] == pytest.approx(2.625)  # 840/320
    assert row["giro_anualizado"] == pytest.approx(91.25)  # 730/(7+1)
    assert row["carrying_cost_rs"] == pytest.approx(5.523, abs=1e-3)  # 320*42*0.15/365


def test_cenario_deterministico_portfolio_bate_com_o_mesmo_calculo_de_um_item_so() -> None:
    """Com um único item, o agregado do portfólio tem que reproduzir
    exatamente os mesmos números do teste por item acima -- é o caso trivial
    da agregação (N=1 item)."""
    events, economics, evaluation_start = _rodar_cenario_deterministico()

    portfolio = compute_portfolio_metrics(
        events, economics, evaluation_start=evaluation_start, capital_cost_annual=0.15
    )

    assert portfolio.capital_medio_rs == pytest.approx(320.0)
    assert portfolio.margem_realizada_rs == pytest.approx(840.0)
    assert portfolio.ruptura_rs == pytest.approx(0.0)
    assert portfolio.perda_rs == pytest.approx(0.0)
    assert portfolio.nivel_servico == pytest.approx(1.0)
    assert portfolio.decision_metric == pytest.approx(2.625)
    assert portfolio.giro_anualizado == pytest.approx(91.25)
    assert portfolio.carrying_cost_rs == pytest.approx(5.523, abs=1e-3)


# -- invariância de escala ---------------------------------------------------


@pytest.mark.parametrize(
    ("daily_demand", "price", "margin_pct"),
    [(10.0, 10.0, 0.20), (25.0, 3.0, 0.35), (4.0, 100.0, 0.05)],
)
def test_giro_anualizado_independe_de_d_price_cost(
    daily_demand: float, price: float, margin_pct: float
) -> None:
    """730 / (R+1) é uma fórmula fechada: não deve mudar com `daily_demand`,
    `price` nem `margin_pct` -- é a checagem de escala mais forte que temos
    (ver docstring do módulo)."""
    total_days = (_WARMUP_CYCLES + _MEASURED_CYCLES) * _R
    scenario = build_analytic_scenario(
        daily_demand=daily_demand,
        lead_time_days=_L,
        review_period_days=_R,
        total_days=total_days,
        start=D0,
    )
    eventos = scenario.simulator.run(scenario.start, scenario.end)
    events = _events_df("X", eventos)
    economics = _economics_df(item_id="X", price=price, margin_pct=margin_pct)
    evaluation_start = D0 + timedelta(days=_WARMUP_CYCLES * _R)

    result = compute_financial_metrics(
        events, economics, evaluation_start=evaluation_start, capital_cost_annual=0.15
    )
    giro = result.to_dicts()[0]["giro_anualizado"]
    assert giro == pytest.approx(730.0 / (_R + 1))


def test_decision_metric_e_giro_invariantes_a_price_margem_realizada_e_capital_escalam() -> None:
    """`price` uniforme cancela em `decision_metric`/`giro_anualizado`, mas
    NÃO em `margem_realizada_rs`/`capital_medio_rs` isolados -- os dois
    escalam linearmente com `price` (ver prova algébrica na docstring do
    módulo)."""
    events, economics_10, evaluation_start = _rodar_cenario_deterministico()
    economics_100 = _economics_df(item_id="ITEM_TESTE", price=100.0, margin_pct=_MARGIN_PCT)

    r10 = compute_financial_metrics(
        events, economics_10, evaluation_start=evaluation_start, capital_cost_annual=0.15
    ).to_dicts()[0]
    r100 = compute_financial_metrics(
        events, economics_100, evaluation_start=evaluation_start, capital_cost_annual=0.15
    ).to_dicts()[0]

    assert r10["decision_metric"] == pytest.approx(r100["decision_metric"])
    assert r10["giro_anualizado"] == pytest.approx(r100["giro_anualizado"])
    assert r10["nivel_servico"] == pytest.approx(r100["nivel_servico"])

    assert r100["margem_realizada_rs"] == pytest.approx(r10["margem_realizada_rs"] * 10)
    assert r100["capital_medio_rs"] == pytest.approx(r10["capital_medio_rs"] * 10)


# -- portfólio com múltiplos itens: razão de somas, não soma de razões ------


def test_compute_portfolio_metrics_agrega_por_soma_nao_por_media_de_razoes() -> None:
    total_days = (_WARMUP_CYCLES + _MEASURED_CYCLES) * _R
    evaluation_start = D0 + timedelta(days=_WARMUP_CYCLES * _R)

    scenario_a = build_analytic_scenario(
        daily_demand=10.0, lead_time_days=_L, review_period_days=_R, total_days=total_days, start=D0
    )
    scenario_b = build_analytic_scenario(
        daily_demand=20.0, lead_time_days=_L, review_period_days=_R, total_days=total_days, start=D0
    )
    events = pl.concat(
        [
            _events_df("A", scenario_a.simulator.run(scenario_a.start, scenario_a.end)),
            _events_df("B", scenario_b.simulator.run(scenario_b.start, scenario_b.end)),
        ]
    )
    economics = pl.concat(
        [
            _economics_df(item_id="A", price=10.0, margin_pct=0.20),
            _economics_df(item_id="B", price=10.0, margin_pct=0.20),
        ]
    )

    portfolio = compute_portfolio_metrics(
        events, economics, evaluation_start=evaluation_start, capital_cost_annual=0.15
    )
    por_item = compute_financial_metrics(
        events, economics, evaluation_start=evaluation_start, capital_cost_annual=0.15
    )

    # nivel_servico == 1.0 nos dois itens (regime permanente) -> soma/soma == 1.0 também
    assert portfolio.nivel_servico == pytest.approx(1.0)
    # capital_medio do portfólio é a SOMA dos capitais médios por item (linearidade da
    # média sobre os MESMOS dias em ambos) -- checagem direta, não a definição usada
    # internamente (que soma por dia antes de tirar a média).
    assert portfolio.capital_medio_rs == pytest.approx(por_item["capital_medio_rs"].sum())
    assert portfolio.margem_realizada_rs == pytest.approx(por_item["margem_realizada_rs"].sum())


# -- erro alto quando falta economia de um item -----------------------------


def test_item_sem_economics_levanta_erro_explicito() -> None:
    events, _, evaluation_start = _rodar_cenario_deterministico()
    economics_de_outro_item = _economics_df(item_id="OUTRO_ITEM", price=10.0, margin_pct=0.2)

    with pytest.raises(MissingItemEconomicsError, match="ITEM_TESTE"):
        compute_financial_metrics(
            events,
            economics_de_outro_item,
            evaluation_start=evaluation_start,
            capital_cost_annual=0.15,
        )


# -- filtro de warmup interno -------------------------------------------


def test_evaluation_start_filtra_o_warmup_internamente() -> None:
    """Sem o filtro, o aquecimento (estoque inicial vazio, ruptura real)
    contaminaria `nivel_servico` -- CLAUDE.md, seção 6."""
    events, economics, evaluation_start = _rodar_cenario_deterministico()

    com_filtro = compute_financial_metrics(
        events, economics, evaluation_start=evaluation_start, capital_cost_annual=0.15
    ).to_dicts()[0]
    sem_filtro = compute_financial_metrics(
        events, economics, evaluation_start=D0, capital_cost_annual=0.15
    ).to_dicts()[0]

    assert com_filtro["nivel_servico"] == pytest.approx(1.0)
    assert sem_filtro["nivel_servico"] < 1.0  # aquecimento tem ruptura real


# -- daily_net_margin (Sprint 15) ----------------------------------------


def test_daily_net_margin_e_margem_menos_perda_por_dia() -> None:
    """Dois dias, um item: dia 1 só vende (sem perda), dia 2 só expira (sem
    venda) -- `net_margin_rs` tem que refletir os dois efeitos, por dia,
    sem misturar um no outro."""
    events = [
        DailyEvent(
            day=D0,
            on_hand_start=10.0,
            in_transit_start=0.0,
            demand=5.0,
            sold=5.0,
            unmet_demand=0.0,
            expired=0.0,
            order_placed=None,
            on_hand_end=5.0,
            in_transit_end=0.0,
        ),
        DailyEvent(
            day=D0 + timedelta(days=1),
            on_hand_start=5.0,
            in_transit_start=0.0,
            demand=0.0,
            sold=0.0,
            unmet_demand=0.0,
            expired=5.0,
            order_placed=None,
            on_hand_end=0.0,
            in_transit_end=0.0,
        ),
    ]
    events_df = _events_df("A", events)
    economics = _economics_df(item_id="A", price=_PRICE, margin_pct=_MARGIN_PCT)

    result = daily_net_margin(events_df, economics, evaluation_start=D0).sort("day")
    rows = result.to_dicts()

    assert rows[0]["day"] == D0
    assert rows[0]["net_margin_rs"] == pytest.approx(5.0 * (_PRICE - _COST))  # só margem
    assert rows[1]["day"] == D0 + timedelta(days=1)
    assert rows[1]["net_margin_rs"] == pytest.approx(-5.0 * _COST)  # só perda


def test_daily_net_margin_soma_entre_itens_no_mesmo_dia() -> None:
    evento_a = DailyEvent(
        day=D0,
        on_hand_start=10.0,
        in_transit_start=0.0,
        demand=5.0,
        sold=5.0,
        unmet_demand=0.0,
        expired=0.0,
        order_placed=None,
        on_hand_end=5.0,
        in_transit_end=0.0,
    )
    evento_b = DailyEvent(
        day=D0,
        on_hand_start=10.0,
        in_transit_start=0.0,
        demand=3.0,
        sold=3.0,
        unmet_demand=0.0,
        expired=0.0,
        order_placed=None,
        on_hand_end=7.0,
        in_transit_end=0.0,
    )
    events_df = pl.concat([_events_df("A", [evento_a]), _events_df("B", [evento_b])])
    economics = pl.concat(
        [
            _economics_df(item_id="A", price=_PRICE, margin_pct=_MARGIN_PCT),
            _economics_df(item_id="B", price=_PRICE, margin_pct=_MARGIN_PCT),
        ]
    )

    result = daily_net_margin(events_df, economics, evaluation_start=D0)
    assert result.height == 1  # um dia só
    assert result["net_margin_rs"][0] == pytest.approx((5.0 + 3.0) * (_PRICE - _COST))

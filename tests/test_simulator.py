"""Testes do loop diário do simulador (`motor.simulator.engine.Simulator`).

Previsão e política aqui são de mentira (`tests/fakes.py`): `ConstantForecaster`
e `OrderUpToPolicy`. O objetivo desta sprint não é previsão nem política reais
-- é provar que o LOOP (ordem dos passos, posição com pipeline, calendário de
revisão, corte de lookahead, FEFO/expiração dentro do dia) está correto.

Se o teste de aceitação (`test_regime_permanente_*`) não fechar, os demais não
importam -- CLAUDE.md, seção 6.
"""

from datetime import date, timedelta

import polars as pl
import pytest

from motor.inventory import InventoryState
from motor.simulator.engine import Simulator, _in_transit, review_every_n_days, review_on_weekdays
from tests.fakes import ConstantForecaster, OrderUpToPolicy, SpyForecaster, build_analytic_scenario

D0 = date(2026, 1, 1)


def _dias(n: int) -> date:
    return D0 + timedelta(days=n)


# -- _in_transit -----------------------------------------------------------


def test_in_transit_e_posicao_menos_em_maos() -> None:
    estado = InventoryState(data_inicial=D0)
    estado.receber(5.0, validade=None)
    estado.agendar_pedido(8.0, data_chegada=_dias(3), validade=None)
    assert _in_transit(estado) == estado.posicao() - estado.em_maos()
    assert _in_transit(estado) == 8.0


# -- calendário de revisão ---------------------------------------------------


def test_review_every_n_days_marca_apenas_multiplos_do_periodo() -> None:
    e_dia_de_revisao = review_every_n_days(reference=D0, period_days=7)
    assert e_dia_de_revisao(D0)
    assert not e_dia_de_revisao(_dias(1))
    assert e_dia_de_revisao(_dias(7))
    assert e_dia_de_revisao(_dias(14))


def test_review_every_n_days_com_periodo_nao_positivo_levanta_value_error() -> None:
    with pytest.raises(ValueError, match="period_days deve ser positivo"):
        review_every_n_days(reference=D0, period_days=0)


def test_review_on_weekdays_marca_dias_da_semana_configurados() -> None:
    # D0 = 2026-01-01 é uma quinta (isoweekday 4)
    e_dia_de_revisao = review_on_weekdays([1, 4])  # segunda e quinta
    assert e_dia_de_revisao(D0)  # quinta
    assert not e_dia_de_revisao(_dias(1))  # sexta
    assert e_dia_de_revisao(_dias(4))  # segunda seguinte


# -- teste de aceitação: regime permanente ----------------------------------
#
# Demanda constante d, lead time L, revisão a cada R dias, política que enche
# até S = d x (L + R). Usamos d=10, L=3, R=7 -> S=100, horizon=L+R=10.
#
# Derivação (regime permanente, sem ruptura):
#
# 1. Posição na revisão. Entre duas revisões consecutivas, a posição só cai
#    por consumo (nunca por vencimento nesta cena: sem shelf life). Em regime
#    permanente, cada dia vende a demanda cheia (sem ruptura), então a
#    posição cai exatamente d por dia. Na revisão seguinte, R dias depois,
#    a posição caiu d*R a partir do S deixado pela revisão anterior:
#        posição_na_revisão = S - d*R = d*(L+R) - d*R = d*L
#
# 2. Em trânsito na revisão é zero. Como L < R, o pedido da revisão anterior
#    (feito R dias atrás) já chegou há R-L dias -- não há pedido em aberto no
#    momento da revisão. Logo em_maos_na_revisão = posição_na_revisão = d*L.
#
# 3. Pedido em regime permanente. pedido = S - posição = S - d*L = d*R.
#    Cada revisão pede exatamente d*R -- não repete o que já chegou.
#
# 4. Trajetória do estoque em mãos dentro do ciclo. O pedido feito na revisão
#    chega L dias depois. Do dia da revisão até o dia anterior à chegada, o
#    estoque só declina (R-1 dias de declínio depois do próprio dia da
#    revisão, que já refletiu o consumo daquele dia):
#        trough = em_maos_na_revisão - d*(L-1) = d*L - d*(L-1) = d
#    No dia da chegada, o recebimento entra ANTES da demanda do mesmo dia
#    (CLAUDE.md, seção 6): em_maos sobe por d*R e desce por d no mesmo dia:
#        peak = trough + d*R - d = d + d*(R-1) = d*R
#    Do dia seguinte à chegada até a revisão seguinte (R-1 dias), o estoque
#    declina d por dia, voltando ao mesmo padrão.
#
# 5. Estoque médio. Ao longo de qualquer janela de R dias consecutivos em
#    regime permanente (uma revisão completa), os valores de em_maos ao
#    FINAL do dia formam uma sequência aritmética de R termos, de peak=d*R
#    até trough=d, decrescendo d por dia:
#        média = (peak + trough) / 2 = (d*R + d) / 2 = d*(R+1)/2
#    NÃO é d*R/2: essa seria a aproximação contínua, que ignora que o dia da
#    chegada também consome uma unidade de demanda antes do próximo ciclo
#    recomeçar. O modelo discreto (recebimento antes da demanda do mesmo dia,
#    exigido pela ordem fixa do loop) desloca o resultado em exatamente d/2
#    para cima -- `AnalyticScenario.expected_average_on_hand` documenta o
#    mesmo valor.
#
# 6. Nível de serviço. Em regime permanente trough = d > 0 sempre (para
#    L >= 1): o estoque nunca chega a zero, logo toda a demanda é atendida
#    -- nível de serviço = 1.0 exatamente.
#
# O período de aquecimento (antes do regime permanente) tem ruptura real,
# porque o estoque parte vazio: por isso o teste descarta os primeiros ciclos
# de revisão antes de medir.

_D = 10.0
_L = 3
_R = 7
_WARMUP_CYCLES = 4
_MEASURED_CYCLES = 6


def _rodar_regime_permanente(*, slack: float = 0.0) -> tuple[list, float, float]:
    total_days = (_WARMUP_CYCLES + _MEASURED_CYCLES) * _R
    scenario = build_analytic_scenario(
        daily_demand=_D,
        lead_time_days=_L,
        review_period_days=_R,
        total_days=total_days,
        slack=slack,
        start=D0,
    )
    eventos = scenario.simulator.run(scenario.start, scenario.end)

    warmup_days = _WARMUP_CYCLES * _R
    medidos = eventos[warmup_days:]
    assert len(medidos) == _MEASURED_CYCLES * _R

    media_em_maos = sum(e.on_hand_end for e in medidos) / len(medidos)
    nivel_servico = sum(e.sold for e in medidos) / sum(e.demand for e in medidos)
    return medidos, media_em_maos, nivel_servico


def test_regime_permanente_estoque_medio_e_nivel_de_servico() -> None:
    medidos, media_em_maos, nivel_servico = _rodar_regime_permanente()

    esperado = _D * (_R + 1) / 2  # ver derivação acima
    assert media_em_maos == pytest.approx(esperado)
    assert nivel_servico == pytest.approx(1.0)

    # cada revisão medida pede exatamente d*R -- nunca repete o que já chegou
    pedidos_revisao = [e.order_placed for e in medidos if e.order_placed is not None]
    assert pedidos_revisao  # houve ao menos uma revisão na janela medida
    for pedido in pedidos_revisao:
        assert pedido == pytest.approx(_D * _R)


def test_regime_permanente_folga_desloca_media_sem_mudar_pedido() -> None:
    """S + f: a folga aparece como deslocamento no estoque médio (+f exato),
    não como mudança de escala -- o pedido por revisão continua d*R."""
    _, media_sem_folga, _ = _rodar_regime_permanente()
    folga = 25.0
    medidos_com_folga, media_com_folga, nivel_servico_com_folga = _rodar_regime_permanente(
        slack=folga
    )

    assert media_com_folga == pytest.approx(media_sem_folga + folga)
    assert nivel_servico_com_folga == pytest.approx(1.0)
    for evento in medidos_com_folga:
        if evento.order_placed is not None:
            assert evento.order_placed == pytest.approx(_D * _R)


# -- demanda não atendida desaparece -----------------------------------------


def test_demanda_nao_atendida_nunca_e_recuperada_depois() -> None:
    """No aquecimento (estoque parte vazio), há ruptura real -- mas o total
    vendido nunca excede o total demandado, e o total não atendido nunca
    reaparece como venda num dia futuro (não existe backorder)."""
    total_days = 4 * _R
    scenario = build_analytic_scenario(
        daily_demand=_D,
        lead_time_days=_L,
        review_period_days=_R,
        total_days=total_days,
        start=D0,
    )
    eventos = scenario.simulator.run(scenario.start, scenario.end)

    for evento in eventos:
        assert evento.sold <= evento.demand
        assert evento.sold + evento.unmet_demand == pytest.approx(evento.demand)

    # balanço global: tudo que chegou (recebido ou ainda em trânsito ao
    # final) foi vendido, perdido por vencimento, ou está em mãos/trânsito
    # no fim -- nada desaparece sem explicação, e nada "sobra" de um dia
    # não atendido para vender depois além do que a política já decidiu.
    total_pedido = sum(e.order_placed for e in eventos if e.order_placed is not None)
    total_vendido = sum(e.sold for e in eventos)
    total_perdido = sum(e.expired for e in eventos)
    em_maos_final = eventos[-1].on_hand_end
    em_transito_final = eventos[-1].in_transit_end
    saldo_final = total_vendido + total_perdido + em_maos_final + em_transito_final
    assert total_pedido == pytest.approx(saldo_final)


# -- posição inclui em trânsito ----------------------------------------------


def test_segunda_revisao_nao_repete_pedido_com_pipeline_em_aberto() -> None:
    """Lead time (10) maior que o período de revisão (5): na segunda
    revisão, o pedido da primeira ainda não chegou. Se o simulador ignorasse
    o em trânsito, pediria S de novo -- o bug clássico do pipeline ignorado."""
    d, lead_time_days, review_period_days = 10.0, 10, 5
    s = d * (lead_time_days + review_period_days)  # 150.0
    total_days = 2 * review_period_days  # duas revisões: dia 0 e dia 5

    dates = [D0 + timedelta(days=i) for i in range(total_days)]
    demand_table = pl.DataFrame({"date": dates, "units_sold": [d] * total_days})

    estado = InventoryState(data_inicial=D0 - timedelta(days=1))
    simulador = Simulator(
        estado,
        ConstantForecaster(d),
        OrderUpToPolicy(s),
        demand_table,
        lead_time_days=lead_time_days,
        horizon_days=lead_time_days + review_period_days,
        quantiles=[0.5],
        is_review_day=review_every_n_days(reference=D0, period_days=review_period_days),
        shelf_life_from_arrival_days=None,
    )
    eventos = simulador.run(D0, D0 + timedelta(days=total_days - 1))

    primeira_revisao, segunda_revisao = eventos[0], eventos[review_period_days]
    assert primeira_revisao.order_placed == pytest.approx(s)  # estoque partiu vazio
    assert segunda_revisao.order_placed == pytest.approx(0.0)  # tudo já está em trânsito


# -- previsão sem lookahead ---------------------------------------------------


def test_forecaster_nunca_recebe_historico_com_data_maior_ou_igual_ao_as_of() -> None:
    d, lead_time_days, review_period_days = 10.0, 2, 5
    total_days = 2 * review_period_days  # duas revisões: dia 0 e dia 5
    dates = [D0 + timedelta(days=i) for i in range(total_days)]
    demand_table = pl.DataFrame({"date": dates, "units_sold": [d] * total_days})

    espiao = SpyForecaster(demand_per_day=d)
    estado = InventoryState(data_inicial=D0 - timedelta(days=1))
    simulador = Simulator(
        estado,
        espiao,
        OrderUpToPolicy(d * (lead_time_days + review_period_days)),
        demand_table,
        lead_time_days=lead_time_days,
        horizon_days=lead_time_days + review_period_days,
        quantiles=[0.5],
        is_review_day=review_every_n_days(reference=D0, period_days=review_period_days),
        shelf_life_from_arrival_days=None,
    )
    simulador.run(D0, D0 + timedelta(days=total_days - 1))  # não deve levantar AssertionError

    assert espiao.as_of_calls == [D0, D0 + timedelta(days=review_period_days)]
    # o histórico visto na segunda revisão vai exatamente até o dia anterior -- nem um dia menos
    assert espiao.max_history_date_seen == D0 + timedelta(days=review_period_days - 1)


# -- recebimento antes da demanda do mesmo dia -------------------------------


def test_recebimento_do_dia_atende_a_demanda_do_mesmo_dia() -> None:
    """Lead time = 1: o pedido feito na revisão do dia 0 chega no dia 1 e
    atende, no mesmo dia, a demanda que encontraria o estoque vazio."""
    d, lead_time_days, review_period_days = 10.0, 1, 5
    s = d * (lead_time_days + review_period_days)
    total_days = review_period_days
    dates = [D0 + timedelta(days=i) for i in range(total_days)]
    demand_table = pl.DataFrame({"date": dates, "units_sold": [d] * total_days})

    estado = InventoryState(data_inicial=D0 - timedelta(days=1))
    simulador = Simulator(
        estado,
        ConstantForecaster(d),
        OrderUpToPolicy(s),
        demand_table,
        lead_time_days=lead_time_days,
        horizon_days=lead_time_days + review_period_days,
        quantiles=[0.5],
        is_review_day=review_every_n_days(reference=D0, period_days=review_period_days),
        shelf_life_from_arrival_days=None,
    )
    eventos = simulador.run(D0, D0 + timedelta(days=total_days - 1))

    dia_da_chegada = eventos[1]  # D0 + 1: chegada do pedido feito em D0
    assert dia_da_chegada.on_hand_start == 0.0  # nada em mãos antes do recebimento
    assert dia_da_chegada.sold == d  # ainda assim vende a demanda cheia
    assert dia_da_chegada.unmet_demand == 0.0


# -- expiração depois do atendimento -----------------------------------------


def test_item_que_vence_no_dia_ainda_vende_no_mesmo_dia() -> None:
    """Lote que chega e cuja validade é o próprio dia de chegada ainda é
    vendido nesse dia -- só expira, se sobrar, no dia seguinte (FEFO/validade
    já testados em `InventoryState`; aqui confirmamos a ORDEM dentro do
    Simulator: atendimento sempre antes de expiração)."""
    d, lead_time_days, review_period_days = 4.0, 1, 5
    s = d * (lead_time_days + review_period_days)
    total_days = review_period_days + 1
    dates = [D0 + timedelta(days=i) for i in range(total_days)]
    demand_table = pl.DataFrame({"date": dates, "units_sold": [d] * total_days})

    estado = InventoryState(data_inicial=D0 - timedelta(days=1))
    simulador = Simulator(
        estado,
        ConstantForecaster(d),
        OrderUpToPolicy(s),
        demand_table,
        lead_time_days=lead_time_days,
        horizon_days=lead_time_days + review_period_days,
        quantiles=[0.5],
        is_review_day=review_every_n_days(reference=D0, period_days=review_period_days),
        shelf_life_from_arrival_days=0,  # validade = data de chegada -- premissa declarada
    )
    eventos = simulador.run(D0, D0 + timedelta(days=total_days - 1))

    dia_da_chegada = eventos[1]  # D0 + 1: chegada do lote com validade == D0 + 1
    assert dia_da_chegada.sold == d  # vendido no mesmo dia da validade, não perdido
    assert dia_da_chegada.expired == 0.0  # validade == data corrente ainda não é vencido

    dia_seguinte = eventos[2]  # D0 + 2: validade (D0+1) agora é passado
    assert dia_seguinte.expired == pytest.approx(s - d - d)  # sobra do lote, vencida

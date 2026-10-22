"""Testes de `motor.features.censoring` (Sprint 24, etapa 24.4b).

Limiares provisórios, SÓ de teste (o `params.yaml` os mantém `null`):
janela de 7 dias, média mínima 1,0/dia, mínimo de 3 dias com venda, 3 dias
sem entrada antes.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from motor.config import CensuraParams, MissingParamError, load_params
from motor.features.censoring import (
    REASON_ENTRIES_UNKNOWN,
    REASON_NO_RECENT_ENTRY,
    censoring_summary,
    drop_censored,
    flag_probable_stockout,
    flags_for_item,
)
from motor.inventory import InventoryState
from motor.policy.base import DecisionContext
from motor.reporting.purchase_list import _decide_item
from motor.simulator.engine import DailyEvent, Simulator, review_every_n_days

D0 = date(2026, 3, 2)


def _params(**overrides: object) -> CensuraParams:
    base: dict[str, object] = {
        "ativa": True,
        "janela_dias": 7,
        "media_minima_por_dia": 1.0,
        "dias_minimos_com_venda": 3,
        "dias_sem_entrada_antes": 3,
        "alerta_percentual_dias_censurados": 0.15,
    }
    return CensuraParams(**{**base, **overrides})  # type: ignore[arg-type]


def _sales(units: list[float], item_id: str = "A") -> pl.DataFrame:
    return pl.DataFrame(
        {
            "store_id": ["1"] * len(units),
            "item_id": [item_id] * len(units),
            "date": [D0 + timedelta(days=i) for i in range(len(units))],
            "units_sold": units,
        }
    )


def _entries(received: list[date]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "store_id": ["1"] * len(received),
            "item_id": ["A"] * len(received),
            "received_date": received,
            "quantity": [10.0] * len(received),
        },
        schema={
            "store_id": pl.String,
            "item_id": pl.String,
            "received_date": pl.Date,
            "quantity": pl.Float64,
        },
    )


def _marked_days(flags: pl.DataFrame) -> list[date]:
    return flags.filter(pl.col("is_censored"))["date"].to_list()


# item regular: 5/dia por 10 dias; zero no dia 10 (D0 + 10)
_REGULAR = [5.0] * 10 + [0.0] + [5.0]


def test_item_regular_zero_sem_entrada_perto_e_marcado() -> None:
    flags = flag_probable_stockout(_sales(_REGULAR), _entries([D0 - timedelta(days=30)]), _params())
    assert _marked_days(flags) == [D0 + timedelta(days=10)]
    reasons = flags.filter(pl.col("is_censored"))["reason"].to_list()
    assert reasons == [REASON_NO_RECENT_ENTRY]
    assert flags.columns == ["store_id", "item_id", "date", "is_censored", "reason"]
    assert flags.height == len(_REGULAR)


@pytest.mark.parametrize("days_before_zero", [1, 2, 3])
def test_mesmo_zero_com_entrada_nos_3_dias_anteriores_nao_e_marcado(days_before_zero: int) -> None:
    received = D0 + timedelta(days=10 - days_before_zero)
    flags = flag_probable_stockout(_sales(_REGULAR), _entries([received]), _params())
    assert _marked_days(flags) == []


def test_entrada_4_dias_antes_ja_nao_protege_o_zero() -> None:
    received = D0 + timedelta(days=10 - 4)
    flags = flag_probable_stockout(_sales(_REGULAR), _entries([received]), _params())
    assert _marked_days(flags) == [D0 + timedelta(days=10)]


def test_item_intermitente_nao_tem_dia_marcado() -> None:
    # 7 dias anteriores a qualquer zero têm no máximo 2 dias com venda e média < 1.
    units = [0.0, 0.0, 5.0, 0.0, 0.0, 0.0, 5.0, 0.0, 0.0, 0.0, 5.0, 0.0, 0.0, 0.0]
    flags = flag_probable_stockout(_sales(units), _entries([]), _params())
    assert _marked_days(flags) == []


def test_entries_none_aplica_a_regra_sem_a_condicao_de_entrada_e_diz_isso() -> None:
    flags = flag_probable_stockout(_sales(_REGULAR), None, _params())
    marked = flags.filter(pl.col("is_censored"))
    assert marked["date"].to_list() == [D0 + timedelta(days=10)]
    assert marked["reason"].to_list() == [REASON_ENTRIES_UNKNOWN]


def test_janela_olha_so_o_passado_do_dia() -> None:
    # Mudar o futuro (depois do zero) não muda a marcação do zero.
    base = flag_probable_stockout(_sales(_REGULAR), None, _params())
    altered = flag_probable_stockout(_sales([*_REGULAR[:11], 999.0]), None, _params())
    day = D0 + timedelta(days=10)
    assert (
        base.filter(pl.col("date") == day)["is_censored"].to_list()
        == altered.filter(pl.col("date") == day)["is_censored"].to_list()
        == [True]
    )


def test_limiar_nulo_no_params_falha_com_o_nome_da_chave() -> None:
    with pytest.raises(MissingParamError, match="media_minima_por_dia"):
        flag_probable_stockout(_sales(_REGULAR), None, _params(media_minima_por_dia=None))


def test_flags_vazias_drop_censored_devolve_o_historico_identico() -> None:
    history = _sales(_REGULAR).select("date", "units_sold")
    empty = pl.DataFrame(
        schema={"date": pl.Date, "is_censored": pl.Boolean},
    )
    assert drop_censored(history, empty).equals(history)
    none_marked = flag_probable_stockout(_sales([5.0] * 12), None, _params())
    assert drop_censored(history, none_marked).equals(history)


def test_drop_censored_remove_so_as_linhas_marcadas_por_par_e_por_painel() -> None:
    sales = pl.concat([_sales(_REGULAR, "A"), _sales([5.0] * 12, "B")])
    flags = flag_probable_stockout(sales, None, _params())
    marked_day = D0 + timedelta(days=10)

    panel = drop_censored(sales, flags)
    assert panel.height == sales.height - 1
    assert panel.filter((pl.col("item_id") == "A") & (pl.col("date") == marked_day)).height == 0
    assert panel.filter(pl.col("item_id") == "B").height == 12

    pair = _sales(_REGULAR, "A").select("date", "units_sold")
    pair_flags = flags_for_item(flags, "1", "A")
    assert drop_censored(pair, pair_flags).height == len(_REGULAR) - 1


def test_censoring_summary_por_item_e_total_com_alerta() -> None:
    sales = pl.concat([_sales(_REGULAR, "A"), _sales([5.0] * 12, "B")])
    flags = flag_probable_stockout(sales, None, _params())
    summary = censoring_summary(flags, _params())
    rows = {r["item_id"]: r for r in summary.iter_rows(named=True)}
    assert rows["A"]["censored_days"] == 1
    assert rows["A"]["days"] == 12
    assert rows["B"]["censored_days"] == 0
    assert rows["TOTAL"]["days"] == 24
    assert rows["TOTAL"]["censored_days"] == 1
    # 1/12 = 8,3% < 15%: sem alerta; com limiar de 5% o item A alerta, B não.
    assert rows["A"]["alert"] is False
    strict = censoring_summary(flags, _params(alerta_percentual_dias_censurados=0.05))
    strict_rows = {r["item_id"]: r for r in strict.iter_rows(named=True)}
    assert strict_rows["A"]["alert"] is True
    assert strict_rows["B"]["alert"] is False


# --------------------------------------------------------------------------
# 24.4c -- pontos de chamada
# --------------------------------------------------------------------------


class _RecordingMeanForecaster:
    """Previsão dependente do histórico: média diária do que recebeu x horizonte.
    Guarda as datas que viu em cada `fit`, para provar o que foi filtrado."""

    def __init__(self) -> None:
        self.seen: dict[date, list[date]] = {}
        self._mean = 0.0

    def fit(self, history: pl.DataFrame, as_of: date) -> None:
        self.seen[as_of] = history["date"].to_list()
        self._mean = float(history["units_sold"].mean()) if history.height else 0.0  # type: ignore[arg-type]

    def predict_quantiles(self, _as_of: date, horizon: int, quantiles: list[float]) -> pl.DataFrame:
        return pl.DataFrame(
            {"quantile": quantiles, "value": [self._mean * horizon] * len(quantiles)}
        )


class _UpToForecastPolicy:
    def order(self, ctx: DecisionContext) -> float:
        # 4 x a previsão do horizonte: pede cedo e de forma sensível ao histórico.
        return max(0.0, 4 * float(ctx.forecast["value"][0]) - ctx.on_hand - ctx.in_transit)


def _run_simulator(
    demand: pl.DataFrame, flags: pl.DataFrame | None
) -> tuple[list[DailyEvent], _RecordingMeanForecaster]:
    forecaster = _RecordingMeanForecaster()
    state = InventoryState(data_inicial=D0 - timedelta(days=1))
    # 300 > demanda total de 28 dias (~260): nenhuma ruptura, com ou sem pedido novo.
    state.receber(300.0, validade=None)
    simulator = Simulator(
        state,
        forecaster,
        _UpToForecastPolicy(),
        demand,
        lead_time_days=1,
        horizon_days=7,
        quantiles=[0.5],
        is_review_day=review_every_n_days(reference=D0, period_days=7),
        shelf_life_from_arrival_days=None,
        censoring_flags=flags,
    )
    events = simulator.run(D0, D0 + timedelta(days=n_days - 1))
    return events, forecaster


n_days = 28
_ZERO_DAYS = [D0 + timedelta(days=3), D0 + timedelta(days=10)]


def _demand_with_zeros() -> pl.DataFrame:
    units = [0.0 if D0 + timedelta(days=i) in _ZERO_DAYS else 10.0 for i in range(n_days)]
    return pl.DataFrame(
        {"date": [D0 + timedelta(days=i) for i in range(n_days)], "units_sold": units}
    )


def _flags_for(days: list[date]) -> pl.DataFrame:
    all_days = [D0 + timedelta(days=i) for i in range(n_days)]
    return pl.DataFrame({"date": all_days, "is_censored": [d in days for d in all_days]})


def test_simulador_com_censura_nao_muda_demanda_nem_atendimento_so_o_pedido() -> None:
    demand = _demand_with_zeros()
    plain, plain_fc = _run_simulator(demand, None)
    censored, censored_fc = _run_simulator(demand, _flags_for(_ZERO_DAYS))

    # Demanda e atendimento: idênticos, dia a dia -- inclusive nos dias censurados.
    assert [e.demand for e in censored] == [e.demand for e in plain]
    assert [e.unmet_demand for e in censored] == [e.unmet_demand for e in plain]
    assert [e.sold for e in censored] == [e.sold for e in plain]
    assert [e.demand for e in plain if e.day in _ZERO_DAYS] == [0.0, 0.0]

    # O histórico entregue ao forecaster perde os dias marcados, e só eles...
    as_of = D0 + timedelta(days=14)
    assert set(plain_fc.seen[as_of]) - set(censored_fc.seen[as_of]) == set(_ZERO_DAYS)
    # ...e é isso que muda o pedido (média sobe sem os zeros).
    plain_orders = [e.order_placed for e in plain]
    censored_orders = [e.order_placed for e in censored]
    assert censored_orders != plain_orders
    after_first_zero = [
        (c, p)
        for e, c, p in zip(plain, censored_orders, plain_orders, strict=True)
        if e.day > _ZERO_DAYS[0]
    ]
    assert any(c is not None and p is not None and c > p for c, p in after_first_zero)


def test_simulador_com_flags_vazias_e_identico_ao_sem_flags() -> None:
    demand = _demand_with_zeros()
    plain, _ = _run_simulator(demand, None)
    empty, _ = _run_simulator(demand, _flags_for([]))
    assert empty == plain


def test_purchase_list_com_censura_usa_historico_censurado() -> None:
    params = load_params(Path(__file__).resolve().parent.parent / "config" / "params.yaml")
    # ARM2_CHOSEN_ALPHA (0,66) não está na grade model.quantiles atual do params.yaml;
    # o teste inclui o 0,66 na grade para exercitar a censura, não essa divergência.
    cell_params = params.model_copy(
        update={"model": params.model.model_copy(update={"quantiles": [0.5, 0.66, 0.9]})}
    )
    start = cell_params.simulation.start_date
    as_of = start + timedelta(days=100)
    days = [start - timedelta(days=120) + timedelta(days=i) for i in range(120 + 100)]
    zero_days = [d for d in days if d >= as_of - timedelta(days=28) and (d - start).days % 4 == 0]
    demand = pl.DataFrame(
        {"date": days, "units_sold": [0.0 if d in zero_days else 10.0 for d in days]}
    )
    flags = pl.DataFrame({"date": days, "is_censored": [d in zero_days for d in days]})
    kwargs = {
        "lead_time_days": 2,
        "review_period_days": 7,
        "demand": demand,
        "cell_params": cell_params,
        "as_of": as_of,
        "variation_lookback_days": 90,
    }

    plain = _decide_item(**kwargs)  # type: ignore[arg-type]
    none_marked = _decide_item(
        **kwargs,  # type: ignore[arg-type]
        censoring_flags=flags.with_columns(pl.lit(False).alias("is_censored")),
    )
    censored = _decide_item(**kwargs, censoring_flags=flags)  # type: ignore[arg-type]

    assert none_marked == plain  # nada marcado = comportamento de antes
    # Sem os zeros a previsão sobe: os pedidos simulados (média das compras
    # recentes e pipeline na véspera de as_of) mudam em relação ao histórico bruto.
    assert censored[4] > plain[4]
    assert censored[2] != plain[2]
    assert censored[3] == plain[3]  # cobertura em dias usa a demanda observada, não censurada

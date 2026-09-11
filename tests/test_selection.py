"""Testes de motor.selection -- seleção do subconjunto de trabalho (Sprint 4).

Todo frame é sintético, construído à mão com os nomes CANÔNICOS (`store_id`,
`item_id`, `units_sold`, ...) -- `selection.py` opera depois da normalização
do Sprint 3, nunca vê o formato bruto do Favorita. Nenhum teste aqui lê
`data/`.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from motor.config import (
    CanonicalParams,
    Params,
    SimulationParams,
    SubsetSelectionParams,
    load_params,
)
from motor.selection import (
    LeakageGuardError,
    _cap_by_family,
    _density_by_item,
    _exclude_degenerate_families,
    select_subset,
)

PARAMS_PATH = Path(__file__).resolve().parent.parent / "config" / "params.yaml"

# --------------------------------------------------------------------------
# Construtores de frame sintético e de config
# --------------------------------------------------------------------------


def _tiny_params(
    *,
    canonical: CanonicalParams,
    subset_selection: SubsetSelectionParams,
    simulation: SimulationParams,
) -> Params:
    """`params.yaml` real do repositório, com as três seções relevantes trocadas por
    versões pequenas/controladas -- evita reconstruir o `Params` inteiro (padrão de
    `tests/test_loaders.py::_tiny_params`)."""
    base = load_params(PARAMS_PATH)
    return base.model_copy(
        update={
            "canonical": canonical,
            "subset_selection": subset_selection,
            "simulation": simulation,
        }
    )


def _daterange(start: date, end: date) -> list[date]:
    n = (end - start).days + 1
    return [start + timedelta(days=i) for i in range(n)]


def _sale_rows(
    *,
    store_id: str,
    item_id: str,
    units_by_date: dict[date, float],
    promo_by_date: dict[date, bool] | None = None,
) -> list[dict[str, object]]:
    """Uma linha por (store_id, item_id, date), no formato canônico de `Sale`."""
    promo_by_date = promo_by_date or {}
    return [
        {
            "store_id": store_id,
            "item_id": item_id,
            "date": d,
            "units_sold": units,
            "units_returned": 0.0,
            "on_promo": promo_by_date.get(d, False),
            "price": None,
            "is_operating_day": True,
            "is_anomaly": False,
            "anomaly_reason": None,
        }
        for d, units in units_by_date.items()
    ]


def _item_row(
    *, item_id: str, category: str, supplier_id: str, is_perishable: bool = False
) -> dict[str, object]:
    return {
        "item_id": item_id,
        "ean": None,
        "description": None,
        "category": category,
        "item_class": None,
        "supplier_id": supplier_id,
        "unit_of_sale": "unidade",
        "pack_multiple": None,
        "is_perishable": is_perishable,
        "is_anchor": None,
        "cost": None,
        "price_ref": None,
    }


_EMPTY_SUPPLIERS = pl.DataFrame(
    schema={
        "supplier_id": pl.String,
        "lead_time_days": pl.Int64,
        "order_days": pl.List(pl.Int64),
        "review_period_days": pl.Int64,
        "min_order_value": pl.Float64,
        "min_order_units": pl.Float64,
    }
)
_EMPTY_STOCK = pl.DataFrame(
    schema={
        "store_id": pl.String,
        "item_id": pl.String,
        "date": pl.Date,
        "on_hand": pl.Float64,
        "in_transit": pl.Float64,
    }
)


# --------------------------------------------------------------------------
# Cenário completo, reusado por mais de um teste: 2 famílias, uma degenerada
# --------------------------------------------------------------------------

_WINDOW_START = date(2024, 1, 1)
_WINDOW_END = date(2024, 2, 19)  # 50 dias
_DENSITY_START = date(2024, 1, 1)
_DENSITY_END = date(2024, 1, 20)  # primeiros 20 dias -- fatia segura
_SIM_START = date(2024, 1, 21)  # estritamente depois de _DENSITY_END


def _item_with_pattern(
    *, store_id: str, item_id: str, n_dias_vendidos_na_fatia: int
) -> list[dict[str, object]]:
    """Vende em `n_dias_vendidos_na_fatia` dos 20 dias da fatia segura (densidade =
    n/20), presente em TODOS os dias da janela canônica inteira (lifespan completo,
    D2). Fora da fatia segura, vende todo dia -- não deveria importar para D3."""
    units_by_date: dict[date, float] = {}
    for i, d in enumerate(_daterange(_WINDOW_START, _DENSITY_END)):
        units_by_date[d] = 1.0 if i < n_dias_vendidos_na_fatia else 0.0
    for d in _daterange(_DENSITY_END + timedelta(days=1), _WINDOW_END):
        units_by_date[d] = 1.0
    return _sale_rows(store_id=store_id, item_id=item_id, units_by_date=units_by_date)


def _cenario_duas_familias() -> tuple[pl.LazyFrame, pl.DataFrame, Params]:
    """FAM_A: 3 itens, densidade 0,9 (18/20). FAM_B: 2 itens, densidade 0,9 -- família
    inteira excluída por `family_min_items=3`, mesmo os itens individualmente passando
    em tudo mais (D6)."""
    store_id = "44"
    rows: list[dict[str, object]] = []
    for item_id in ["A1", "A2", "A3"]:
        rows += _item_with_pattern(store_id=store_id, item_id=item_id, n_dias_vendidos_na_fatia=18)
    for item_id in ["B1", "B2"]:
        rows += _item_with_pattern(store_id=store_id, item_id=item_id, n_dias_vendidos_na_fatia=18)
    sales = pl.LazyFrame(rows)

    items = pl.DataFrame(
        [
            _item_row(item_id="A1", category="FAMILIA_A", supplier_id="SUP-FAM-A"),
            _item_row(item_id="A2", category="FAMILIA_A", supplier_id="SUP-FAM-A"),
            _item_row(item_id="A3", category="FAMILIA_A", supplier_id="SUP-FAM-A"),
            _item_row(item_id="B1", category="FAMILIA_B", supplier_id="SUP-FAM-B"),
            _item_row(item_id="B2", category="FAMILIA_B", supplier_id="SUP-FAM-B"),
        ]
    )

    canonical = CanonicalParams(
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        delisting_gap_days=90,
        fractional_threshold=0.5,
        anomalies=[],
    )
    subset_selection = SubsetSelectionParams(
        store_id=store_id,
        n_stores=1,
        n_items_min=1,
        n_items_max=10,
        min_weeks_of_history=1,
        density_window_start=_DENSITY_START,
        density_window_end=_DENSITY_END,
        density_threshold=0.9,
        promo_days_max_share=0.5,
        family_min_items=3,
        family_cap=10,  # folgado -- este cenário não testa o cap
    )
    simulation = SimulationParams(
        warmup_days=1,
        start_date=_SIM_START,
        evaluation_start_date=_SIM_START,
        end_date=_WINDOW_END,
        seed=42,
    )
    params = _tiny_params(
        canonical=canonical, subset_selection=subset_selection, simulation=simulation
    )
    return sales, items, params


# --------------------------------------------------------------------------
# 1. Estabilidade: duas execuções, mesma config -> mesma lista, mesma ordem
# --------------------------------------------------------------------------


def test_estabilidade_duas_execucoes_saida_identica() -> None:
    sales, items, params = _cenario_duas_familias()
    r1 = select_subset(sales, items, _EMPTY_SUPPLIERS, _EMPTY_STOCK, params)
    r2 = select_subset(sales, items, _EMPTY_SUPPLIERS, _EMPTY_STOCK, params)

    assert r1.item_ids == r2.item_ids
    assert r1.store_id == r2.store_id
    assert r1.funnel.equals(r2.funnel)


# --------------------------------------------------------------------------
# 2. Determinismo do cap: famílias empatadas em contagem, ordem = especificada
# --------------------------------------------------------------------------


def test_determinismo_do_cap_por_familia() -> None:
    """SUP-ZEBRA e SUP-ALPHA empatam em contagem (2 itens cada). D7: ordem entre
    famílias é (contagem_familia asc, supplier_id asc) -- ALPHA antes de ZEBRA,
    nunca a ordem em que as linhas foram inseridas no frame (aqui, de propósito,
    ZEBRA vem primeiro na entrada)."""
    candidates = pl.DataFrame(
        {
            "item_id": ["Z1", "Z2", "A1", "A2"],
            "densidade": [0.91, 0.95, 0.92, 0.99],
            "category": ["ZEBRA", "ZEBRA", "ALPHA", "ALPHA"],
            "supplier_id": ["SUP-ZEBRA", "SUP-ZEBRA", "SUP-ALPHA", "SUP-ALPHA"],
        }
    )

    result = _cap_by_family(candidates, family_cap=1)

    # cap=1: só o item de maior densidade de cada família sobrevive.
    assert result["item_id"].to_list() == ["A2", "Z2"]


def test_determinismo_do_cap_desempate_dentro_da_familia() -> None:
    """Dentro da família, sem cap (todos cabem): ordem é (densidade desc, item_id asc)."""
    candidates = pl.DataFrame(
        {
            "item_id": ["X3", "X1", "X2"],
            "densidade": [0.90, 0.99, 0.99],
            "category": ["FAM", "FAM", "FAM"],
            "supplier_id": ["SUP-FAM", "SUP-FAM", "SUP-FAM"],
        }
    )

    result = _cap_by_family(candidates, family_cap=10)

    # X1 e X2 empatam em densidade (0.99) -> desempate por item_id asc; X3 (0.90) por último.
    assert result["item_id"].to_list() == ["X1", "X2", "X3"]


# --------------------------------------------------------------------------
# 3. Isolamento temporal: nenhuma linha depois de density_window_end pode
#    influenciar o resultado (prova de que D3 não vaza)
# --------------------------------------------------------------------------


def test_isolamento_temporal_nao_ve_periodo_de_avaliacao() -> None:
    """Duas versões do mesmo cenário, IDÊNTICAS até `_DENSITY_END` (mesma
    densidade, 18/20 -- passa no piso de 0,9), e DELIBERADAMENTE opostas depois
    dele: versão A vende todo dia após o corte, versão B não vende nenhum dia.
    Se alguma função lesse além de `density_window_end`, os dois resultados
    divergiriam -- inclusive o funil inteiro (`select_subset`, não só
    `_density_by_item`, roda igual nas duas). Mesmo padrão de
    `tests/test_loaders.py::test_sem_vazamento_por_agregado_global`: provar
    por execução, não só por leitura de código.
    """
    store_id = "44"

    def _build(*, vende_depois_do_corte: bool) -> pl.LazyFrame:
        units_by_date: dict[date, float] = {}
        for i, d in enumerate(_daterange(_WINDOW_START, _DENSITY_END)):
            units_by_date[d] = 1.0 if i < 18 else 0.0  # 18/20 = densidade 0,9
        pos_corte_units = 1.0 if vende_depois_do_corte else 0.0
        for d in _daterange(_DENSITY_END + timedelta(days=1), _WINDOW_END):
            units_by_date[d] = pos_corte_units
        promo_by_date = {d: vende_depois_do_corte for d in units_by_date if d > _DENSITY_END}
        rows = _sale_rows(
            store_id=store_id,
            item_id="I1",
            units_by_date=units_by_date,
            promo_by_date=promo_by_date,
        )
        return pl.LazyFrame(rows)

    items = pl.DataFrame([_item_row(item_id="I1", category="FAM", supplier_id="SUP-FAM")])
    canonical = CanonicalParams(
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        delisting_gap_days=90,
        fractional_threshold=0.5,
        anomalies=[],
    )
    subset_selection = SubsetSelectionParams(
        store_id=store_id,
        n_stores=1,
        n_items_min=1,
        n_items_max=10,
        min_weeks_of_history=1,
        density_window_start=_DENSITY_START,
        density_window_end=_DENSITY_END,
        density_threshold=0.9,
        promo_days_max_share=0.5,
        family_min_items=1,
        family_cap=10,
    )
    simulation = SimulationParams(
        warmup_days=1,
        start_date=_SIM_START,
        evaluation_start_date=_SIM_START,
        end_date=_WINDOW_END,
        seed=42,
    )
    params = _tiny_params(
        canonical=canonical, subset_selection=subset_selection, simulation=simulation
    )

    result_a = select_subset(
        _build(vende_depois_do_corte=True), items, _EMPTY_SUPPLIERS, _EMPTY_STOCK, params
    )
    result_b = select_subset(
        _build(vende_depois_do_corte=False), items, _EMPTY_SUPPLIERS, _EMPTY_STOCK, params
    )

    assert result_a.item_ids == result_b.item_ids == ("I1",)
    assert result_a.funnel.equals(result_b.funnel)


def test_leakage_guard_barra_janela_de_densidade_mal_configurada() -> None:
    """`density_window_end >= simulation.start_date` tem que levantar erro em runtime,
    não só ser um cuidado de convenção (D3)."""
    canonical = CanonicalParams(
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        delisting_gap_days=90,
        fractional_threshold=0.5,
        anomalies=[],
    )
    subset_selection = SubsetSelectionParams(
        store_id="44",
        n_stores=1,
        n_items_min=1,
        n_items_max=10,
        min_weeks_of_history=1,
        density_window_start=_DENSITY_START,
        density_window_end=_DENSITY_END,
        density_threshold=0.9,
        promo_days_max_share=0.5,
        family_min_items=1,
        family_cap=10,
    )
    simulation = SimulationParams(
        warmup_days=1,
        start_date=_DENSITY_END,  # não é estritamente posterior -> deve barrar
        evaluation_start_date=_DENSITY_END,
        end_date=_WINDOW_END,
        seed=42,
    )
    params = _tiny_params(
        canonical=canonical, subset_selection=subset_selection, simulation=simulation
    )
    items = pl.DataFrame([_item_row(item_id="I1", category="FAM", supplier_id="SUP-FAM")])
    sales = pl.LazyFrame(
        _sale_rows(store_id="44", item_id="I1", units_by_date={_WINDOW_START: 1.0})
    )

    with pytest.raises(LeakageGuardError):
        select_subset(sales, items, _EMPTY_SUPPLIERS, _EMPTY_STOCK, params)


# --------------------------------------------------------------------------
# 4. Densidade: caso pequeno com buracos de calendário conhecidos
# --------------------------------------------------------------------------


def test_densidade_com_buracos_de_calendario_conhecidos() -> None:
    """Item vende em 6 dos 10 dias da fatia (dias 1,2,4,6,7,10 -- buracos nos dias
    3,5,8,9) -- densidade esperada = 6/10 = 0,6, calculada à mão."""
    store_id = "44"
    density_start = date(2024, 1, 1)
    density_end = date(2024, 1, 10)
    dias_vendidos = {1, 2, 4, 6, 7, 10}
    units_by_date = {
        density_start + timedelta(days=i - 1): (2.0 if i in dias_vendidos else 0.0)
        for i in range(1, 11)
    }
    # Linha fora da fatia (dia 11): valor absurdo -- não pode entrar na média.
    units_by_date[density_end + timedelta(days=1)] = 999.0

    sales = pl.LazyFrame(_sale_rows(store_id=store_id, item_id="I1", units_by_date=units_by_date))

    result = _density_by_item(
        sales, store_id=store_id, density_window_start=density_start, density_window_end=density_end
    )

    row = result.filter(pl.col("item_id") == "I1").row(0, named=True)
    assert row["n_dias_na_fatia"] == 10
    assert row["n_dias_com_venda"] == 6
    assert row["densidade"] == pytest.approx(0.6)


# --------------------------------------------------------------------------
# 5. Família degenerada: família com 2 itens some da saída e aparece no funil
# --------------------------------------------------------------------------


def test_familia_degenerada_excluida_da_saida_e_registrada_no_funil() -> None:
    sales, items, params = _cenario_duas_familias()

    result = select_subset(sales, items, _EMPTY_SUPPLIERS, _EMPTY_STOCK, params)

    # FAM_B (2 itens, < family_min_items=3) não aparece na saída...
    assert "B1" not in result.item_ids
    assert "B2" not in result.item_ids
    # ...enquanto FAM_A (3 itens) sobrevive inteira.
    assert set(result.item_ids) == {"A1", "A2", "A3"}

    motivo = result.funnel.filter(pl.col("stage") == "familia_degenerada")["motivo"].item()
    assert "SUP-FAM-B" in motivo
    assert "2" in motivo  # contagem da família excluída, visível no motivo


def test_exclude_degenerate_families_isolado() -> None:
    """A mesma checagem, direto na função isolada (sem passar pelo pipeline inteiro)."""
    candidates = pl.DataFrame(
        {
            "item_id": ["A1", "A2", "A3", "B1", "B2"],
            "densidade": [0.9, 0.9, 0.9, 0.9, 0.9],
        }
    )
    items = pl.DataFrame(
        [
            _item_row(item_id="A1", category="FAMILIA_A", supplier_id="SUP-FAM-A"),
            _item_row(item_id="A2", category="FAMILIA_A", supplier_id="SUP-FAM-A"),
            _item_row(item_id="A3", category="FAMILIA_A", supplier_id="SUP-FAM-A"),
            _item_row(item_id="B1", category="FAMILIA_B", supplier_id="SUP-FAM-B"),
            _item_row(item_id="B2", category="FAMILIA_B", supplier_id="SUP-FAM-B"),
        ]
    )

    kept, motivo = _exclude_degenerate_families(candidates, items, family_min_items=3)

    assert set(kept["item_id"].to_list()) == {"A1", "A2", "A3"}
    assert "SUP-FAM-B" in motivo

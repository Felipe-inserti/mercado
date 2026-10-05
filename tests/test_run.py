"""Testes de `motor.experiments.run` (Sprint 7).

Frames sintéticos com os nomes canônicos (mesmo padrão de
`tests/test_selection.py`) -- nenhum teste aqui lê `data/`.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError

from motor.assumptions import AssumptionOrigin
from motor.config import (
    CanonicalParams,
    Params,
    SimulationParams,
    SubsetSelectionParams,
    load_params,
)
from motor.experiments.run import (
    ExistingResultError,
    RunManifest,
    StaleSubsetSelectionError,
    _build_forecaster,
    _build_manifest,
    _build_policy,
    _find_arm,
    _quantile_gbm_retrain_dates,
    _selection_params_hash,
    load_or_select_subset,
    run_arm,
    run_arm_and_save,
)
from motor.experiments.sensitivity import build_cell_params
from motor.forecast.statistical import StatisticalForecaster
from motor.policy.basestock import BasestockPolicy
from motor.selection import SubsetSelectionResult
from motor.simulator.engine import review_every_n_days

PARAMS_PATH = Path(__file__).resolve().parent.parent / "config" / "params.yaml"

WINDOW_START = date(2024, 1, 1)
WINDOW_END = date(2024, 1, 30)  # 30 dias
DENSITY_START = WINDOW_START
DENSITY_END = date(2024, 1, 10)  # fatia segura, 10 dias
SIM_START = date(2024, 1, 11)  # estritamente depois de DENSITY_END
SIM_END = WINDOW_END


def _tiny_params() -> Params:
    """`params.yaml` real, com `canonical`/`subset_selection`/`simulation`
    trocados por uma janela pequena e controlada (padrão de
    `tests/test_selection.py::_tiny_params`) -- `forecast_naive`,
    `erp_baseline`, `model`, `experiments` ficam com os valores reais do
    repositório (é o que `run_arm` de fato usa em produção)."""
    base = load_params(PARAMS_PATH)
    return base.model_copy(
        update={
            "canonical": CanonicalParams(
                window_start=WINDOW_START,
                window_end=WINDOW_END,
                delisting_gap_days=90,
                fractional_threshold=0.5,
                anomalies=[],
            ),
            "subset_selection": SubsetSelectionParams(
                store_id="S1",
                n_stores=1,
                n_items_min=1,
                n_items_max=5,
                min_weeks_of_history=1,
                density_window_start=DENSITY_START,
                density_window_end=DENSITY_END,
                density_threshold=0.5,
                promo_days_max_share=1.0,
                family_min_items=1,
                family_cap=5,
            ),
            "simulation": SimulationParams(
                warmup_days=2,
                start_date=SIM_START,
                evaluation_start_date=SIM_START + timedelta(days=2),
                end_date=SIM_END,
                seed=42,
            ),
        }
    )


def _daterange(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _sale_rows(*, store_id: str, item_id: str, units: float) -> list[dict[str, object]]:
    return [
        {
            "store_id": store_id,
            "item_id": item_id,
            "date": d,
            "units_sold": units,
            "units_returned": 0.0,
            "on_promo": False,
            "price": None,
            "is_operating_day": True,
            "is_anomaly": False,
            "anomaly_reason": None,
        }
        for d in _daterange(WINDOW_START, WINDOW_END)
    ]


def _item_row(*, item_id: str, supplier_id: str) -> dict[str, object]:
    return {
        "item_id": item_id,
        "ean": None,
        "description": None,
        "category": "mercearia",
        "item_class": None,
        "supplier_id": supplier_id,
        "unit_of_sale": "unidade",
        "pack_multiple": 1.0,
        "is_perishable": False,
        "is_anchor": None,
        "cost": None,
        "price_ref": None,
    }


def _supplier_row(
    *, supplier_id: str, lead_time_days: int, review_period_days: int
) -> dict[str, object]:
    return {
        "supplier_id": supplier_id,
        "lead_time_days": lead_time_days,
        "order_days": [1, 2, 3, 4, 5],
        "review_period_days": review_period_days,
        "min_order_value": 0.0,
        "min_order_units": 0.0,
    }


_EMPTY_STOCK = pl.DataFrame(
    schema={
        "store_id": pl.String,
        "item_id": pl.String,
        "date": pl.Date,
        "on_hand": pl.Float64,
        "in_transit": pl.Float64,
    }
)


def _cenario_um_item() -> tuple[pl.LazyFrame, pl.DataFrame, pl.DataFrame, Params]:
    """Um item ("I1"), um fornecedor ("SUP1"), densidade 1.0 -- passa em todos
    os cortes de `select_subset` com a `_tiny_params` acima."""
    sales = pl.DataFrame(_sale_rows(store_id="S1", item_id="I1", units=5.0)).lazy()
    items = pl.DataFrame([_item_row(item_id="I1", supplier_id="SUP1")])
    suppliers = pl.DataFrame(
        [_supplier_row(supplier_id="SUP1", lead_time_days=2, review_period_days=3)]
    )
    return sales, items, suppliers, _tiny_params()


# -- hash dos parâmetros de seleção -----------------------------------------


def test_selection_params_hash_muda_quando_subset_selection_muda() -> None:
    params_a = _tiny_params()
    params_b = params_a.model_copy(
        update={
            "subset_selection": params_a.subset_selection.model_copy(
                update={"density_threshold": 0.99}
            )
        }
    )
    assert _selection_params_hash(params_a) != _selection_params_hash(params_b)


def test_selection_params_hash_nao_muda_quando_erp_baseline_muda() -> None:
    """`erp_baseline`/`forecast_naive` não entram no hash -- não afetam
    `select_subset` (ver docstring de `_selection_params_hash`)."""
    params_a = _tiny_params()
    params_b = params_a.model_copy(
        update={"erp_baseline": params_a.erp_baseline.model_copy(update={"factor": 999.0})}
    )
    assert _selection_params_hash(params_a) == _selection_params_hash(params_b)


def test_selection_params_hash_e_deterministico() -> None:
    params = _tiny_params()
    assert _selection_params_hash(params) == _selection_params_hash(params)


# -- load_or_select_subset ---------------------------------------------------


def test_load_or_select_subset_grava_cache_e_reusa_sem_rodar_select_subset_de_novo(
    tmp_path: Path,
) -> None:
    sales, items, suppliers, params = _cenario_um_item()
    cache_path = tmp_path / "subset_selection.json"

    primeira = load_or_select_subset(
        sales, items, suppliers, _EMPTY_STOCK, params, cache_path=cache_path
    )
    assert primeira.store_id == "S1"
    assert primeira.item_ids == ("I1",)
    assert cache_path.exists()

    # tabelas quebradas de propósito -- se `load_or_select_subset` rodasse
    # `select_subset` de novo em vez de usar o cache, isso quebraria ou
    # devolveria um resultado vazio.
    items_quebrado = items.clear()
    segunda = load_or_select_subset(
        sales, items_quebrado, suppliers, _EMPTY_STOCK, params, cache_path=cache_path
    )
    assert segunda.item_ids == primeira.item_ids
    assert segunda.store_id == primeira.store_id


def test_load_or_select_subset_levanta_stale_subset_selection_error_quando_hash_diverge(
    tmp_path: Path,
) -> None:
    sales, items, suppliers, params = _cenario_um_item()
    cache_path = tmp_path / "subset_selection.json"
    cache_path.write_text(
        json.dumps(
            {"params_hash": "hash-invalido", "store_id": "S1", "item_ids": ["I1"], "funnel": []}
        )
    )

    with pytest.raises(StaleSubsetSelectionError, match="outros parâmetros de seleção"):
        load_or_select_subset(sales, items, suppliers, _EMPTY_STOCK, params, cache_path=cache_path)


# -- run_arm ------------------------------------------------------------------


def _cache_path_pre_populado(tmp_path: Path, params: Params, result: SubsetSelectionResult) -> Path:
    """Grava o cache já resolvido -- evita depender da lógica de filtro de
    `select_subset` nos testes de `run_arm`, que testam outra coisa."""
    cache_path = tmp_path / "subset_selection.json"
    cache_path.write_text(
        json.dumps(
            {
                "params_hash": _selection_params_hash(params),
                "store_id": result.store_id,
                "item_ids": list(result.item_ids),
                "funnel": [],
            }
        )
    )
    return cache_path


def _cenario_dois_itens() -> tuple[pl.LazyFrame, pl.DataFrame, pl.DataFrame, Params]:
    sales = pl.DataFrame(
        _sale_rows(store_id="S1", item_id="I1", units=5.0)
        + _sale_rows(store_id="S1", item_id="I2", units=8.0)
    ).lazy()
    items = pl.DataFrame(
        [
            _item_row(item_id="I1", supplier_id="SUP1"),
            _item_row(item_id="I2", supplier_id="SUP1"),
        ]
    )
    suppliers = pl.DataFrame(
        [_supplier_row(supplier_id="SUP1", lead_time_days=2, review_period_days=3)]
    )
    return sales, items, suppliers, _tiny_params()


def test_run_arm_produz_uma_linha_por_item_dia(tmp_path: Path) -> None:
    sales, items, suppliers, params = _cenario_dois_itens()
    result = SubsetSelectionResult(store_id="S1", item_ids=("I1", "I2"), funnel=pl.DataFrame())
    cache_path = _cache_path_pre_populado(tmp_path, params, result)

    saida = run_arm(
        "erp_baseline",
        params,
        sales=sales,
        items=items,
        suppliers=suppliers,
        stock=_EMPTY_STOCK,
        subset_cache_path=cache_path,
    )

    n_dias = (SIM_END - SIM_START).days + 1
    assert saida.events.height == 2 * n_dias
    assert set(saida.events["item_id"].unique().to_list()) == {"I1", "I2"}
    assert set(saida.events["store_id"].unique().to_list()) == {"S1"}
    assert saida.events["day"].min() == SIM_START
    assert saida.events["day"].max() == SIM_END


def test_run_arm_estatistico_basestock_roda_ponta_a_ponta_com_as_mesmas_metricas(
    tmp_path: Path,
) -> None:
    """Fecha o braço 2 (Sprint 12): mesmo subconjunto, mesmo período, mesmas
    colunas de métrica que o braço 1 -- só forecaster/policy mudam."""
    sales, items, suppliers, params = _cenario_dois_itens()
    result = SubsetSelectionResult(store_id="S1", item_ids=("I1", "I2"), funnel=pl.DataFrame())
    cache_path = _cache_path_pre_populado(tmp_path, params, result)

    saida = run_arm(
        "estatistico_basestock",
        params,
        sales=sales,
        items=items,
        suppliers=suppliers,
        stock=_EMPTY_STOCK,
        subset_cache_path=cache_path,
    )

    n_dias = (SIM_END - SIM_START).days + 1
    assert saida.events.height == 2 * n_dias
    assert set(saida.events["item_id"].unique().to_list()) == {"I1", "I2"}
    assert saida.item_metrics.height == 2
    assert 0.0 <= saida.portfolio_metrics.nivel_servico <= 1.0


def test_run_arm_e_deterministico_entre_duas_chamadas(tmp_path: Path) -> None:
    sales, items, suppliers, params = _cenario_dois_itens()
    result = SubsetSelectionResult(store_id="S1", item_ids=("I1", "I2"), funnel=pl.DataFrame())
    cache_path = _cache_path_pre_populado(tmp_path, params, result)

    kwargs = {
        "sales": sales,
        "items": items,
        "suppliers": suppliers,
        "stock": _EMPTY_STOCK,
        "subset_cache_path": cache_path,
    }
    saida_a = run_arm("erp_baseline", params, **kwargs)
    saida_b = run_arm("erp_baseline", params, **kwargs)

    assert saida_a.events.equals(saida_b.events)


def test_run_arm_braco_desconhecido_levanta_value_error(tmp_path: Path) -> None:
    sales, items, suppliers, params = _cenario_um_item()
    result = SubsetSelectionResult(store_id="S1", item_ids=("I1",), funnel=pl.DataFrame())
    cache_path = _cache_path_pre_populado(tmp_path, params, result)

    with pytest.raises(ValueError, match=r"não existe em experiments\.arms"):
        run_arm(
            "braco_que_nao_existe",
            params,
            sales=sales,
            items=items,
            suppliers=suppliers,
            stock=_EMPTY_STOCK,
            subset_cache_path=cache_path,
        )


def test_build_forecaster_desconhecido_levanta_value_error() -> None:
    with pytest.raises(ValueError, match="forecaster desconhecido"):
        _build_forecaster("nao_existe", _tiny_params())


def test_build_forecaster_statistical_devolve_statistical_forecaster() -> None:
    forecaster = _build_forecaster("statistical", _tiny_params())
    assert isinstance(forecaster, StatisticalForecaster)


def test_build_policy_basestock_devolve_basestock_policy() -> None:
    params = _tiny_params()
    policy = _build_policy(
        "basestock", params, horizon_days=5, alpha=params.economics.default_alpha
    )
    assert isinstance(policy, BasestockPolicy)


def test_build_policy_desconhecida_levanta_value_error() -> None:
    params = _tiny_params()
    with pytest.raises(ValueError, match="policy desconhecida"):
        _build_policy("nao_existe", params, horizon_days=5, alpha=params.economics.default_alpha)


def test_find_arm_desconhecido_levanta_value_error() -> None:
    params = _tiny_params()
    with pytest.raises(ValueError, match=r"não existe em experiments\.arms"):
        _find_arm(params, "braco_que_nao_existe")


# -- manifesto ------------------------------------------------------------


def _canonical_dir_com_parquets(
    tmp_path: Path, *, sales: pl.LazyFrame, items: pl.DataFrame, suppliers: pl.DataFrame
) -> Path:
    """`_build_manifest` hasheia os 4 parquets canônicos -- grava versões
    materializadas num diretório temporário pros testes que exercitam isso."""
    canonical_dir = tmp_path / "canonical"
    canonical_dir.mkdir()
    sales.collect().write_parquet(canonical_dir / "sales.parquet")
    items.write_parquet(canonical_dir / "items.parquet")
    suppliers.write_parquet(canonical_dir / "suppliers.parquet")
    _EMPTY_STOCK.write_parquet(canonical_dir / "stock.parquet")
    return canonical_dir


def test_build_manifest_contem_premissas_compartilhadas_calibracao_e_financeiro(
    tmp_path: Path,
) -> None:
    sales, items, suppliers, params = _cenario_dois_itens()
    result = SubsetSelectionResult(store_id="S1", item_ids=("I1", "I2"), funnel=pl.DataFrame())
    cache_path = _cache_path_pre_populado(tmp_path, params, result)
    canonical_dir = _canonical_dir_com_parquets(
        tmp_path, sales=sales, items=items, suppliers=suppliers
    )

    saida = run_arm(
        "erp_baseline",
        params,
        sales=sales,
        items=items,
        suppliers=suppliers,
        stock=_EMPTY_STOCK,
        subset_cache_path=cache_path,
    )
    events_path = tmp_path / "events.parquet"
    item_metrics_path = tmp_path / "item_metrics.parquet"
    saida.events.write_parquet(events_path)
    saida.item_metrics.write_parquet(item_metrics_path)

    manifest = _build_manifest(
        "erp_baseline",
        params,
        saida,
        canonical_dir=canonical_dir,
        events_path=events_path,
        item_metrics_path=item_metrics_path,
        execution_seconds=1.23,
    )

    assert manifest.n_items == 2
    assert manifest.store_id == "S1"
    assert manifest.item_ids == ["I1", "I2"]
    assert "None" in manifest.shared_assumptions["shelf_life"]
    assert manifest.erp_baseline_calibration.factor == params.erp_baseline.factor
    assert manifest.erp_baseline_calibration.min_order_units == params.erp_baseline.min_order_units
    assert manifest.erp_baseline_calibration.coverage_context

    # braço 2 (Sprint 12): registrado no manifesto de todo braço, não só quando ativo
    assert manifest.basestock_calibration.alpha == params.economics.default_alpha
    assert "uniforme" in manifest.basestock_calibration.alpha_scope
    assert "category_alpha" in manifest.basestock_calibration.limitation

    # financeiro (Sprint 9): premissas E resultado no mesmo arquivo
    assert manifest.financial_assumptions.uniform_unit_price == params.economics.uniform_unit_price
    assert manifest.financial_assumptions.category_margin_pct == dict(
        params.economics.category_margin_pct
    )
    assert manifest.financial_assumptions.price_invariance_note
    assert manifest.financial_assumptions.scale_warning
    assert len(manifest.limitations) == 3
    assert manifest.results.portfolio.decision_metric == saida.portfolio_metrics.decision_metric
    assert manifest.results.item_metrics_path == "item_metrics.parquet"

    # autossuficiência: hash de código+parâmetros e dos parquets de entrada
    assert manifest.params_hash  # sha256 não vazio
    assert "escopos diferentes" in manifest.params_hash_scope
    assert set(manifest.input_files) == {"sales", "items", "suppliers", "stock"}
    assert all(f.sha256 and f.size_bytes > 0 for f in manifest.input_files.values())
    assert manifest.output_files["events"].size_bytes == events_path.stat().st_size
    assert manifest.row_counts["events"] == saida.events.height
    assert manifest.row_counts["item_metrics"] == saida.item_metrics.height


def test_build_manifest_e_json_serializavel_com_chaves_ordenadas(tmp_path: Path) -> None:
    """`main()` grava com `sort_keys=True` -- confirma que o `RunManifest`
    (via `model_dump(mode="json")`) não tem nada que quebre isso (datas,
    dicts aninhados etc.)."""
    sales, items, suppliers, params = _cenario_dois_itens()
    result = SubsetSelectionResult(store_id="S1", item_ids=("I1", "I2"), funnel=pl.DataFrame())
    cache_path = _cache_path_pre_populado(tmp_path, params, result)
    canonical_dir = _canonical_dir_com_parquets(
        tmp_path, sales=sales, items=items, suppliers=suppliers
    )

    saida = run_arm(
        "erp_baseline",
        params,
        sales=sales,
        items=items,
        suppliers=suppliers,
        stock=_EMPTY_STOCK,
        subset_cache_path=cache_path,
    )
    events_path = tmp_path / "events.parquet"
    item_metrics_path = tmp_path / "item_metrics.parquet"
    saida.events.write_parquet(events_path)
    saida.item_metrics.write_parquet(item_metrics_path)

    manifest = _build_manifest(
        "erp_baseline",
        params,
        saida,
        canonical_dir=canonical_dir,
        events_path=events_path,
        item_metrics_path=item_metrics_path,
        execution_seconds=1.23,
    )
    encoded = json.dumps(manifest.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    decoded = json.loads(encoded)
    assert decoded["arm"] == "erp_baseline"


def test_build_manifest_registra_grade_de_quantis_ativa(tmp_path: Path) -> None:
    """Sprint 16: `active_quantiles` presente em TODO manifesto (mesmo padrão
    de `basestock_calibration`), não só quando `forecaster == 'quantile_gbm'`
    -- é o campo que permite checar se dois manifestos de braço 3 são
    comparáveis entre si (ver `QuantileGbmDiagnosticsManifest.grid_coupling_note`,
    achado do acoplamento por rank na correção de não-cruzamento)."""
    sales, items, suppliers, params = _cenario_dois_itens()
    result = SubsetSelectionResult(store_id="S1", item_ids=("I1", "I2"), funnel=pl.DataFrame())
    cache_path = _cache_path_pre_populado(tmp_path, params, result)
    canonical_dir = _canonical_dir_com_parquets(
        tmp_path, sales=sales, items=items, suppliers=suppliers
    )

    saida = run_arm(
        "erp_baseline",
        params,
        sales=sales,
        items=items,
        suppliers=suppliers,
        stock=_EMPTY_STOCK,
        subset_cache_path=cache_path,
    )
    events_path = tmp_path / "events.parquet"
    item_metrics_path = tmp_path / "item_metrics.parquet"
    saida.events.write_parquet(events_path)
    saida.item_metrics.write_parquet(item_metrics_path)

    manifest = _build_manifest(
        "erp_baseline",
        params,
        saida,
        canonical_dir=canonical_dir,
        events_path=events_path,
        item_metrics_path=item_metrics_path,
        execution_seconds=1.23,
    )

    assert manifest.active_quantiles == list(params.model.quantiles)


def test_build_manifest_inclui_registro_de_premissas(tmp_path: Path) -> None:
    """Sprint 16.5, Etapa 3.1: `assumptions` é campo obrigatório de
    `RunManifest` -- presente e com a origem certa nas 8 premissas
    exigidas."""
    sales, items, suppliers, params = _cenario_dois_itens()
    result = SubsetSelectionResult(store_id="S1", item_ids=("I1", "I2"), funnel=pl.DataFrame())
    cache_path = _cache_path_pre_populado(tmp_path, params, result)
    canonical_dir = _canonical_dir_com_parquets(
        tmp_path, sales=sales, items=items, suppliers=suppliers
    )

    saida = run_arm(
        "erp_baseline",
        params,
        sales=sales,
        items=items,
        suppliers=suppliers,
        stock=_EMPTY_STOCK,
        subset_cache_path=cache_path,
    )
    events_path = tmp_path / "events.parquet"
    item_metrics_path = tmp_path / "item_metrics.parquet"
    saida.events.write_parquet(events_path)
    saida.item_metrics.write_parquet(item_metrics_path)

    manifest = _build_manifest(
        "erp_baseline",
        params,
        saida,
        canonical_dir=canonical_dir,
        events_path=events_path,
        item_metrics_path=item_metrics_path,
        execution_seconds=1.23,
    )

    default_lead_time = params.supplier_assumptions.default_lead_time_days
    assert manifest.assumptions.lead_time_days.valor == default_lead_time
    assert manifest.assumptions.lead_time_days.origem == AssumptionOrigin.ARBITRADO


def test_run_manifest_sem_registro_de_premissas_falha_explicito(tmp_path: Path) -> None:
    """`assumptions` não tem default -- gravar um manifesto sem o registro
    completo tem que falhar alto e claro (pydantic recusa a validação),
    nunca produzir um resultado incompleto em silêncio."""
    sales, items, suppliers, params = _cenario_dois_itens()
    result = SubsetSelectionResult(store_id="S1", item_ids=("I1", "I2"), funnel=pl.DataFrame())
    cache_path = _cache_path_pre_populado(tmp_path, params, result)
    canonical_dir = _canonical_dir_com_parquets(
        tmp_path, sales=sales, items=items, suppliers=suppliers
    )

    saida = run_arm(
        "erp_baseline",
        params,
        sales=sales,
        items=items,
        suppliers=suppliers,
        stock=_EMPTY_STOCK,
        subset_cache_path=cache_path,
    )
    events_path = tmp_path / "events.parquet"
    item_metrics_path = tmp_path / "item_metrics.parquet"
    saida.events.write_parquet(events_path)
    saida.item_metrics.write_parquet(item_metrics_path)

    manifest = _build_manifest(
        "erp_baseline",
        params,
        saida,
        canonical_dir=canonical_dir,
        events_path=events_path,
        item_metrics_path=item_metrics_path,
        execution_seconds=1.23,
    )
    incompleto = manifest.model_dump(mode="json")
    del incompleto["assumptions"]

    with pytest.raises(ValidationError, match="assumptions"):
        RunManifest.model_validate(incompleto)


def test_retrain_dates_bate_exato_com_dias_de_decisao_do_simulador_review_period_variado() -> None:
    """Sprint 16.5, Etapa 3.5: achado da revisão -- `_quantile_gbm_retrain_dates`
    (usada tanto para as datas de retreino do braço 3 quanto para as
    `decision_dates` de `precompute_predictions`) e o calendário de revisão
    real do `Simulator` (`review_every_n_days`) são DUAS implementações
    separadas. Para `review_period_days=14` (varredura dirigida da Etapa
    3.4), elas têm que concordar EXATAMENTE -- comparação de CONJUNTO, não
    de contagem: um desvio de um dia com a mesma quantidade de datas não
    apareceria comparando só `len()`."""
    base = load_params(PARAMS_PATH)
    cell_params = build_cell_params(base, alpha=base.economics.default_alpha, review_period_days=14)
    # build_cell_params amarra retrain_cadence_days a review_period_days -- checagem
    # explícita de que não sobrou nenhum "7" fixo no caminho.
    assert cell_params.model.retrain_cadence_days == 14

    obtido = set(_quantile_gbm_retrain_dates(cell_params))

    is_review_day = review_every_n_days(reference=cell_params.simulation.start_date, period_days=14)
    esperado: set[date] = set()
    dia = cell_params.simulation.start_date
    while dia <= cell_params.simulation.end_date:
        if is_review_day(dia):
            esperado.add(dia)
        dia += timedelta(days=1)

    assert obtido, "janela de teste vazia -- ajuste params.yaml de teste, não a asserção"
    assert obtido == esperado


def test_sem_a_amarracao_o_retreino_desperdica_o_dobro_de_datas() -> None:
    """Prova, por contraste, o que a amarração em `build_cell_params` evita
    -- e corrige uma previsão errada que eu fiz ao propor o teste anterior.

    Para `review_period_days=14` especificamente, 14 é múltiplo de 7
    (`retrain_cadence_days` default): sem a amarração, as datas de decisão
    reais (a cada 14 dias) são SUBCONJUNTO das datas de retreino
    desamarradas (a cada 7 dias, começando na mesma referência) -- então o
    guarda `as_of not in self._precomputed` NÃO estouraria neste caso
    específico (todo `as_of` pedido já estaria no cache). O problema real
    sem a amarração não é uma exceção aqui -- é `_build_quantile_gbm_registry`
    treinar e pré-computar em 2x mais datas do que o Simulator jamais vai
    consultar, desperdício puro. (O guarda estouraria de verdade para um
    `review_period_days` que NÃO fosse múltiplo do `retrain_cadence_days`
    default, ex. 10 -- fora da grade desta etapa, mas é a razão de a
    amarração ser regra geral, não um remendo só para 14.)
    """
    base = load_params(PARAMS_PATH)
    sem_amarracao = base.model_copy(
        update={"model": base.model.model_copy(update={"retrain_cadence_days": 7})}
    )

    datas_retreino_desamarradas = set(_quantile_gbm_retrain_dates(sem_amarracao))
    is_review_day_14 = review_every_n_days(reference=base.simulation.start_date, period_days=14)
    datas_decisao_reais: set[date] = set()
    dia = base.simulation.start_date
    while dia <= base.simulation.end_date:
        if is_review_day_14(dia):
            datas_decisao_reais.add(dia)
        dia += timedelta(days=1)

    # não estoura o guarda neste caso (14 é múltiplo de 7) -- mas desperdiça o dobro
    assert datas_decisao_reais.issubset(datas_retreino_desamarradas)
    assert len(datas_retreino_desamarradas) == pytest.approx(2 * len(datas_decisao_reais), abs=1)


def test_build_cell_params_sem_review_period_nao_toca_retrain_cadence() -> None:
    """Retrocompatibilidade: a varredura de 75 células já aprovada não passa
    `review_period_days` -- `model.retrain_cadence_days` tem que continuar
    exatamente o valor de `params.yaml`, sem surpresa."""
    base = load_params(PARAMS_PATH)
    cell_params = build_cell_params(base, alpha=base.economics.default_alpha)
    assert cell_params.model.retrain_cadence_days == base.model.retrain_cadence_days


def test_run_arm_and_save_recusa_sobrescrever_sem_force(tmp_path: Path) -> None:
    """Sprint 16 (revisão): `results/` não é versionado -- rodar de novo em
    cima de um manifesto já gravado sem `force=True` tem que recusar,
    explícito, em vez de sobrescrever em silêncio (é o que já aconteceu de
    verdade nesta sprint, antes desta guarda existir)."""
    sales, items, suppliers, params = _cenario_dois_itens()
    result = SubsetSelectionResult(store_id="S1", item_ids=("I1", "I2"), funnel=pl.DataFrame())
    cache_path = _cache_path_pre_populado(tmp_path, params, result)
    canonical_dir = _canonical_dir_com_parquets(
        tmp_path, sales=sales, items=items, suppliers=suppliers
    )
    results_dir = tmp_path / "results"

    def _run(*, force: bool = False) -> RunManifest:
        return run_arm_and_save(
            "erp_baseline",
            params,
            sales=sales,
            items=items,
            suppliers=suppliers,
            stock=_EMPTY_STOCK,
            subset_cache_path=cache_path,
            canonical_dir=canonical_dir,
            results_dir=results_dir,
            force=force,
        )

    primeiro = _run()
    assert (results_dir / "erp_baseline" / "manifest.json").exists()

    with pytest.raises(ExistingResultError):
        _run()

    # force=True sobrescreve normalmente, sem levantar
    segundo = _run(force=True)
    assert segundo.results.portfolio.decision_metric == primeiro.results.portfolio.decision_metric

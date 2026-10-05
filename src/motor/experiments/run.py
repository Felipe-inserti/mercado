"""Runner de um braço de experimento (Sprint 7: braço 1 ERP baseline; Sprint 9:
integração das métricas financeiras e resumo autossuficiente).

Roda o `Simulator` por par loja-item sobre o subconjunto real, converte os
eventos em métricas financeiras (`motor.metrics.financial`, Sprint 8) e grava
três artefatos por braço, em `results/<arm>/`:

    events.parquet       -- série diária crua, sem R$, uma linha por item-dia
    item_metrics.parquet -- métricas financeiras por item + price/cost/margin_pct
                             (Sprint 16 varre isso, Sprint 17 monta a lista de
                             compra a partir daqui -- sem recalcular economia)
    manifest.json         -- resumo AUTOSSUFICIENTE: premissas ativas por
                             extenso + resultado agregado, no mesmo arquivo
                             (`RunManifest`, mesmo padrão de
                             `motor.io.loaders.CanonicalManifest`)

CLI: `python -m motor.experiments.run --arm erp_baseline`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final

import polars as pl
from pydantic import BaseModel, ConfigDict

from motor.assumptions import AssumptionsRegistry, build_assumptions_registry
from motor.config import ExperimentArmParams, Params, load_params
from motor.experiments.shared import build_simulator_for_pair
from motor.features.calendar import StoreLocale, load_holidays, load_store_locale
from motor.forecast.base import Forecaster
from motor.forecast.naive import NaiveForecaster
from motor.forecast.quantile_gbm import (
    QuantileGbmForecaster,
    QuantileModelRegistry,
    compute_config_hash,
    precompute_predictions,
    train_quantile_models,
)
from motor.forecast.statistical import StatisticalForecaster
from motor.io.loaders import InputFileManifest, OutputFileManifest
from motor.metrics.financial import (
    LIMITATIONS,
    PRICE_INVARIANCE_NOTE,
    SCALE_WARNING,
    PortfolioFinancialMetrics,
    build_item_economics,
    compute_financial_metrics,
    compute_portfolio_metrics,
)
from motor.policy.base import Policy
from motor.policy.basestock import BasestockPolicy
from motor.policy.erp_baseline import ErpBaselinePolicy
from motor.selection import SubsetSelectionResult, select_subset

_REPO_ROOT: Final = Path(__file__).resolve().parents[3]
_RUN_MANIFEST_SCHEMA_VERSION: Final = 5  # v5 (Sprint 16.5): + simulation_window.polars_max_threads
_METRICS_ROUND_NDIGITS: Final = 8

# --------------------------------------------------------------------------
# Cache do subconjunto (ajuste da revisão da Sprint 7: hash dos parâmetros de
# seleção, pra nunca reusar em silêncio um subconjunto obsoleto).
# --------------------------------------------------------------------------


class StaleSubsetSelectionError(RuntimeError):
    """O cache de subconjunto em disco foi calculado com outros parâmetros de
    seleção -- reusar em silêncio esconderia uma mudança em `params.yaml` que
    deveria invalidar o subconjunto (ajuste da revisão da Sprint 7). A
    correção é apagar o cache ou rodar a seleção de novo antes de continuar,
    nunca ignorar a divergência.
    """


def _selection_params_hash(params: Params) -> str:
    """Hash determinístico só dos campos de `Params` que afetam
    `select_subset` -- não o arquivo inteiro: mudar `erp_baseline.factor`,
    por exemplo, não deveria invalidar um subconjunto que não depende disso.

    Escopo DIFERENTE do `params_hash` do `RunManifest` (Sprint 9) -- aquele
    hasheia `Params` inteiro, pra rastreabilidade; este hasheia só o que
    decide o subconjunto, pra servir de gatilho de cache. Mesmo nome de
    campo (`params_hash`) em dois arquivos, escopos diferentes de propósito
    -- não comparar um contra o outro.
    """
    payload = {
        "subset_selection": params.subset_selection.model_dump(mode="json"),
        "canonical_window_start": params.canonical.window_start.isoformat(),
        "canonical_window_end": params.canonical.window_end.isoformat(),
        "simulation_start_date": params.simulation.start_date.isoformat(),
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_or_select_subset(
    sales: pl.LazyFrame,
    items: pl.DataFrame,
    suppliers: pl.DataFrame,
    stock: pl.DataFrame,
    params: Params,
    *,
    cache_path: Path,
) -> SubsetSelectionResult:
    """Lê `cache_path` se existir e o hash bater; senão roda `select_subset`
    (que escaneia a tabela de vendas inteira) e grava o cache pra próxima vez.

    Levanta `StaleSubsetSelectionError` se o cache existir com um hash
    diferente do calculado agora -- nunca reusa em silêncio.
    """
    current_hash = _selection_params_hash(params)

    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        if cached["params_hash"] != current_hash:
            msg = (
                f"{cache_path} foi calculado com outros parâmetros de seleção "
                f"(hash salvo {cached['params_hash']!r} != hash atual {current_hash!r}). "
                "config/params.yaml mudou desde a última seleção -- apague o "
                "cache ou rode a seleção de novo antes de continuar; reusar em "
                "silêncio compararia braços com subconjuntos diferentes."
            )
            raise StaleSubsetSelectionError(msg)
        return SubsetSelectionResult(
            store_id=cached["store_id"],
            item_ids=tuple(cached["item_ids"]),
            funnel=pl.DataFrame(cached["funnel"]),
        )

    result = select_subset(sales, items, suppliers, stock, params)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "params_hash": current_hash,
                "store_id": result.store_id,
                "item_ids": list(result.item_ids),
                "funnel": result.funnel.to_dicts(),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return result


# --------------------------------------------------------------------------
# Registro de forecaster/policy (nomes de `experiments.arms` em params.yaml)
# --------------------------------------------------------------------------


def _build_forecaster(name: str, params: Params) -> Forecaster:
    if name == "naive":
        return NaiveForecaster(
            params.forecast_naive.moving_average_weeks,
            params.forecast_naive.min_residual_samples,
        )
    if name == "statistical":
        return StatisticalForecaster(
            level_window_weeks=params.forecast_statistical.level_window_weeks,
            seasonal_window_weeks=params.forecast_statistical.seasonal_window_weeks,
            min_residual_samples=params.forecast_statistical.min_residual_samples,
        )
    msg = f"forecaster desconhecido: {name!r}"
    raise ValueError(msg)


def _build_policy(name: str, params: Params, *, horizon_days: int, alpha: float) -> Policy:
    """`alpha` só é usado pelo braço `basestock` -- `erp_baseline` não deriva
    nada de quantil (ver docstring de `ErpBaselinePolicy`). Aceito
    incondicionalmente, em vez de opcional, para que `run_arm` não precise
    saber qual política vai consumir o valor antes de montá-la."""
    if name == "erp_baseline":
        return ErpBaselinePolicy(
            horizon_days=horizon_days,
            moving_average_weeks=params.forecast_naive.moving_average_weeks,
            factor=params.erp_baseline.factor,
            min_order_units=params.erp_baseline.min_order_units,
        )
    if name == "basestock":
        return BasestockPolicy(alpha=alpha, expected_window_days=horizon_days)
    msg = f"policy desconhecida: {name!r}"
    raise ValueError(msg)


def _quantile_gbm_retrain_dates(params: Params) -> list[date]:
    """Grade semanal de retreino (`model.retrain_cadence_days`), de
    `simulation.start_date` a `simulation.end_date` -- as únicas datas em que
    o `Simulator` de fato vai pedir uma previsão (Sprint 15)."""
    cadence = params.model.retrain_cadence_days
    dates: list[date] = []
    d = params.simulation.start_date
    while d <= params.simulation.end_date:
        dates.append(d)
        d += timedelta(days=cadence)
    return dates


def _build_quantile_gbm_registry(
    *,
    sales: pl.LazyFrame,
    items: pl.DataFrame,
    store_id: str,
    item_ids: list[str],
    horizon_by_item: dict[str, int],
    review_period_by_item: dict[str, int],
    calendar_locale: StoreLocale,
    holidays: pl.DataFrame,
    params: Params,
) -> tuple[QuantileModelRegistry, pl.DataFrame, dict[str, dict[date, dict[float, float]]]]:
    """Treina o modelo GLOBAL do braço 3 UMA VEZ, fora do loop por item (ver
    docstring de `motor.forecast.quantile_gbm`) -- `run_arm` chama isto antes
    de montar qualquer `Simulator`, só quando `arm.forecaster == 'quantile_gbm'`.
    Sprint 16: também PRÉ-COMPUTA, aqui, toda previsão que o braço vai pedir
    (`precompute_predictions`, batching de `booster.predict()`) -- mesma
    razão de o treino já acontecer fora do loop por item, mesmo lugar.

    Devolve também `sales_full_subset` (todas as colunas canônicas, inclusive
    `on_promo`) para o loop por item fatiar sem reler o parquet -- é a mesma
    ideia de `sales_subset` logo abaixo, só que com as colunas que
    `motor.features` precisa e `Simulator`/`InventoryState` não.
    """
    sales_full_subset = sales.filter(
        (pl.col("store_id") == store_id) & (pl.col("item_id").is_in(item_ids))
    ).collect()

    retrain_dates = _quantile_gbm_retrain_dates(params)
    config_hash = compute_config_hash(
        hyperparams=params.quantile_gbm,
        features_params=params.features,
        quantiles=params.model.quantiles,
        store_id=store_id,
        item_ids=item_ids,
        horizon_by_item=horizon_by_item,
    )
    registry = train_quantile_models(
        sales_full_subset,
        items,
        horizon_by_item,
        store_id=store_id,
        item_ids=item_ids,
        retrain_dates=retrain_dates,
        earliest_training_origin=params.canonical.window_start,
        origin_cadence_days=params.model.retrain_cadence_days,
        quantiles=params.model.quantiles,
        features_params=params.features,
        calendar_locale=calendar_locale,
        holidays=holidays,
        hyperparams=params.quantile_gbm,
        cache_dir=Path(params.quantile_gbm.model_cache_dir),
        config_hash=config_hash,
    )
    # decision_dates == retrain_dates: mesmo período (model.retrain_cadence_days
    # == review_period_days neste subconjunto) e mesma referência
    # (simulation.start_date) -- ver docstring de precompute_predictions. Se essa
    # igualdade um dia deixar de valer, predict_quantiles recusa alto e claro
    # (as_of sem previsão pré-computada), nunca silencioso.
    predictions = precompute_predictions(
        sales_full_subset,
        items,
        store_id=store_id,
        item_ids=item_ids,
        horizon_by_item=horizon_by_item,
        review_period_by_item=review_period_by_item,
        decision_dates=retrain_dates,
        quantiles=params.model.quantiles,
        features_params=params.features,
        calendar_locale=calendar_locale,
        holidays=holidays,
        registry=registry,
    )
    return registry, sales_full_subset, predictions


def _find_arm(params: Params, arm_name: str) -> ExperimentArmParams:
    for arm in params.experiments.arms:
        if arm.name == arm_name:
            return arm
    nomes = [arm.name for arm in params.experiments.arms]
    msg = f"braço {arm_name!r} não existe em experiments.arms (params.yaml); disponíveis: {nomes}"
    raise ValueError(msg)


def _evaluation_start(params: Params) -> date:
    """Fronteira do warmup -- fonte única (Sprint 9, ajuste da revisão): usada
    tanto pro `manifest.json` quanto pra filtrar as métricas financeiras.
    `run_arm` nunca filtra `events` por essa data antes de chamar
    `compute_financial_metrics`/`compute_portfolio_metrics` -- essas funções
    já filtram internamente (`motor.metrics.financial`, testado). Filtrar de
    novo aqui duplicaria a fronteira e arriscaria as duas contas divergirem
    se uma for editada sem a outra.
    """
    return params.simulation.start_date + timedelta(days=params.simulation.warmup_days)


# --------------------------------------------------------------------------
# Execução do braço
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ArmRunResult:
    """Saída de `run_arm`.

    `item_metrics`: uma linha por item, colunas de métricas financeiras
    (Sprint 8) MAIS `price`/`cost`/`margin_pct` (join com a economia do item
    já embutido) -- é a tabela que a Sprint 16 varre e a Sprint 17 usa pra
    montar a lista de compra, sem recalcular economia. Floats arredondados
    em `_METRICS_ROUND_NDIGITS` casas (ver `_round_float_columns`).
    """

    events: pl.DataFrame
    item_metrics: pl.DataFrame
    portfolio_metrics: PortfolioFinancialMetrics
    store_id: str
    item_ids: tuple[str, ...]
    quantile_gbm_registry: QuantileModelRegistry | None = None
    """Só presente quando `arm.forecaster == 'quantile_gbm'` -- carrega o
    contador de correção de não-cruzamento (`registry.correction`), lido por
    `_build_manifest`. `None` para os outros braços: não treinamos um modelo
    global só para alimentar um contador que nem existiria."""


def _events_to_dataframe(*, store_id: str, item_id: str, events: Sequence[object]) -> pl.DataFrame:
    rows = [asdict(e) for e in events]  # type: ignore[call-overload]
    df = pl.DataFrame(rows)
    return df.select(
        pl.lit(store_id).alias("store_id"),
        pl.lit(item_id).alias("item_id"),
        pl.all(),
    )


def _round_float_columns(
    df: pl.DataFrame, *, exclude: set[str], ndigits: int = _METRICS_ROUND_NDIGITS
) -> pl.DataFrame:
    """Arredonda toda coluna `Float64` (exceto `exclude`) em `ndigits` casas.

    Salvaguarda de determinismo, não decisão de precisão: agregação de
    ponto flutuante do polars (`.sum()`/`.mean()` em `group_by().agg()`) não
    garante ordem de soma estável entre execuções -- ver a medição registrada
    na revisão da Sprint 9 antes de mudar `ndigits`.
    """
    float_cols = [
        name
        for name, dtype in zip(df.columns, df.dtypes, strict=True)
        if dtype == pl.Float64 and name not in exclude
    ]
    return df.with_columns([pl.col(c).round(ndigits) for c in float_cols])


def _round_portfolio_metrics(
    portfolio: PortfolioFinancialMetrics, *, ndigits: int = _METRICS_ROUND_NDIGITS
) -> PortfolioFinancialMetrics:
    return replace(portfolio, **{f: round(v, ndigits) for f, v in asdict(portfolio).items()})


def run_arm(
    arm_name: str,
    params: Params,
    *,
    sales: pl.LazyFrame,
    items: pl.DataFrame,
    suppliers: pl.DataFrame,
    stock: pl.DataFrame,
    subset_cache_path: Path,
) -> ArmRunResult:
    """Roda `arm_name` (de `params.experiments.arms`) sobre o subconjunto real:
    um `Simulator` por par loja-item (mesmas premissas compartilhadas de
    `motor.experiments.shared.build_simulator_for_pair`), depois converte os
    eventos em métricas financeiras (`motor.metrics.financial`, Sprint 8).
    """
    arm = _find_arm(params, arm_name)
    subset = load_or_select_subset(
        sales, items, suppliers, stock, params, cache_path=subset_cache_path
    )
    item_ids = list(subset.item_ids)

    item_supplier = (
        items.filter(pl.col("item_id").is_in(item_ids))
        .select("item_id", "supplier_id")
        .join(
            suppliers.select("supplier_id", "lead_time_days", "review_period_days"),
            on="supplier_id",
            how="left",
        )
    )
    lead_time_by_item = dict(
        zip(item_supplier["item_id"], item_supplier["lead_time_days"], strict=True)
    )
    review_period_by_item = dict(
        zip(item_supplier["item_id"], item_supplier["review_period_days"], strict=True)
    )

    sales_subset = (
        sales.filter((pl.col("store_id") == subset.store_id) & (pl.col("item_id").is_in(item_ids)))
        .select("item_id", "date", "units_sold")
        .sort("item_id", "date")
        .collect()
    )

    horizon_by_item = {
        item_id: int(lead_time_by_item[item_id]) + int(review_period_by_item[item_id])
        for item_id in item_ids
    }

    quantile_gbm_registry: QuantileModelRegistry | None = None
    quantile_gbm_predictions: dict[str, dict[date, dict[float, float]]] | None = None
    if arm.forecaster == "quantile_gbm":
        raw_parquet_dir = Path(params.data.raw_parquet_dir)
        calendar_locale = load_store_locale(subset.store_id, raw_parquet_dir)
        holidays = load_holidays(raw_parquet_dir)
        quantile_gbm_registry, _sales_full_subset, quantile_gbm_predictions = (
            _build_quantile_gbm_registry(
                sales=sales,
                items=items,
                store_id=subset.store_id,
                item_ids=item_ids,
                horizon_by_item=horizon_by_item,
                review_period_by_item=review_period_by_item,
                calendar_locale=calendar_locale,
                holidays=holidays,
                params=params,
            )
        )

    event_frames: list[pl.DataFrame] = []
    for item_id in item_ids:
        demand = sales_subset.filter(pl.col("item_id") == item_id).select("date", "units_sold")
        lead_time_days = int(lead_time_by_item[item_id])
        review_period_days = int(review_period_by_item[item_id])
        horizon_days = horizon_by_item[item_id]

        if arm.forecaster == "quantile_gbm":
            assert quantile_gbm_predictions is not None
            forecaster: Forecaster = QuantileGbmForecaster(
                item_id=item_id,
                expected_horizon=horizon_days,
                precomputed=quantile_gbm_predictions[item_id],
            )
        else:
            forecaster = _build_forecaster(arm.forecaster, params)
        policy = _build_policy(
            arm.policy,
            params,
            horizon_days=horizon_days,
            alpha=params.economics.default_alpha,
        )

        simulator = build_simulator_for_pair(
            demand=demand,
            forecaster=forecaster,
            policy=policy,
            lead_time_days=lead_time_days,
            review_period_days=review_period_days,
            start=params.simulation.start_date,
            warmup_days=params.simulation.warmup_days,
            quantiles=params.model.quantiles,
        )
        events = simulator.run(params.simulation.start_date, params.simulation.end_date)
        event_frames.append(
            _events_to_dataframe(store_id=subset.store_id, item_id=item_id, events=events)
        )

    combined = pl.concat(event_frames)

    item_economics = build_item_economics(
        items.filter(pl.col("item_id").is_in(item_ids)).select("item_id", "category"),
        category_margin_pct=params.economics.category_margin_pct,
        default_margin_pct=params.economics.default_margin_pct,
        uniform_unit_price=params.economics.uniform_unit_price,
    )
    evaluation_start = _evaluation_start(params)
    item_metrics = compute_financial_metrics(
        combined,
        item_economics,
        evaluation_start=evaluation_start,
        capital_cost_annual=params.economics.capital_cost_annual,
    ).join(item_economics, on="item_id", how="left")
    item_metrics = _round_float_columns(item_metrics, exclude={"item_id"})

    portfolio_metrics = compute_portfolio_metrics(
        combined,
        item_economics,
        evaluation_start=evaluation_start,
        capital_cost_annual=params.economics.capital_cost_annual,
    )
    portfolio_metrics = _round_portfolio_metrics(portfolio_metrics)

    return ArmRunResult(
        events=combined,
        item_metrics=item_metrics,
        portfolio_metrics=portfolio_metrics,
        store_id=subset.store_id,
        item_ids=subset.item_ids,
        quantile_gbm_registry=quantile_gbm_registry,
    )


# --------------------------------------------------------------------------
# Manifesto autossuficiente (Sprint 9) -- mesmo padrão de
# motor.io.loaders.CanonicalManifest: premissas E resultados no mesmo
# arquivo, hash de código+parâmetros, hash dos parquets de entrada.
# --------------------------------------------------------------------------

_BASELINE_COVERAGE_CONTEXT = (
    "Como o baseline calibrado (factor=0.34, ver params.yaml/erp_baseline) já "
    "cobre 9.52 dos 10 dias da janela de risco (lead_time + review_period, "
    "razão 0.952), o ganho esperado dos braços 2 e 3 sobre este baseline NÃO "
    "deve vir de corrigir uma cobertura errada em dias -- este baseline não "
    "erra isso de forma grosseira nesta calibração. Tem que vir de onde o "
    "baseline é estruturalmente cego: reagir à forma da distribuição de "
    "demanda (previsão quantílica por item, em vez de um fator plano igual "
    "pra toda a base) e das regras de guarda. Se os braços futuros não "
    "superarem este baseline, a pergunta certa é se a previsão quantílica "
    "está de fato capturando risco que a média móvel não vê -- não se este "
    "baseline está artificialmente ruim."
)

_BASESTOCK_ALPHA_LIMITATION = (
    "BasestockPolicy usa economics.default_alpha, UNIFORME para todo item, mesmo com "
    "economics.category_alpha declarado no config -- decisão explícita da Sprint 12: "
    "misturar previsão nova (braço 2) com alpha por categoria na mesma mudança destruiria "
    "a atribuição do ganho financeiro entre os braços 2 e 3 (não daria para saber se a "
    "diferença de R$ vem da previsão ou do alpha). EFEITO: alpha uniforme deprime o "
    "resultado em categorias perecíveis de validade curta (alpha adequado seria mais baixo, "
    "~0.75-0.82, para pesar menos a ruptura frente à perda) e infla o resultado em "
    "mercearia seca (alpha adequado seria mais alto, ~0.92-0.97). A COMPARAÇÃO ENTRE BRAÇOS "
    "permanece válida porque o alpha é o mesmo nos três -- o NÍVEL ABSOLUTO de R$ não é "
    "interpretável por categoria. Remapeamento de category_alpha para as categorias reais "
    "fica para uma sprint de calibração dedicada, medido isoladamente contra este braço já "
    "congelado."
)

_QUANTILE_CROSSING_METHODOLOGY_NOTE = (
    "Medido antes de implementar (relatório da Sprint 15), sobre um fit piloto no "
    "subconjunto real -- números ESTÁTICOS, não recalculados a cada rodada (recalcular "
    "com 3000 rounds a cada execução do braço seria puro desperdício de tempo pra um "
    "diagnóstico que já não mudou entre as três variantes medidas). Três variantes "
    "lado a lado, porque a primeira medição (in-sample, 200 rounds) é sabidamente "
    "otimista de duas formas independentes: (A) in-sample, 200 rounds -- 34.84% das "
    "linhas com alguma inversão adjacente (q0.5>q0.8: 2.87%, q0.8>q0.9: 15.29%, "
    "q0.9>q0.95: 19.08%); (B) fora da amostra, mesmos boosters de (A), origem ~10 "
    "semanas depois do fim do treino -- 36.73% (6.18%, 16.36%, 18.55%); (C) in-sample, "
    "3000 rounds + learning_rate=0.03 (checa se (A) era subtreino) -- 33.94% (3.52%, "
    "14.10%, 18.63%). CONCLUSÃO: os três números são ESTÁVEIS entre si -- nem overfitting "
    "in-sample nem subtreino explicam a taxa medida. O cruzamento é estrutural (dois "
    "modelos independentes por linha, sem restrição de monotonicidade entre eles), não "
    "artefato de medição -- a correção de não-cruzamento (NonCrossingCorrection) não é "
    "cosmética, e o contador de quantas vezes ela atua nesta rodada (abaixo) é esperado "
    "ser grande, não raro."
)

_ZERO_TARGET_SHARE_LIMITATION = (
    "Medido antes de implementar (relatório da Sprint 15), sobre o subconjunto real: a "
    "proporção de janelas de risco com alvo zero (demanda acumulada = 0) é de só 0.30% "
    "(14.025 combinações item x origem semanal, 51 origens x 275 itens) -- 260 dos 275 "
    "itens NUNCA tiveram uma janela de risco zerada em nenhuma das 51 origens medidas. "
    "Isso NÃO é uma propriedade geral de demanda de varejo -- é consequência direta do "
    "critério de seleção do subconjunto de trabalho (subset_selection.density_threshold="
    "0.9, Sprint 4: só entram itens de demanda REGULAR). Um subconjunto de cauda mais "
    "longa (itens intermitentes, density_threshold mais baixo) teria proporção de zeros "
    "bem maior, e a pinball loss nos quantis baixos se comportaria de forma diferente "
    "-- não avaliado aqui, fora do escopo desta sprint. Não generalizar este número para "
    "'a demanda deste tipo de negócio raramente é zero' -- é 'o subconjunto ESCOLHIDO "
    "raramente tem demanda zero', por construção."
)

_PARAMS_HASH_SCOPE_NOTE = (
    "sha256 de Params inteiro (model_dump_json) -- NÃO é o mesmo hash nem o "
    "mesmo escopo do params_hash em subset_selection.json (esse é só "
    "subset_selection + canonical + simulation.start_date, usado como "
    "gatilho de cache). Mesmo nome de campo, escopos diferentes de "
    "propósito -- não comparar um contra o outro."
)

_QUANTILE_GRID_COUPLING_NOTE = (
    "Achado na revisão da Sprint 16, ao estender model.quantiles de "
    "[0.5, 0.8, 0.9, 0.95] para [0.5, 0.70, 0.80, 0.85, 0.90, 0.95]: "
    "NonCrossingCorrection.apply (motor.forecast.quantile_gbm) ordena os "
    "valores brutos de TODOS os quantis de active_quantiles e reatribui por "
    "RANK, não por identidade de quantil -- cada booster treina "
    "independente (pinball loss no seu próprio quantil, imune ao tamanho da "
    "grade), mas o valor que a política lê para, por exemplo, quantile=0.90 "
    "muda dependendo de quantos e quais OUTROS quantis estão na mesma grade, "
    "porque a correção mistura todos antes de reatribuir. Medido: braço 3 em "
    "lead_time=3, alpha=0.90 deu decision_metric=11.71267776 sob a grade "
    "antiga (4 quantis, Sprint 15) e 11.56804972 sob a grade nova (6 "
    "quantis) -- mesmo config, mesmos dados, só a grade mudou. CONSEQUÊNCIA: "
    "resultados do braço 3 (`forecaster=quantile_gbm`) só são comparáveis "
    "entre execuções com o MESMO active_quantiles abaixo. Nunca compare um "
    "decision_metric de braço 3 contra outro sem checar que a grade bate."
)


class SimulationWindowManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    start: date
    warmup_days: int
    evaluation_start: date
    end: date
    n_evaluation_days: int
    seed: int
    """`params.simulation.seed` (Sprint 16.5, Etapa 3.4/3.6) -- achado da
    revisão: faltava no manifesto inteiramente, não só nesta varredura.
    Autossuficiência (Sprint 9) inclui reproduzir a mesma execução daqui a
    um mês -- sem o seed registrado, "determinístico" era uma alegação sem
    como conferir a partir do próprio resultado."""
    polars_max_threads: int | None = None
    """`POLARS_MAX_THREADS` do processo que gerou este manifesto, lido de
    `os.environ` no momento da gravação (Sprint 16.5, Etapa 3.9) -- `None`
    quando a env var não estava setada (thread pool default do polars,
    tipicamente todos os núcleos). Achado da checagem de determinismo desta
    etapa: contagem de threads MEXE no último dígito de ponto flutuante dos
    eventos brutos (ordem de redução do polars) -- não muda `item_metrics`
    nem `decision_metric` (arredondados, ver `_round_float_columns`), mas é
    uma premissa de execução que demonstravelmente afeta o float, e a
    Sprint 9 pede que toda premissa ativa esteja no resumo, não só as que
    mudam o resultado que importa."""


class FinancialAssumptionsManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    uniform_unit_price: float
    capital_cost_annual: float
    daily_capital_cost_rate: float
    default_margin_pct: float
    category_margin_pct: dict[str, float]
    price_invariance_note: str
    scale_warning: str


class ErpBaselineCalibrationManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    factor: float
    min_order_units: float
    target_service_level: float
    moving_average_weeks: int
    coverage_days_implied: float
    coverage_context: str


class BasestockCalibrationManifest(BaseModel):
    """Premissas do braço de nível-alvo (Sprint 12) -- registrado no manifesto
    de TODO braço, independente do que estiver rodando (mesmo padrão de
    `erp_baseline_calibration`): documenta o que o braço 2 FARIA se fosse o
    braço ativo, para comparação, não só quando `arm == "estatistico_basestock"`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    alpha: float
    alpha_scope: str
    limitation: str


class QuantileGbmDiagnosticsManifest(BaseModel):
    """Diagnóstico do braço 3 (Sprint 15) -- SÓ presente quando
    `arm.forecaster == 'quantile_gbm'` (ao contrário de
    `erp_baseline_calibration`/`basestock_calibration`, que são sempre
    presentes): treinar o modelo global só para preencher um campo inerte
    num braço que nem o usa seria puro desperdício de computação, não
    documentação de graça.

    `crossing_methodology_note` e os três pares de números que ele descreve
    são ESTÁTICOS (medidos uma vez, no relatório da sprint) -- não
    recalculados a cada rodada. `n_correction_calls`/`n_correction_activations`
    são AO VIVO: contam de fato quantas previsões desta rodada específica
    passaram pela correção de não-cruzamento e quantas precisaram dela.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    crossing_methodology_note: str
    zero_target_share_limitation: str
    grid_coupling_note: str
    n_retrain_dates: int
    n_correction_calls: int
    n_correction_activations: int
    correction_activation_rate: float


class PortfolioResultsManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    margem_realizada_rs: float
    ruptura_rs: float
    perda_rs: float
    capital_medio_rs: float
    nivel_servico: float
    giro_anualizado: float
    carrying_cost_rs: float
    decision_metric: float


class ResultsManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    portfolio: PortfolioResultsManifest
    item_metrics_path: str


class RunManifest(BaseModel):
    """Resumo autossuficiente de uma execução de `run_arm` -- mesmo padrão de
    `motor.io.loaders.CanonicalManifest` (Sprint 3): premissas por extenso E
    resultado agregado no mesmo arquivo, hash de parâmetros, hash dos
    parquets de entrada, hash do commit do código.

    `generated_at`/`execution_seconds` são os únicos campos que variam entre
    duas execuções com o mesmo código/parâmetros/entrada -- mesma exceção
    documentada em `CanonicalManifest`, não uma regra nova.

    `execution_seconds` (Sprint 16, achado da revisão): `time.perf_counter()`,
    NÃO relógio de parede -- no Linux, `CLOCK_MONOTONIC` não conta tempo em
    que a máquina ficou suspensa, e `datetime.now()` conta (um run já
    registrou 34276s de relógio de parede para 2092s de computação real,
    porque a máquina dormiu no meio). `generated_at` continua timestamp de
    relógio de parede -- é o uso certo dele, não duração.

    `execution_seconds_clock_source` declara a fonte explícita -- "perf_counter"
    a partir desta versão do schema; um manifesto pré-existente (schema_version
    1, sem este campo -- ex.: a execução da Sprint 15, 2229.7s, e o que restou
    dela no snapshot `results/_archive/`) tem `execution_seconds` em relógio de
    parede e NÃO é comparável a um `execution_seconds` desta versão em diante.
    Duração sem fonte declarada é exatamente o tipo de número que engana
    silenciosamente três semanas depois -- não repetir isso.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int
    generated_at: datetime
    execution_seconds: float
    execution_seconds_clock_source: str = "perf_counter"
    git_commit_hash: str | None
    params_hash: str
    params_hash_scope: str

    arm: str
    forecaster: str
    policy: str
    store_id: str
    n_items: int
    item_ids: list[str]
    active_quantiles: list[float]
    """`params.model.quantiles` desta execução -- registrado explícito (Sprint
    16) porque o braço 3 (quantile_gbm) NÃO é comparável entre execuções com
    grades diferentes (ver `QuantileGbmDiagnosticsManifest.grid_coupling_note`);
    presente em todo manifesto, não só quando `forecaster == 'quantile_gbm'`,
    mesmo padrão de `basestock_calibration`."""

    simulation_window: SimulationWindowManifest
    shared_assumptions: dict[str, str]
    erp_baseline_calibration: ErpBaselineCalibrationManifest
    basestock_calibration: BasestockCalibrationManifest
    quantile_gbm_diagnostics: QuantileGbmDiagnosticsManifest | None = None
    financial_assumptions: FinancialAssumptionsManifest
    assumptions: AssumptionsRegistry
    """Registro auditável de premissas arbitradas (Sprint 16.5, Etapa 3.1,
    `motor.assumptions`) -- CAMPO OBRIGATÓRIO, sem default: um manifesto
    construído sem isto não valida, pydantic recusa a gravação com erro
    explícito nomeando o campo. Nunca um resultado publicado sem declarar
    o que, nele, é medido e o que é chute."""
    limitations: list[str]
    results: ResultsManifest

    input_files: dict[str, InputFileManifest]
    output_files: dict[str, OutputFileManifest]
    row_counts: dict[str, int]


def _git_commit_hash(repo_dir: Path) -> str | None:
    """Hash do commit HEAD do código, para o manifesto -- `None` quando o
    diretório não é um repositório git ou `git` não está disponível; nunca
    falha a geração do resumo por causa disso. Só lê o estado do git (`rev-parse
    HEAD`), não é um dos comandos proibidos para o agente nesta sessão.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _hash_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    """sha256 de um arquivo, lido em blocos -- nunca carrega o arquivo inteiro em memória."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_manifest(
    arm_name: str,
    params: Params,
    result: ArmRunResult,
    *,
    canonical_dir: Path,
    events_path: Path,
    item_metrics_path: Path,
    execution_seconds: float,
) -> RunManifest:
    arm = _find_arm(params, arm_name)
    evaluation_start = _evaluation_start(params)
    n_evaluation_days = (params.simulation.end_date - evaluation_start).days + 1

    input_files = {
        table: InputFileManifest(
            sha256=_hash_file(canonical_dir / f"{table}.parquet"),
            size_bytes=(canonical_dir / f"{table}.parquet").stat().st_size,
        )
        for table in ("sales", "items", "suppliers", "stock")
    }

    return RunManifest(
        schema_version=_RUN_MANIFEST_SCHEMA_VERSION,
        generated_at=datetime.now(UTC),
        execution_seconds=execution_seconds,
        git_commit_hash=_git_commit_hash(_REPO_ROOT),
        params_hash=hashlib.sha256(params.model_dump_json().encode("utf-8")).hexdigest(),
        params_hash_scope=_PARAMS_HASH_SCOPE_NOTE,
        arm=arm_name,
        forecaster=arm.forecaster,
        policy=arm.policy,
        store_id=result.store_id,
        n_items=len(result.item_ids),
        item_ids=list(result.item_ids),
        active_quantiles=list(params.model.quantiles),
        simulation_window=SimulationWindowManifest(
            start=params.simulation.start_date,
            warmup_days=params.simulation.warmup_days,
            evaluation_start=evaluation_start,
            end=params.simulation.end_date,
            n_evaluation_days=n_evaluation_days,
            seed=params.simulation.seed,
            polars_max_threads=(
                int(os.environ["POLARS_MAX_THREADS"])
                if "POLARS_MAX_THREADS" in os.environ
                else None
            ),
        ),
        shared_assumptions={
            "lead_time_review_period": (
                "por par loja-item, de suppliers.parquet (join via item.supplier_id)"
            ),
            "initial_stock_rule": (
                "avg_daily_demand_no_warmup x (lead_time_days + review_period_days), "
                "por par loja-item -- constante experimental idêntica em todos os "
                "braços (motor.experiments.shared.initial_stock_units)"
            ),
            "shelf_life": (
                "shelf_life_from_arrival_days=None para todo item -- premissa "
                "declarada: o canônico só tem Item.is_perishable (bool), nenhum "
                "dado de dias de validade. Nenhum item expira nesta sprint, em "
                "nenhum braço."
            ),
            "review_calendar": (
                "review_every_n_days(reference=simulation.start_date, "
                "period_days=review_period_days) -- não usa Supplier.order_days "
                "ainda (interação entre os dois é Sprint 11)"
            ),
        },
        erp_baseline_calibration=ErpBaselineCalibrationManifest(
            factor=params.erp_baseline.factor,
            min_order_units=params.erp_baseline.min_order_units,
            target_service_level=0.95,
            moving_average_weeks=params.forecast_naive.moving_average_weeks,
            coverage_days_implied=(
                params.erp_baseline.factor * params.forecast_naive.moving_average_weeks * 7
            ),
            coverage_context=_BASELINE_COVERAGE_CONTEXT,
        ),
        basestock_calibration=BasestockCalibrationManifest(
            alpha=params.economics.default_alpha,
            alpha_scope=(
                "economics.default_alpha, uniforme para todo item -- economics.category_alpha "
                "está declarado mas não é consumido nesta sprint (ver EconomicsParams)."
            ),
            limitation=_BASESTOCK_ALPHA_LIMITATION,
        ),
        quantile_gbm_diagnostics=(
            QuantileGbmDiagnosticsManifest(
                crossing_methodology_note=_QUANTILE_CROSSING_METHODOLOGY_NOTE,
                zero_target_share_limitation=_ZERO_TARGET_SHARE_LIMITATION,
                grid_coupling_note=_QUANTILE_GRID_COUPLING_NOTE,
                n_retrain_dates=len(_quantile_gbm_retrain_dates(params)),
                n_correction_calls=result.quantile_gbm_registry.correction.n_calls,
                n_correction_activations=result.quantile_gbm_registry.correction.n_corrected,
                correction_activation_rate=(
                    result.quantile_gbm_registry.correction.n_corrected
                    / result.quantile_gbm_registry.correction.n_calls
                    if result.quantile_gbm_registry.correction.n_calls > 0
                    else 0.0
                ),
            )
            if result.quantile_gbm_registry is not None
            else None
        ),
        financial_assumptions=FinancialAssumptionsManifest(
            uniform_unit_price=params.economics.uniform_unit_price,
            capital_cost_annual=params.economics.capital_cost_annual,
            daily_capital_cost_rate=params.economics.capital_cost_annual / 365,
            default_margin_pct=params.economics.default_margin_pct,
            category_margin_pct=dict(params.economics.category_margin_pct),
            price_invariance_note=PRICE_INVARIANCE_NOTE,
            scale_warning=SCALE_WARNING,
        ),
        assumptions=build_assumptions_registry(params),
        limitations=list(LIMITATIONS),
        results=ResultsManifest(
            portfolio=PortfolioResultsManifest(**asdict(result.portfolio_metrics)),
            item_metrics_path="item_metrics.parquet",
        ),
        input_files=input_files,
        output_files={
            "events": OutputFileManifest(size_bytes=events_path.stat().st_size),
            "item_metrics": OutputFileManifest(size_bytes=item_metrics_path.stat().st_size),
        },
        row_counts={
            "events": result.events.height,
            "item_metrics": result.item_metrics.height,
        },
    )


# --------------------------------------------------------------------------
# Execução + gravação (Sprint 16: corpo de `main()` extraído para ser
# compartilhado com `motor.experiments.sensitivity`, que roda o MESMO braço
# repetidas vezes com `lead_time`/`alpha` variados -- sem duplicar o
# caminho que decide o que vira arquivo em disco.)
# --------------------------------------------------------------------------


class ExistingResultError(RuntimeError):
    """`results_dir/<arm>/manifest.json` já existe -- `results/` não é
    versionado (`.gitignore`), então sobrescrever em silêncio destrói o único
    registro de um resultado já publicado sem deixar rastro (aconteceu de
    verdade na revisão da Sprint 16: um manifesto da Sprint 15 foi perdido
    assim, ver `results/_archive/`). A correção é arquivar o resultado atual
    antes de rodar de novo, ou passar `force=True`/`--force` quando
    sobrescrever é mesmo a intenção."""


def run_arm_and_save(
    arm_name: str,
    params: Params,
    *,
    sales: pl.LazyFrame,
    items: pl.DataFrame,
    suppliers: pl.DataFrame,
    stock: pl.DataFrame,
    subset_cache_path: Path,
    canonical_dir: Path,
    results_dir: Path,
    force: bool = False,
) -> RunManifest:
    """Roda `run_arm` e grava os três artefatos de sempre
    (`events.parquet`, `item_metrics.parquet`, `manifest.json`) em
    `results_dir/<arm_name>/`. Único caminho que escreve um braço em disco --
    `main()` (CLI) e `motor.experiments.sensitivity` chamam isto, nenhum dos
    dois duplica a lógica de gravação.
    """
    arm_dir = results_dir / arm_name
    manifest_path = arm_dir / "manifest.json"
    if manifest_path.exists() and not force:
        msg = (
            f"{manifest_path} já existe. Rodar de novo sem --force/force=True "
            "sobrescreveria um resultado publicado sem registro -- ver "
            "ExistingResultError."
        )
        raise ExistingResultError(msg)

    # perf_counter, não datetime.now() -- CLOCK_MONOTONIC no Linux não conta
    # tempo em que a máquina ficou suspensa (achado real desta sprint:
    # execution_seconds em relógio de parede chegou a registrar 34276s para
    # uma execução que só computou 2092s de verdade). Todo tempo que entra
    # em manifesto ou em projeção de custo usa perf_counter -- nunca
    # datetime.now() para DURAÇÃO (para TIMESTAMP, `generated_at` abaixo em
    # `_build_manifest` continua datetime.now(UTC), que é o uso certo dele).
    t0 = time.perf_counter()
    result = run_arm(
        arm_name,
        params,
        sales=sales,
        items=items,
        suppliers=suppliers,
        stock=stock,
        subset_cache_path=subset_cache_path,
    )
    execution_seconds = time.perf_counter() - t0

    arm_dir.mkdir(parents=True, exist_ok=True)
    events_path = arm_dir / "events.parquet"
    item_metrics_path = arm_dir / "item_metrics.parquet"
    result.events.write_parquet(events_path)
    result.item_metrics.write_parquet(item_metrics_path)

    manifest = _build_manifest(
        arm_name,
        params,
        result,
        canonical_dir=canonical_dir,
        events_path=events_path,
        item_metrics_path=item_metrics_path,
        execution_seconds=execution_seconds,
    )
    manifest_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False)
    )
    return manifest


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Roda um braço de experimento completo.")
    parser.add_argument(
        "--arm", required=True, help="Nome do braço em experiments.arms (params.yaml)"
    )
    parser.add_argument("--params", type=Path, default=Path("config/params.yaml"))
    parser.add_argument("--results-dir", type=Path, default=Path("results"))
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "sobrescreve --results-dir/--arm/manifest.json se já existir (ver ExistingResultError)"
        ),
    )
    args = parser.parse_args(argv)

    params = load_params(args.params)
    canonical_dir = Path(params.data.canonical_dir)
    sales = pl.scan_parquet(canonical_dir / "sales.parquet")
    items = pl.read_parquet(canonical_dir / "items.parquet")
    suppliers = pl.read_parquet(canonical_dir / "suppliers.parquet")
    stock = pl.read_parquet(canonical_dir / "stock.parquet")

    subset_cache_path = args.results_dir / "subset_selection.json"

    manifest = run_arm_and_save(
        args.arm,
        params,
        sales=sales,
        items=items,
        suppliers=suppliers,
        stock=stock,
        subset_cache_path=subset_cache_path,
        canonical_dir=canonical_dir,
        results_dir=args.results_dir,
        force=args.force,
    )

    print(
        f"{args.arm}: {manifest.n_items} itens, loja {manifest.store_id} -> "
        f"{args.results_dir / args.arm} "
        f"(decision_metric={manifest.results.portfolio.decision_metric})"
    )


if __name__ == "__main__":
    main()

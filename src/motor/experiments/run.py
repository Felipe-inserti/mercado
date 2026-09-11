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
import subprocess
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final

import polars as pl
from pydantic import BaseModel, ConfigDict

from motor.config import ExperimentArmParams, Params, load_params
from motor.experiments.shared import build_simulator_for_pair
from motor.forecast.base import Forecaster
from motor.forecast.naive import NaiveForecaster
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
_RUN_MANIFEST_SCHEMA_VERSION: Final = 1
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

    event_frames: list[pl.DataFrame] = []
    for item_id in item_ids:
        demand = sales_subset.filter(pl.col("item_id") == item_id).select("date", "units_sold")
        lead_time_days = int(lead_time_by_item[item_id])
        review_period_days = int(review_period_by_item[item_id])
        horizon_days = lead_time_days + review_period_days

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

_PARAMS_HASH_SCOPE_NOTE = (
    "sha256 de Params inteiro (model_dump_json) -- NÃO é o mesmo hash nem o "
    "mesmo escopo do params_hash em subset_selection.json (esse é só "
    "subset_selection + canonical + simulation.start_date, usado como "
    "gatilho de cache). Mesmo nome de campo, escopos diferentes de "
    "propósito -- não comparar um contra o outro."
)


class SimulationWindowManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    start: date
    warmup_days: int
    evaluation_start: date
    end: date
    n_evaluation_days: int


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
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int
    generated_at: datetime
    execution_seconds: float
    git_commit_hash: str | None
    params_hash: str
    params_hash_scope: str

    arm: str
    forecaster: str
    policy: str
    store_id: str
    n_items: int
    item_ids: list[str]

    simulation_window: SimulationWindowManifest
    shared_assumptions: dict[str, str]
    erp_baseline_calibration: ErpBaselineCalibrationManifest
    basestock_calibration: BasestockCalibrationManifest
    financial_assumptions: FinancialAssumptionsManifest
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
        simulation_window=SimulationWindowManifest(
            start=params.simulation.start_date,
            warmup_days=params.simulation.warmup_days,
            evaluation_start=evaluation_start,
            end=params.simulation.end_date,
            n_evaluation_days=n_evaluation_days,
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
        financial_assumptions=FinancialAssumptionsManifest(
            uniform_unit_price=params.economics.uniform_unit_price,
            capital_cost_annual=params.economics.capital_cost_annual,
            daily_capital_cost_rate=params.economics.capital_cost_annual / 365,
            default_margin_pct=params.economics.default_margin_pct,
            category_margin_pct=dict(params.economics.category_margin_pct),
            price_invariance_note=PRICE_INVARIANCE_NOTE,
            scale_warning=SCALE_WARNING,
        ),
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
# CLI
# --------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Roda um braço de experimento completo.")
    parser.add_argument(
        "--arm", required=True, help="Nome do braço em experiments.arms (params.yaml)"
    )
    parser.add_argument("--params", type=Path, default=Path("config/params.yaml"))
    parser.add_argument("--results-dir", type=Path, default=Path("results"))
    args = parser.parse_args(argv)

    params = load_params(args.params)
    canonical_dir = Path(params.data.canonical_dir)
    sales = pl.scan_parquet(canonical_dir / "sales.parquet")
    items = pl.read_parquet(canonical_dir / "items.parquet")
    suppliers = pl.read_parquet(canonical_dir / "suppliers.parquet")
    stock = pl.read_parquet(canonical_dir / "stock.parquet")

    subset_cache_path = args.results_dir / "subset_selection.json"

    t0 = datetime.now(UTC)
    result = run_arm(
        args.arm,
        params,
        sales=sales,
        items=items,
        suppliers=suppliers,
        stock=stock,
        subset_cache_path=subset_cache_path,
    )
    execution_seconds = (datetime.now(UTC) - t0).total_seconds()

    arm_dir = args.results_dir / args.arm
    arm_dir.mkdir(parents=True, exist_ok=True)
    events_path = arm_dir / "events.parquet"
    item_metrics_path = arm_dir / "item_metrics.parquet"
    result.events.write_parquet(events_path)
    result.item_metrics.write_parquet(item_metrics_path)

    manifest = _build_manifest(
        args.arm,
        params,
        result,
        canonical_dir=canonical_dir,
        events_path=events_path,
        item_metrics_path=item_metrics_path,
        execution_seconds=execution_seconds,
    )
    (arm_dir / "manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False)
    )

    print(
        f"{args.arm}: {len(result.item_ids)} itens, loja {result.store_id} -> {arm_dir} "
        f"(decision_metric={result.portfolio_metrics.decision_metric})"
    )


if __name__ == "__main__":
    main()

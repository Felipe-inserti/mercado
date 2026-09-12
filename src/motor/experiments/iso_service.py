"""Comparação iso-serviço, braços 2 e 3 contra o baseline (Sprint 17,
Etapas 3.10-3.13).

ESCOPO -- UMA célula só, deliberadamente
-----------------------------------------
`lead_time_days=7`, `review_period_days=14`. A tabela de 8 células da Sprint
16.5 (`results/sensibilidade_dirigida`) compara os braços em pontos
DIFERENTES da curva serviço x capital -- o baseline calibrado a ~95% de
serviço contra os braços 2/3 rodando em `economics.default_alpha=0.90`
arbitrário. A comparação correta precisa fixar o serviço e comparar o
capital/decision_metric no MESMO ponto. Isto é caro (calibrar alpha por
braço, por célula), então a Etapa 3.10-3.12 mediu isto rigorosamente numa
única célula em vez de espalhar o orçamento por 8 mal medidas. Generalizar
para outras combinações de lead_time/review_period é HIPÓTESE, não
resultado -- ver `results/iso_servico/README.md`.

DUAS GRADES, DUAS GRANULARIDADES -- por quê
---------------------------------------------
Braço 2 (estatístico, sem correção de não-cruzamento): seguro estender
`model.quantiles` para um valor único fora da grade de produção
(`build_arm2_single_alpha_params`) -- sem acoplamento entre quantis, uma
grade fina (0,60-0,90, passo 0,02) custa 16 avaliações independentes sem
reabrir nada.

Braço 3 (quantile_gbm, com correção de não-cruzamento por rank): estender
`model.quantiles` reabre o acoplamento documentado em
`motor.experiments.run._QUANTILE_GRID_COUPLING_NOTE` -- resultados deixariam
de ser comparáveis com o resto do projeto sem um teste de equivalência
estilo Sprint 16. Por isso o braço 3 usa só os alphas JÁ presentes na grade
de produção (`ARM3_ALPHA_GRID` -- 0,50/0,70/0,80/0,85/0,90),
`build_directed_cell_params` (`motor.experiments.sensitivity`), sem tocar
`model.quantiles`. Grade mais grossa (5 pontos vs. 16) é o preço de não
reabrir o acoplamento -- ver `motor.experiments.sensitivity` para o
raciocínio completo.

Consequência prática: a distância ao alvo de serviço do braço 2 (0,018 p.p.)
e a do braço 3 (0,411 p.p., mais próximo dos dois vizinhos que emolduram o
alvo) não são comparáveis em precisão. A comparação de cada braço contra o
baseline, no seu próprio ponto iso-serviço, é sólida; braço 2 x braço 3
entre si é indicativa, não conclusiva -- ver `README.md`.

Fatores de calibração do ERP (`CELL_ERP_FACTOR`/`CELL_ERP_MIN_ORDER_UNITS`)
são os já recalibrados para esta célula na Etapa 3.4
(`results/sensibilidade_dirigida/lt7_rp14/erp_baseline/manifest.json` ->
`erp_baseline_calibration`) -- reutilizados aqui, não recalibrados de novo.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Final

import polars as pl

from motor.config import Params, load_params
from motor.experiments.run import ArmRunResult, run_arm
from motor.experiments.sensitivity import (
    build_directed_cell_params,
    override_supplier_lead_time,
    override_supplier_review_period,
)

CELL_LEAD_TIME_DAYS: Final[int] = 7
CELL_REVIEW_PERIOD_DAYS: Final[int] = 14
CELL_ERP_FACTOR: Final[float] = 0.8
CELL_ERP_MIN_ORDER_UNITS: Final[float] = 0.0

# Alvo de serviço do baseline nesta célula -- fonte:
# results/sensibilidade_dirigida/lt7_rp14/erp_baseline/manifest.json,
# results.portfolio.nivel_servico. Repetido aqui como constante (não lido do
# manifesto em runtime) para que este módulo não dependa de um arquivo de
# resultado existir -- é usado só como referência textual/teste, nunca em
# lugar do valor medido de fato.
BASELINE_NIVEL_SERVICO_LT7_RP14: Final[float] = 0.9485436
BASELINE_DECISION_METRIC_LT7_RP14: Final[float] = 7.08751197
BASELINE_CAPITAL_MEDIO_RS_LT7_RP14: Final[float] = 672427.37257384

ARM2_ALPHA_GRID: Final[tuple[float, ...]] = tuple(round(0.60 + 0.02 * i, 2) for i in range(16))
"""0,60 a 0,90, passo 0,02 -- Etapa 3.11/3.12: a grade original (0,70-0,90)
não emoldurava o alvo (todo o range ficava acima); estendida para baixo
depois de relatado e aprovado (ver motor.experiments.sensitivity para a
distinção entre estender por justiça de teste vs. por resultado favorável)."""

ARM2_CHOSEN_ALPHA: Final[float] = 0.66
"""Mais próximo do alvo de serviço do baseline entre os 16 pontos de
ARM2_ALPHA_GRID -- distância 0,018 p.p."""

ARM3_ALPHA_GRID: Final[tuple[float, ...]] = (0.50, 0.70, 0.80, 0.85, 0.90)
"""Únicos valores já presentes em model.quantiles de produção -- grade
'segura', sem reabrir a correção de não-cruzamento (ver docstring do
módulo)."""

ARM3_CLOSEST_ALPHA: Final[float] = 0.70
"""Mais próximo do alvo entre os 5 pontos de ARM3_ALPHA_GRID -- distância
0,411 p.p. O alvo cai entre 0,70 e 0,80 (vão de 0,10); ambos os vizinhos já
mostram inversão do gap contra o baseline, então a imprecisão não muda a
conclusão qualitativa (ver README.md)."""


@dataclass(frozen=True)
class CanonicalTables:
    """As quatro tabelas canônicas mais o cache de seleção de subconjunto --
    agrupadas porque toda função deste módulo que roda uma célula precisa
    das cinco juntas."""

    sales: pl.LazyFrame
    items: pl.DataFrame
    suppliers: pl.DataFrame
    stock: pl.DataFrame
    subset_cache_path: Path


def load_canonical_tables(
    params: Params, *, subset_cache_path: Path | None = None
) -> CanonicalTables:
    """Carrega as quatro tabelas canônicas de `params.data.canonical_dir`.

    `subset_cache_path` default (`results/subset_selection.json`) é o mesmo
    arquivo compartilhado por `motor.experiments.sensitivity` -- reusar o
    cache já quente evita reselecionar o subconjunto.
    """
    canonical_dir = Path(params.data.canonical_dir)
    return CanonicalTables(
        sales=pl.scan_parquet(canonical_dir / "sales.parquet"),
        items=pl.read_parquet(canonical_dir / "items.parquet"),
        suppliers=pl.read_parquet(canonical_dir / "suppliers.parquet"),
        stock=pl.read_parquet(canonical_dir / "stock.parquet"),
        subset_cache_path=subset_cache_path or Path("results/subset_selection.json"),
    )


def cell_suppliers(
    suppliers: pl.DataFrame,
    *,
    lead_time_days: int = CELL_LEAD_TIME_DAYS,
    review_period_days: int = CELL_REVIEW_PERIOD_DAYS,
) -> pl.DataFrame:
    """`suppliers` com lead_time/review_period sobrescritos para a célula --
    mesmas duas funções de `motor.experiments.sensitivity`, compostas."""
    return override_supplier_review_period(
        override_supplier_lead_time(suppliers, lead_time_days), review_period_days
    )


def build_arm2_single_alpha_params(base_params: Params, alpha: float) -> Params:
    """`Params` do braço 2 (estatístico) para UM alpha fora da grade de
    produção -- `model.quantiles=[alpha]` (grade de um único valor).

    Seguro só porque o braço 2 (`motor.forecast.statistical`) não tem
    correção de não-cruzamento entre quantis -- não existe acoplamento para
    reabrir (ver docstring do módulo). NUNCA usar este padrão para o braço 3;
    `build_directed_cell_params` (`motor.experiments.sensitivity`), que
    preserva a grade de produção inteira, é o jeito seguro para ele.

    `model.retrain_cadence_days` é amarrado a `CELL_REVIEW_PERIOD_DAYS`
    (mesma razão de `build_cell_params`/`build_directed_cell_params`: sem
    isto, `_quantile_gbm_retrain_dates` desacopla de `review_period_days` do
    fornecedor -- não afeta o braço 2 em si, mas mantém os `Params` desta
    célula idênticos em estrutura aos do braço 3 para comparação).
    """
    return base_params.model_copy(
        update={
            "model": base_params.model.model_copy(
                update={"retrain_cadence_days": CELL_REVIEW_PERIOD_DAYS, "quantiles": [alpha]}
            ),
            "erp_baseline": base_params.erp_baseline.model_copy(
                update={"factor": CELL_ERP_FACTOR, "min_order_units": CELL_ERP_MIN_ORDER_UNITS}
            ),
            "economics": base_params.economics.model_copy(update={"default_alpha": alpha}),
        }
    )


def build_arm3_alpha_params(base_params: Params, alpha: float) -> Params:
    """`Params` do braço 3 (quantile_gbm) para um alpha da grade SEGURA
    (`ARM3_ALPHA_GRID`) -- delega a `build_directed_cell_params`, que valida
    que `alpha` está em `model.quantiles` e preserva a grade inteira."""
    return build_directed_cell_params(
        base_params,
        lead_time_days=CELL_LEAD_TIME_DAYS,
        review_period_days=CELL_REVIEW_PERIOD_DAYS,
        erp_factor=CELL_ERP_FACTOR,
        erp_min_order_units=CELL_ERP_MIN_ORDER_UNITS,
        alpha=alpha,
    )


def run_arm2_alpha_point(
    alpha: float, *, base_params: Params, tables: CanonicalTables
) -> ArmRunResult:
    """Roda o braço 2 (estatístico) em `alpha`, célula lt=7/rp=14."""
    cell_params = build_arm2_single_alpha_params(base_params, alpha)
    return run_arm(
        "estatistico_basestock",
        cell_params,
        sales=tables.sales,
        items=tables.items,
        suppliers=cell_suppliers(tables.suppliers),
        stock=tables.stock,
        subset_cache_path=tables.subset_cache_path,
    )


def run_arm3_alpha_point(
    alpha: float, *, base_params: Params, tables: CanonicalTables
) -> ArmRunResult:
    """Roda o braço 3 (quantile_gbm) em `alpha` da grade segura, célula
    lt=7/rp=14."""
    cell_params = build_arm3_alpha_params(base_params, alpha)
    return run_arm(
        "quantile_gbm_basestock",
        cell_params,
        sales=tables.sales,
        items=tables.items,
        suppliers=cell_suppliers(tables.suppliers),
        stock=tables.stock,
        subset_cache_path=tables.subset_cache_path,
    )


def point_summary(
    *,
    arm: str,
    alpha: float,
    active_quantiles: list[float],
    seed: int,
    polars_max_threads: int | None,
    result: ArmRunResult,
    segundos: float,
) -> dict[str, Any]:
    """Resumo autossuficiente de UM ponto (alpha) -- todo campo que o
    manifesto padrão (`motor.experiments.run.RunManifest`) exige para
    determinismo/premissas, mais os campos específicos desta etapa. Usado
    tanto pela grade fina do braço 2 quanto pela segura do braço 3, para que
    os dois produzam exatamente o mesmo formato."""
    p = result.portfolio_metrics
    return {
        "arm": arm,
        "alpha": alpha,
        "lead_time_days": CELL_LEAD_TIME_DAYS,
        "review_period_days": CELL_REVIEW_PERIOD_DAYS,
        "erp_factor": CELL_ERP_FACTOR,
        "erp_min_order_units": CELL_ERP_MIN_ORDER_UNITS,
        "active_quantiles": active_quantiles,
        "seed": seed,
        "polars_max_threads": polars_max_threads,
        "nivel_servico": p.nivel_servico,
        "decision_metric": p.decision_metric,
        "capital_medio_rs": p.capital_medio_rs,
        "segundos": segundos,
    }


def compute_item_decomposition(
    events: pl.DataFrame, item_metrics: pl.DataFrame, *, evaluation_start: Any
) -> pl.DataFrame:
    """`item_metrics` (uma linha por item, decision_metric já calculado)
    cruzado com a proporção de dias com venda (`sold > 0`) por item, no
    período pós-warmup (`day >= evaluation_start`) -- responde se a
    vantagem do braço vem de uma cauda de itens irregulares ou é uniforme
    pelo portfólio (Etapa 3.12/3.13).

    Função pura, testável sem rodar o simulador -- recebe `events`/
    `item_metrics` já prontos (mesmo formato de `ArmRunResult`).
    """
    dias_com_venda = (
        events.filter(pl.col("day") >= evaluation_start)
        .group_by("item_id")
        .agg(
            pl.len().alias("dias_avaliados"),
            (pl.col("sold") > 0).sum().alias("dias_com_venda"),
        )
        .with_columns(
            (pl.col("dias_com_venda") / pl.col("dias_avaliados")).alias("pct_dias_com_venda")
        )
    )
    return item_metrics.join(dias_com_venda, on="item_id", how="left").sort(
        "decision_metric", descending=True
    )


def evaluation_start_of(params: Params) -> Any:
    """Mesma fronteira de warmup que `motor.experiments.run._evaluation_start`
    -- duplicada aqui (não importada, `_evaluation_start` é privada do outro
    módulo) porque é uma soma de duas premissas de `params.simulation`, não
    lógica de negócio nova."""
    return params.simulation.start_date + timedelta(days=params.simulation.warmup_days)


# --------------------------------------------------------------------------
# CLI -- regenera qualquer ponto sem depender de diretório de job (Etapa
# 3.13: "nada da Etapa 3 pode depender de um diretório de job").
# --------------------------------------------------------------------------


def _run_point(
    arm: str, alpha: float, *, params_path: Path, output_path: Path, polars_max_threads: int | None
) -> dict[str, Any]:
    base_params = load_params(params_path)
    tables = load_canonical_tables(base_params)
    t0 = time.perf_counter()
    if arm == "estatistico_basestock":
        result = run_arm2_alpha_point(alpha, base_params=base_params, tables=tables)
        active_quantiles = [alpha]
    elif arm == "quantile_gbm_basestock":
        result = run_arm3_alpha_point(alpha, base_params=base_params, tables=tables)
        active_quantiles = list(build_arm3_alpha_params(base_params, alpha).model.quantiles)
    else:
        msg = f"arm={arm!r} não suportado -- use estatistico_basestock ou quantile_gbm_basestock"
        raise ValueError(msg)
    segundos = time.perf_counter() - t0

    summary = point_summary(
        arm=arm,
        alpha=alpha,
        active_quantiles=active_quantiles,
        seed=base_params.simulation.seed,
        polars_max_threads=polars_max_threads,
        result=result,
        segundos=segundos,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2))
    return summary


def _run_item_decomposition(
    alpha: float, *, params_path: Path, output_dir: Path, polars_max_threads: int | None
) -> dict[str, Any]:
    base_params = load_params(params_path)
    tables = load_canonical_tables(base_params)
    result = run_arm2_alpha_point(alpha, base_params=base_params, tables=tables)
    item_table = compute_item_decomposition(
        result.events, result.item_metrics, evaluation_start=evaluation_start_of(base_params)
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    slug = f"{alpha:.2f}".replace(".", "")
    item_table.write_parquet(output_dir / f"item_decomposition_alpha{slug}.parquet")
    item_table.write_csv(output_dir / f"item_decomposition_alpha{slug}.csv")

    corr = item_table.select(
        pl.corr("decision_metric", "pct_dias_com_venda", method="spearman").alias("spearman")
    ).item()
    resumo = {
        "arm": "estatistico_basestock",
        "alpha": alpha,
        "lead_time_days": CELL_LEAD_TIME_DAYS,
        "review_period_days": CELL_REVIEW_PERIOD_DAYS,
        "erp_factor": CELL_ERP_FACTOR,
        "erp_min_order_units": CELL_ERP_MIN_ORDER_UNITS,
        "active_quantiles": [alpha],
        "seed": base_params.simulation.seed,
        "polars_max_threads": polars_max_threads,
        "n_itens": item_table.height,
        "spearman_decision_metric_vs_pct_dias_com_venda": corr,
        "decision_metric_portfolio": result.portfolio_metrics.decision_metric,
        "decision_metric_item_min": item_table["decision_metric"].min(),
        "decision_metric_item_max": item_table["decision_metric"].max(),
        "decision_metric_item_mediana": item_table["decision_metric"].median(),
        "decision_metric_item_p10": item_table["decision_metric"].quantile(0.10),
        "decision_metric_item_p90": item_table["decision_metric"].quantile(0.90),
    }
    (output_dir / f"resumo_decomposicao_alpha{slug}.json").write_text(
        json.dumps(resumo, indent=2, default=str)
    )
    return resumo


def consolidate_points(point_paths: Sequence[Path]) -> pl.DataFrame:
    """Lê uma lista de JSONs no formato de `point_summary` e devolve uma
    tabela ordenada por `alpha` -- a curva completa alpha x serviço x
    decision_metric x capital que vai para `results/iso_servico/`."""
    rows = [json.loads(p.read_text()) for p in point_paths]
    return pl.DataFrame(rows).sort("alpha")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Comparação iso-serviço, célula lead_time=7/review_period=14 (Sprint 17, "
            "Etapas 3.10-3.13)."
        )
    )
    parser.add_argument("--params", type=Path, default=Path("config/params.yaml"))
    parser.add_argument(
        "--arm", choices=["estatistico_basestock", "quantile_gbm_basestock"], help="braço do ponto"
    )
    parser.add_argument("--alpha", type=float, help="alpha do ponto")
    parser.add_argument("--output", type=Path, help="destino do JSON (--run-point)")
    parser.add_argument(
        "--run-point", action="store_true", help="roda UM ponto (--arm, --alpha, --output)"
    )
    parser.add_argument(
        "--item-decomposition",
        action="store_true",
        help="decomposição por item do braço 2 em --alpha, grava em --output-dir",
    )
    parser.add_argument("--output-dir", type=Path, help="diretório de saída (--item-decomposition)")
    args = parser.parse_args(argv)

    polars_max_threads = (
        int(os.environ["POLARS_MAX_THREADS"]) if "POLARS_MAX_THREADS" in os.environ else None
    )

    if args.run_point:
        if not args.arm or args.alpha is None or not args.output:
            parser.error("--run-point precisa de --arm, --alpha e --output")
        summary = _run_point(
            args.arm,
            args.alpha,
            params_path=args.params,
            output_path=args.output,
            polars_max_threads=polars_max_threads,
        )
        print(json.dumps(summary, indent=2))
        return

    if args.item_decomposition:
        if args.alpha is None or not args.output_dir:
            parser.error("--item-decomposition precisa de --alpha e --output-dir")
        resumo = _run_item_decomposition(
            args.alpha,
            params_path=args.params,
            output_dir=args.output_dir,
            polars_max_threads=polars_max_threads,
        )
        print(json.dumps(resumo, indent=2, default=str))
        return

    parser.error(
        "nada a fazer -- use --run-point (--arm/--alpha/--output) ou "
        "--item-decomposition (--alpha/--output-dir)"
    )


if __name__ == "__main__":
    main()

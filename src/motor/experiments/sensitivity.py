"""Varredura de sensibilidade em `lead_time` e `alpha` (Sprint 16).

Dois eixos:
    lead_time_days: 3, 4, 6, 8, 10 (sobrescrito em `suppliers`, uniforme --
        hoje já é uniforme em 3, vindo de
        `supplier_assumptions.default_lead_time_days`, ver params.yaml)
    alpha (razão custo-faltar/custo-sobrar, materializada como
        `economics.default_alpha`): 0.70, 0.80, 0.85, 0.90, 0.95

Os três braços de `experiments.arms` (params.yaml) em cada célula --
5 x 5 x 3 = 75 células. Cada célula reusa `run_arm_and_save`
(`motor.experiments.run`, Sprint 9/16) -- NENHUM caminho paralelo que decide
o que vira arquivo em disco; só os parâmetros de entrada (`Params`,
`suppliers`) variam por célula.

GRADE DE QUANTIS -- decisão da revisão desta sprint, depois do achado do
acoplamento por rank na correção de não-cruzamento do braço 3 (ver
`motor.experiments.run._QUANTILE_GRID_COUPLING_NOTE`): `model.quantiles` é
uma grade ÚNICA e global,
`[0.5, 0.70, 0.80, 0.85, 0.90, 0.95]` (params.yaml), que já cobre todo alpha
desta varredura. Nenhuma célula usa uma grade própria -- variar a grade por
célula reabriria o acoplamento (resultados de braço 3 deixariam de ser
comparáveis ENTRE células, que é o produto desta sprint).

CONSEQUÊNCIA DE CACHE (a que interessa para o custo): como `alpha` não entra
em `compute_config_hash` nem no treino do braço 3 (só seleciona qual quantil
BasestockPolicy lê na decisão -- os boosters são por quantil, não por alpha),
as 5 células de alpha de um mesmo `lead_time` compartilham o MESMO
`QuantileModelRegistry` em cache -- 1 treino real por `lead_time` (5 no
total), não 1 por célula (25). Verificado empiricamente em `measure_one`
antes de assumir.

PARALELIZAÇÃO (Sprint 16, revisão) -- unidade de paralelismo é `(lead_time,
arm)`, NÃO a célula: dentro de um worker, os 5 alphas de um `(lead_time, arm)`
rodam em SÉRIE. Uniforme para os três braços (não só o 3) -- alpha não muda o
custo de nenhum deles (só o valor que a política lê depois da previsão já
calculada para todos os quantis da grade), e ter uma regra só é mais simples
que ter uma exceção por braço. 5 lead_times x 3 braços = 15 unidades.

Por que isto evita disputa de escrita SEM lock: o hash de cache do braço 3
depende de `horizon_by_item` (corrigido na Etapa 2 desta sprint) -- lead_times
diferentes têm horizontes diferentes, logo diretórios de cache diferentes,
por construção. Dentro de uma unidade (um lead_time fixo), os 5 alphas em
série significam que a primeira célula treina (cache frio, escreve) e as
quatro seguintes só leem (cache quente) -- nunca duas escritas concorrentes
no mesmo diretório. A ÚNICA disputa de escrita real da varredura é
`subset_selection.json` (compartilhado por TODAS as 75 células) -- por isso
`warm_subset_cache` roda em série, explícita, ANTES de qualquer worker.

Cada worker é um PROCESSO DO SISTEMA OPERACIONAL (`subprocess.Popen`, não
`multiprocessing`/`ProcessPoolExecutor`) -- de propósito: `POLARS_MAX_THREADS`
só tem efeito se estiver no ambiente ANTES do processo Python arrancar (lido
na inicialização do módulo `polars`, não em tempo de execução -- confirmado:
setar a env var depois de `import polars` já feito não muda nada). Com
`multiprocessing` (fork ou spawn), o processo filho pode herdar ou reimportar
`polars` antes de qualquer código de inicialização nosso rodar, sem garantia
de ordem. `subprocess.Popen(..., env=...)` garante a env var no processo
ANTES do interpretador Python sequer iniciar -- sem ambiguidade de ordem.

CLI:
    python -m motor.experiments.sensitivity --measure-one
        roda um pequeno plano de sondagem (não a varredura completa): mede
        custo real por braço, confirma o compartilhamento de cache entre
        alphas do mesmo lead_time, e projeta o custo das 75 células.
    python -m motor.experiments.sensitivity --run-unit --lead-time N --arm ARM
        roda os alphas de UMA unidade (lead_time, arm) em série neste
        processo -- é o que --run-grid dispara em subprocessos paralelos;
        chamável sozinho para depurar uma unidade.
    python -m motor.experiments.sensitivity --run-grid --workers N
        varredura completa (75 células), paralelizada por unidade
        (lead_time, arm). Retomada idempotente: pula unidade cujas 5 células
        já têm manifesto sob a mesma active_quantiles.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import polars as pl

import motor.experiments.run as run_module
import motor.forecast.quantile_gbm as qgbm_module
from motor.config import Params, load_params
from motor.experiments.run import RunManifest, run_arm_and_save
from motor.policy.erp_calibration import CalibrationItem, CalibrationResult, sweep_erp_baseline

LEAD_TIMES: Final[tuple[int, ...]] = (3, 4, 6, 8, 10)
ALPHAS: Final[tuple[float, ...]] = (0.70, 0.80, 0.85, 0.90, 0.95)
ARMS: Final[tuple[str, ...]] = ("erp_baseline", "estatistico_basestock", "quantile_gbm_basestock")

TOTAL_CORES: Final[int] = os.cpu_count() or 1
"""Núcleos físicos+lógicos vistos pelo processo -- `os.cpu_count()` pode
devolver `None` num container sem cgroup exposto; `1` é o piso seguro."""

# Plano de sondagem do --measure-one: NÃO é a varredura completa (75 células).
# arm3 aparece 3x de propósito -- (lt3,a0.90)/(lt3,a0.95) têm que dar cache
# HIT de treino (mesmo lead_time -> mesmo horizonte -> mesmo config_hash,
# alpha não entra nele); (lt6,a0.90) é um lead_time novo, treino a frio de
# verdade -- é o dado real que falta para projetar o custo por lead_time.
_PROBE_PLAN: Final[tuple[tuple[str, int, float], ...]] = (
    ("erp_baseline", 3, 0.90),
    ("estatistico_basestock", 3, 0.90),
    ("quantile_gbm_basestock", 3, 0.90),
    ("quantile_gbm_basestock", 3, 0.95),
    ("quantile_gbm_basestock", 6, 0.90),
)

_BUDGET_SECONDS: Final[float] = 4 * 3600  # ~4h, teto do enunciado da sprint
_CACHE_HIT_THRESHOLD_SECONDS: Final[float] = 60.0  # acima disso, não é "carregar do disco"


def override_supplier_lead_time(suppliers: pl.DataFrame, lead_time_days: int) -> pl.DataFrame:
    """Sobrescreve `lead_time_days` para TODOS os fornecedores do
    subconjunto. Único jeito de variar o eixo lead_time sem tocar
    `motor.io.loaders` -- hoje já é uniforme (3, vindo do default de
    `supplier_assumptions`, ver params.yaml), então não há uma distribuição
    real por fornecedor para preservar."""
    return suppliers.with_columns(pl.lit(lead_time_days).cast(pl.Int64).alias("lead_time_days"))


def override_supplier_review_period(
    suppliers: pl.DataFrame, review_period_days: int
) -> pl.DataFrame:
    """Sobrescreve `review_period_days` para TODOS os fornecedores do
    subconjunto -- simétrico a `override_supplier_lead_time` (Etapa 3.4/3.5,
    Sprint 16.5). Sozinho isto NÃO basta para o braço 3: `build_cell_params`
    (abaixo) amarra `model.retrain_cadence_days` ao mesmo valor -- ver
    docstring de `build_cell_params` para o porquê."""
    return suppliers.with_columns(
        pl.lit(review_period_days).cast(pl.Int64).alias("review_period_days")
    )


def build_cell_params(
    base_params: Params, *, alpha: float, review_period_days: int | None = None
) -> Params:
    """Só `economics.default_alpha` muda por célula -- `model.quantiles` é a
    grade única e global (ver docstring do módulo). Checagem explícita
    porque `Params.model_copy(update=...)` (ao contrário de
    `Params.model_validate`) NÃO reexecuta o `model_validator` que amarra
    `default_alpha` a `model.quantiles` (`Params._alpha_bate_com_a_grade_de_quantis`).

    `review_period_days` (Etapa 3.4/3.5): quando dado, TAMBÉM sobrescreve
    `model.retrain_cadence_days` para o MESMO valor -- achado da revisão da
    Sprint 16.5: `_quantile_gbm_retrain_dates` (motor.experiments.run) usa
    `model.retrain_cadence_days` pra gerar tanto as datas de retreino quanto
    as `decision_dates` de `precompute_predictions`, DESACOPLADO do
    `review_period_days` do fornecedor -- variar um sem o outro faz o
    Simulator decidir em datas que o precompute nunca calculou (o guarda
    `as_of not in self._precomputed`, motor.forecast.quantile_gbm, estoura
    exatamente por isto, de propósito). Sem `review_period_days`, o
    comportamento é idêntico ao de antes desta etapa (`model.retrain_cadence_days`
    não é tocado) -- retrocompatível com a varredura de 75 células já aprovada."""
    grade = set(base_params.model.quantiles)
    if alpha not in grade:
        msg = (
            f"alpha={alpha!r} não está em model.quantiles={list(base_params.model.quantiles)!r} "
            "-- a varredura assume uma grade única que já cobre todo alpha testado (ver "
            "docstring do módulo); estender a grade por célula reabriria o acoplamento por "
            "rank documentado em motor.experiments.run._QUANTILE_GRID_COUPLING_NOTE."
        )
        raise ValueError(msg)
    update: dict[str, Any] = {
        "economics": base_params.economics.model_copy(update={"default_alpha": alpha})
    }
    if review_period_days is not None:
        update["model"] = base_params.model.model_copy(
            update={"retrain_cadence_days": review_period_days}
        )
    return base_params.model_copy(update=update)


def cell_dir(
    results_root: Path,
    *,
    lead_time_days: int,
    alpha: float,
    review_period_days: int | None = None,
) -> Path:
    if review_period_days is None:
        return results_root / "sensibilidade" / f"lt{lead_time_days}_a{alpha:.2f}"
    return (
        results_root
        / "sensibilidade_dirigida"
        / f"lt{lead_time_days}_rp{review_period_days}_a{alpha:.2f}"
    )


@dataclass(frozen=True)
class CellTiming:
    """Decomposição por `perf_counter` (imune a suspensão da máquina, ao
    contrário do `execution_seconds` do manifesto, que usa relógio de
    parede -- ver ressalva da Etapa 2). `train_seconds`/`predict_seconds`
    ficam em 0.0 para braços que não são `quantile_gbm` (não passam pelo
    código instrumentado)."""

    total_seconds: float
    train_seconds: float
    predict_seconds: float

    @property
    def rest_seconds(self) -> float:
        return self.total_seconds - self.train_seconds - self.predict_seconds


def run_cell(
    *,
    arm_name: str,
    lead_time_days: int,
    alpha: float,
    base_params: Params,
    sales: pl.LazyFrame,
    items: pl.DataFrame,
    suppliers: pl.DataFrame,
    stock: pl.DataFrame,
    canonical_dir: Path,
    results_root: Path,
    subset_cache_path: Path,
    review_period_days: int | None = None,
    force: bool = False,
) -> tuple[RunManifest, CellTiming]:
    """Roda UMA célula via `run_arm_and_save` (nenhum caminho paralelo).
    Instrumenta treino (`_build_quantile_gbm_registry`) e previsão
    (`QuantileGbmForecaster.predict_quantiles`) por monkeypatch de módulo,
    igual à medição da Etapa 2 -- não altera `run.py` nem `quantile_gbm.py`.

    `review_period_days` (Etapa 3.4/3.5): quando dado, sobrescreve
    `suppliers.review_period_days` (`override_supplier_review_period`) E
    amarra `model.retrain_cadence_days` ao mesmo valor (`build_cell_params`)
    -- os dois juntos, nunca um sem o outro (ver docstring de
    `build_cell_params` para o porquê). `None` preserva o comportamento da
    varredura de 75 células já aprovada, sem tocar `review_period_days`.

    Grava `cell.json` ao lado do `manifest.json` de sempre --
    `lead_time_days`/`review_period_days` são uniformes por construção nesta
    varredura, mas não são campos naturais de `RunManifest` (que é por-item
    em geral); `alpha` já está em `manifest.basestock_calibration.alpha`,
    repetido aqui só por conveniência de quem for ler `cell.json` sozinho."""
    cell_params = build_cell_params(base_params, alpha=alpha, review_period_days=review_period_days)
    cell_suppliers = override_supplier_lead_time(suppliers, lead_time_days)
    if review_period_days is not None:
        cell_suppliers = override_supplier_review_period(cell_suppliers, review_period_days)
    out_dir = cell_dir(
        results_root,
        lead_time_days=lead_time_days,
        alpha=alpha,
        review_period_days=review_period_days,
    )

    timings = {"train": 0.0, "predict": 0.0}
    original_build_registry = run_module._build_quantile_gbm_registry
    original_predict = qgbm_module.QuantileGbmForecaster.predict_quantiles

    def _timed_build_registry(*args: Any, **kwargs: Any) -> Any:
        t0 = time.perf_counter()
        result = original_build_registry(*args, **kwargs)
        timings["train"] += time.perf_counter() - t0
        return result

    def _timed_predict(self: Any, *args: Any, **kwargs: Any) -> Any:
        t0 = time.perf_counter()
        result = original_predict(self, *args, **kwargs)
        timings["predict"] += time.perf_counter() - t0
        return result

    run_module._build_quantile_gbm_registry = _timed_build_registry
    qgbm_module.QuantileGbmForecaster.predict_quantiles = _timed_predict  # type: ignore[method-assign]
    t0_total = time.perf_counter()
    try:
        manifest = run_arm_and_save(
            arm_name,
            cell_params,
            sales=sales,
            items=items,
            suppliers=cell_suppliers,
            stock=stock,
            subset_cache_path=subset_cache_path,
            canonical_dir=canonical_dir,
            results_dir=out_dir,
            force=force,
        )
    finally:
        run_module._build_quantile_gbm_registry = original_build_registry
        qgbm_module.QuantileGbmForecaster.predict_quantiles = original_predict  # type: ignore[method-assign]
    total_seconds = time.perf_counter() - t0_total

    cell_json: dict[str, Any] = {"lead_time_days": lead_time_days, "alpha": alpha, "arm": arm_name}
    if review_period_days is not None:
        cell_json["review_period_days"] = review_period_days
        cell_json["retrain_cadence_days"] = cell_params.model.retrain_cadence_days
        cell_json["nota"] = (
            "varredura dirigida (Sprint 16.5, Etapa 3.4/3.5): lead_time_days e "
            "review_period_days sobrescritos para esta célula, não são o valor de "
            "produção de supplier_assumptions -- ver manifest.json/assumptions para "
            "o registro completo."
        )
    (out_dir / arm_name / "cell.json").write_text(json.dumps(cell_json, indent=2, sort_keys=True))

    return manifest, CellTiming(
        total_seconds=total_seconds,
        train_seconds=timings["train"],
        predict_seconds=timings["predict"],
    )


# --------------------------------------------------------------------------
# Varredura DIRIGIDA (Sprint 16.5, Etapa 3.4/3.5/3.6) -- lead_time x
# review_period, com o baseline RECALIBRADO em cada célula pela mesma
# metodologia da Sprint 7 (motor.policy.erp_calibration.sweep_erp_baseline).
# Eixo e motivação diferentes da varredura de 75 células acima (aquela é
# lead_time x alpha, braço 1 SEM recalibrar -- decisão deliberada daquela
# etapa; esta existe porque a Sprint 16 mostrou que um baseline não
# recalibrado é espantalho fora do lead_time de referência). Saída em
# `results/sensibilidade_dirigida/`, caminho próprio -- não mistura com as
# 75 células.
# --------------------------------------------------------------------------

DIRECTED_LEAD_TIMES: Final[tuple[int, ...]] = (3, 5, 7, 10)
DIRECTED_REVIEW_PERIODS: Final[tuple[int, ...]] = (7, 14)

# Mesma grade documentada em params.yaml/erp_baseline (Sprint 7) -- não uma
# grade nova. Passo 0.02 entre 0.28-0.40 (onde a curva cruza a meta medida
# na Sprint 7), passo 0.1 no resto.
_ERP_FACTOR_GRID: Final[tuple[float, ...]] = (
    0.1,
    0.2,
    0.28,
    0.30,
    0.32,
    0.34,
    0.36,
    0.38,
    0.40,
    *(round(0.5 + 0.1 * i, 2) for i in range(16)),  # 0.5 .. 2.0 passo 0.1
)
_ERP_MIN_ORDER_GRID: Final[tuple[float, ...]] = (0.0, 1.0, 3.0, 5.0, 10.0)
_ERP_TARGET_SERVICE_LEVEL: Final[float] = 0.95


def directed_cell_dir(
    results_root: Path, *, lead_time_days: int, review_period_days: int
) -> Path:
    return (
        results_root / "sensibilidade_dirigida" / f"lt{lead_time_days}_rp{review_period_days}"
    )


def build_directed_cell_params(
    base_params: Params,
    *,
    lead_time_days: int,
    review_period_days: int,
    erp_factor: float,
    erp_min_order_units: float,
    alpha: float | None = None,
) -> Params:
    """Constrói os `Params` de uma célula da varredura dirigida.

    Três sobrescritas, nenhuma isolada:
    - `model.retrain_cadence_days = review_period_days` -- a amarração da
      Etapa 3.5 (ver `motor.experiments.run._quantile_gbm_retrain_dates`).
    - `erp_baseline.factor`/`min_order_units` = os valores RECALIBRADOS
      nesta célula (`calibrate_directed_cell`) -- é o ponto inteiro da
      Etapa 3.4: baseline fixo numa grade que varia lead_time/review_period
      é o espantalho que a Sprint 7 avisou.
    - `supplier_assumptions.default_lead_time_days`/`default_review_period_days`
      = os valores desta célula -- SEM efeito em nenhum código de execução
      (a Etapa 3.4 sobrescreve `suppliers` diretamente, não este default),
      só para que `motor.assumptions.build_assumptions_registry` (Etapa 3.1)
      registre o valor CERTO no manifesto desta célula, não o default de
      `params.yaml`. Sem isto, o resumo autossuficiente mentiria sobre a
      própria premissa que a célula existe para variar.
    - `alpha` (Etapa 3.10): quando dado, sobrescreve `economics.default_alpha`
      -- checagem de grade idêntica à de `build_cell_params` (alpha precisa
      estar em `model.quantiles`). `None` (default) preserva o comportamento
      de antes da Etapa 3.10: braços 2/3 rodam com `economics.default_alpha`
      de `params.yaml` (0,90), sem overhead nenhum para quem não pediu isto.
    """
    grade = set(base_params.model.quantiles)
    if alpha is not None and alpha not in grade:
        msg = (
            f"alpha={alpha!r} não está em model.quantiles={list(base_params.model.quantiles)!r}"
        )
        raise ValueError(msg)
    update: dict[str, Any] = {
        "model": base_params.model.model_copy(update={"retrain_cadence_days": review_period_days}),
        "erp_baseline": base_params.erp_baseline.model_copy(
            update={"factor": erp_factor, "min_order_units": erp_min_order_units}
        ),
        "supplier_assumptions": base_params.supplier_assumptions.model_copy(
            update={
                "default_lead_time_days": lead_time_days,
                "default_review_period_days": review_period_days,
            }
        ),
    }
    if alpha is not None:
        update["economics"] = base_params.economics.model_copy(update={"default_alpha": alpha})
    return base_params.model_copy(update=update)


def calibrate_directed_cell(
    *,
    lead_time_days: int,
    review_period_days: int,
    base_params: Params,
    sales_subset: pl.DataFrame,
    item_ids: Sequence[str],
) -> CalibrationResult:
    """Recalibra `erp_baseline.factor`/`min_order_units` para
    `(lead_time_days, review_period_days)`, mesma metodologia e mesma grade
    da Sprint 7 (`motor.policy.erp_calibration.sweep_erp_baseline`) -- só o
    `lead_time_days`/`review_period_days` de cada `CalibrationItem` muda.
    `sales_subset`: colunas `item_id`, `date`, `units_sold`, já recortado ao
    subconjunto de trabalho (275 itens)."""
    items = [
        CalibrationItem(
            item_id=item_id,
            demand=sales_subset.filter(pl.col("item_id") == item_id).select("date", "units_sold"),
            lead_time_days=lead_time_days,
            review_period_days=review_period_days,
        )
        for item_id in item_ids
    ]
    return sweep_erp_baseline(
        items,
        start=base_params.subset_selection.density_window_start,
        end=base_params.subset_selection.density_window_end,
        warmup_days=base_params.simulation.warmup_days,
        moving_average_weeks=base_params.forecast_naive.moving_average_weeks,
        min_residual_samples=base_params.forecast_naive.min_residual_samples,
        quantiles=list(base_params.model.quantiles),
        factor_grid=list(_ERP_FACTOR_GRID),
        min_order_grid=list(_ERP_MIN_ORDER_GRID),
        target_service_level=_ERP_TARGET_SERVICE_LEVEL,
    )


def run_directed_cell(
    *,
    arm_name: str,
    lead_time_days: int,
    review_period_days: int,
    erp_factor: float,
    erp_min_order_units: float,
    base_params: Params,
    sales: pl.LazyFrame,
    items: pl.DataFrame,
    suppliers: pl.DataFrame,
    stock: pl.DataFrame,
    canonical_dir: Path,
    results_root: Path,
    subset_cache_path: Path,
    force: bool = False,
) -> RunManifest:
    """Roda UM braço de UMA célula da varredura dirigida via
    `run_arm_and_save` (nenhum caminho paralelo) -- `erp_factor`/
    `erp_min_order_units` vêm de `calibrate_directed_cell`, calculados uma
    vez por célula, reusados pelos 3 braços dessa célula (o baseline
    recalibrado é o mesmo config para todos, só a política de cada braço
    difere)."""
    cell_params = build_directed_cell_params(
        base_params,
        lead_time_days=lead_time_days,
        review_period_days=review_period_days,
        erp_factor=erp_factor,
        erp_min_order_units=erp_min_order_units,
    )
    cell_suppliers = override_supplier_review_period(
        override_supplier_lead_time(suppliers, lead_time_days), review_period_days
    )
    out_dir = directed_cell_dir(
        results_root, lead_time_days=lead_time_days, review_period_days=review_period_days
    )
    return run_arm_and_save(
        arm_name,
        cell_params,
        sales=sales,
        items=items,
        suppliers=cell_suppliers,
        stock=stock,
        subset_cache_path=subset_cache_path,
        canonical_dir=canonical_dir,
        results_dir=out_dir,
        force=force,
    )


def run_directed_unit(
    *,
    lead_time_days: int,
    review_period_days: int,
    params_path: Path,
    results_dir: Path,
    force: bool,
) -> dict[str, float]:
    """Roda UMA unidade (`lead_time_days`, `review_period_days`) da
    varredura dirigida: calibra o baseline uma vez, depois roda os 3 braços
    em série com essa calibração. Grava `calibration.json` ao lado dos 3
    `manifest.json` -- o registro por extenso da recalibração (grade,
    escolha, meta atingida), no mesmo espírito autossuficiente do
    `RunManifest` (Sprint 9), mas num arquivo próprio porque a calibração
    não é de nenhum braço em particular, é da CÉLULA."""
    params = load_params(params_path)
    sales, items, suppliers, stock = _load_canonical(params)
    canonical_dir = Path(params.data.canonical_dir)
    subset_cache_path = results_dir / "subset_selection.json"

    subset = run_module.load_or_select_subset(
        sales, items, suppliers, stock, params, cache_path=subset_cache_path
    )
    item_ids = list(subset.item_ids)
    sales_subset = (
        sales.filter(
            (pl.col("store_id") == subset.store_id) & (pl.col("item_id").is_in(item_ids))
        )
        .select("item_id", "date", "units_sold")
        .sort("item_id", "date")
        .collect()
    )

    out_dir = directed_cell_dir(
        results_dir, lead_time_days=lead_time_days, review_period_days=review_period_days
    )
    calib_path = out_dir / "calibration.json"
    if not force and calib_path.exists():
        calib_data = json.loads(calib_path.read_text())
        erp_factor = calib_data["chosen"]["factor"]
        erp_min_order_units = calib_data["chosen"]["min_order_units"]
        print(
            f"[calibração reusada] lt={lead_time_days} rp={review_period_days} "
            f"factor={erp_factor} min_order_units={erp_min_order_units}"
        )
    else:
        t0 = time.perf_counter()
        calib = calibrate_directed_cell(
            lead_time_days=lead_time_days,
            review_period_days=review_period_days,
            base_params=params,
            sales_subset=sales_subset,
            item_ids=item_ids,
        )
        t_calib = time.perf_counter() - t0
        erp_factor = calib.chosen.factor
        erp_min_order_units = calib.chosen.min_order_units
        out_dir.mkdir(parents=True, exist_ok=True)
        calib_path.write_text(
            json.dumps(
                {
                    "lead_time_days": lead_time_days,
                    "review_period_days": review_period_days,
                    "metodologia": (
                        "Sprint 7 (motor.policy.erp_calibration.sweep_erp_baseline), "
                        "recalibrado nesta célula (Sprint 16.5, Etapa 3.4) -- mesma "
                        "grade e critério, só lead_time/review_period do item mudam"
                    ),
                    "factor_grid": list(_ERP_FACTOR_GRID),
                    "min_order_grid": list(_ERP_MIN_ORDER_GRID),
                    "target_service_level": calib.target_service_level,
                    "target_met": calib.target_met,
                    "chosen": {
                        "factor": calib.chosen.factor,
                        "min_order_units": calib.chosen.min_order_units,
                        "fill_rate": calib.chosen.fill_rate,
                        "avg_on_hand": calib.chosen.avg_on_hand,
                    },
                    "calibration_seconds": t_calib,
                },
                indent=2,
                sort_keys=True,
            )
        )
        print(
            f"[calibração] lt={lead_time_days} rp={review_period_days} "
            f"factor={erp_factor} min_order_units={erp_min_order_units} "
            f"fill_rate={calib.chosen.fill_rate:.4f} target_met={calib.target_met} "
            f"({t_calib:.1f}s)"
        )

    resultados: dict[str, float] = {}
    for arm_name in ARMS:
        t0 = time.perf_counter()
        manifest = run_directed_cell(
            arm_name=arm_name,
            lead_time_days=lead_time_days,
            review_period_days=review_period_days,
            erp_factor=erp_factor,
            erp_min_order_units=erp_min_order_units,
            base_params=params,
            sales=sales,
            items=items,
            suppliers=suppliers,
            stock=stock,
            canonical_dir=canonical_dir,
            results_root=results_dir,
            subset_cache_path=subset_cache_path,
            force=force,
        )
        dt = time.perf_counter() - t0
        resultados[arm_name] = manifest.results.portfolio.decision_metric
        print(
            f"[ok] lt={lead_time_days} rp={review_period_days} arm={arm_name} "
            f"decision_metric={manifest.results.portfolio.decision_metric} ({dt:.1f}s)"
        )
    return resultados


def run_directed_grid(
    *,
    params_path: Path,
    results_dir: Path,
    workers: int,
    force: bool,
    lead_times: Sequence[int] = DIRECTED_LEAD_TIMES,
    review_periods: Sequence[int] = DIRECTED_REVIEW_PERIODS,
) -> dict[str, bool]:
    """Orquestra a varredura dirigida completa: aquece o cache de
    subconjunto em série, dispara até `workers` subprocessos concorrentes,
    um por unidade `(lead_time, review_period)` -- cada um calibra e roda
    os 3 braços em série (`run_directed_unit`). Mesmo padrão de
    `run_grid` (subprocesso + env, não `multiprocessing` -- ver docstring
    do módulo)."""
    params = load_params(params_path)
    sales, items, suppliers, stock = _load_canonical(params)
    subset_cache_path = results_dir / "subset_selection.json"
    warm_subset_cache(
        params,
        sales=sales,
        items=items,
        suppliers=suppliers,
        stock=stock,
        subset_cache_path=subset_cache_path,
    )
    print(f"subset_selection.json pronto em {subset_cache_path}")

    units = [(lt, rp) for lt in lead_times for rp in review_periods]
    threads = polars_threads_for(workers)
    print(
        f"{len(units)} unidades (lead_time x review_period). POLARS_MAX_THREADS por "
        f"worker: {threads} ({TOTAL_CORES} núcleos totais / {workers} workers)"
    )
    env = {**os.environ, "POLARS_MAX_THREADS": str(threads)}

    def _launch(lt: int, rp: int) -> subprocess.CompletedProcess[str]:
        cmd = [
            sys.executable,
            "-m",
            "motor.experiments.sensitivity",
            "--run-directed-unit",
            "--lead-time",
            str(lt),
            "--review-period",
            str(rp),
            "--params",
            str(params_path),
            "--results-dir",
            str(results_dir),
        ]
        if force:
            cmd.append("--force")
        return subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)

    results: dict[tuple[int, int], subprocess.CompletedProcess[str]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_launch, lt, rp): (lt, rp) for lt, rp in units}
        for future in as_completed(futures):
            lt, rp = futures[future]
            result = future.result()
            results[(lt, rp)] = result
            status = "ok" if result.returncode == 0 else f"FALHOU (exit={result.returncode})"
            print(f"[{status}] lead_time={lt} review_period={rp}")
            if result.returncode != 0:
                print(f"--- stdout ---\n{result.stdout[-3000:]}")
                print(f"--- stderr ---\n{result.stderr[-3000:]}")

    summary = {f"lt{lt}_rp{rp}": (r.returncode == 0) for (lt, rp), r in results.items()}
    summary_path = results_dir / "sensibilidade_dirigida" / "sweep_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True))
    n_falhas = sum(1 for ok in summary.values() if not ok)
    print(f"\n{len(results)} unidades rodadas, {n_falhas} com falha. Resumo: {summary_path}")
    return summary


def _load_canonical(
    params: Params,
) -> tuple[pl.LazyFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    canonical_dir = Path(params.data.canonical_dir)
    sales = pl.scan_parquet(canonical_dir / "sales.parquet")
    items = pl.read_parquet(canonical_dir / "items.parquet")
    suppliers = pl.read_parquet(canonical_dir / "suppliers.parquet")
    stock = pl.read_parquet(canonical_dir / "stock.parquet")
    return sales, items, suppliers, stock


def polars_threads_for(n_workers: int, *, total_cores: int = TOTAL_CORES) -> int:
    """`POLARS_MAX_THREADS` por worker -- nunca menos que 1. `n_workers`
    processos concorrentes, cada um com sua PRÓPRIA thread pool de polars
    (default: todos os núcleos), saturam a máquina em `n_workers` x mais
    threads que núcleos sem isto. Com 16 núcleos e 15 workers (5 lead_times
    x 3 braços), dá 1 -- feature building (`.collect()`, ~63% do custo do
    braço 3, dívida técnica registrada, não atacada nesta sprint) fica
    single-thread em cada worker. Aceito: 15 células em paralelo a 1 thread
    cada ainda ganha muito sobre 1 célula de cada vez a 16 threads -- mas é
    o primeiro lugar a olhar se a projeção final ficar apertada (menos
    workers, mais threads por worker, é outro ponto na mesma curva)."""
    if n_workers < 1:
        msg = f"n_workers deve ser >= 1, recebeu {n_workers}"
        raise ValueError(msg)
    return max(1, total_cores // n_workers)


def warm_subset_cache(
    params: Params,
    *,
    sales: pl.LazyFrame,
    items: pl.DataFrame,
    suppliers: pl.DataFrame,
    stock: pl.DataFrame,
    subset_cache_path: Path,
) -> None:
    """Chamada EXPLÍCITA, em série, ANTES de disparar qualquer worker --
    `subset_cache_path` é compartilhado por TODAS as 75 células; se ainda
    não existir, `load_or_select_subset` escreve nele. É a ÚNICA disputa de
    escrita real desta varredura (diretórios de cache de modelo do braço 3
    são disjuntos por lead_time, por construção -- ver docstring do módulo).
    Falha alto e claro se não deixar o arquivo pronto -- nunca prossegue
    para workers concorrentes sem essa garantia."""
    run_module.load_or_select_subset(
        sales, items, suppliers, stock, params, cache_path=subset_cache_path
    )
    if not subset_cache_path.exists():
        msg = (
            f"warm_subset_cache: {subset_cache_path} não existe depois de "
            "load_or_select_subset -- não prossiga para workers concorrentes sem essa "
            "garantia (é a única disputa de escrita real da varredura, ver docstring do módulo)."
        )
        raise RuntimeError(msg)


def _cell_is_done(
    results_root: Path,
    *,
    lead_time_days: int,
    alpha: float,
    arm_name: str,
    expected_quantiles: list[float],
) -> bool:
    """Retomada idempotente: uma célula só conta como pronta se o manifesto
    existir E tiver sido gravado sob a MESMA `active_quantiles` de hoje
    (achado da Etapa 2: braço 3 não é comparável entre grades -- aceitar uma
    célula de grade antiga como pronta silenciosamente reintroduziria esse
    problema pela porta dos fundos da retomada)."""
    manifest_path = (
        cell_dir(results_root, lead_time_days=lead_time_days, alpha=alpha)
        / arm_name
        / "manifest.json"
    )
    if not manifest_path.exists():
        return False
    manifest = json.loads(manifest_path.read_text())
    return list(manifest.get("active_quantiles", [])) == expected_quantiles


def run_unit(
    *,
    lead_time_days: int,
    arm_name: str,
    alphas: Sequence[float],
    params_path: Path,
    results_dir: Path,
    force: bool,
) -> bool:
    """Roda os `alphas` de UMA unidade `(lead_time_days, arm_name)` EM SÉRIE,
    neste processo -- é o corpo que `--run-unit` executa (chamado por
    `run_grid` via subprocesso, um por unidade) ou que se chama sozinho para
    depurar uma unidade sem paralelismo. Cada alpha num `try/except` próprio
    -- uma falha não impede os outros 4 alphas desta unidade. Devolve `True`
    só se todos os alphas pedidos terminaram sem exceção."""
    params = load_params(params_path)
    sales, items, suppliers, stock = _load_canonical(params)
    canonical_dir = Path(params.data.canonical_dir)
    subset_cache_path = results_dir / "subset_selection.json"
    expected_quantiles = list(params.model.quantiles)

    print(
        f"run_unit lead_time={lead_time_days} arm={arm_name} alphas={list(alphas)} "
        f"(POLARS_MAX_THREADS={os.environ.get('POLARS_MAX_THREADS', '<não setado>')}, "
        f"pl.thread_pool_size()={pl.thread_pool_size()})"
    )

    tudo_ok = True
    for alpha in alphas:
        if not force and _cell_is_done(
            results_dir,
            lead_time_days=lead_time_days,
            alpha=alpha,
            arm_name=arm_name,
            expected_quantiles=expected_quantiles,
        ):
            print(f"  [pulado, já pronto] lt={lead_time_days} arm={arm_name} alpha={alpha:.2f}")
            continue
        try:
            _manifest, timing = run_cell(
                arm_name=arm_name,
                lead_time_days=lead_time_days,
                alpha=alpha,
                base_params=params,
                sales=sales,
                items=items,
                suppliers=suppliers,
                stock=stock,
                canonical_dir=canonical_dir,
                results_root=results_dir,
                subset_cache_path=subset_cache_path,
                force=force,
            )
            print(
                f"  [ok] lt={lead_time_days} arm={arm_name} alpha={alpha:.2f} "
                f"total={timing.total_seconds:.1f}s"
            )
        # captura ampla de propósito: uma falha é registrada e reportada, nunca silenciada
        except Exception as exc:
            tudo_ok = False
            print(f"  [FALHOU] lt={lead_time_days} arm={arm_name} alpha={alpha:.2f}: {exc!r}")
    return tudo_ok


def run_grid(
    *,
    params_path: Path,
    results_dir: Path,
    workers: int,
    force: bool,
    lead_times: Sequence[int] = LEAD_TIMES,
    arms: Sequence[str] = ARMS,
    alphas: Sequence[float] = ALPHAS,
) -> dict[str, bool]:
    """Orquestra a varredura completa: aquece o cache de subconjunto em
    série, calcula as unidades pendentes (retomada idempotente), e dispara
    até `workers` subprocessos concorrentes, um por unidade `(lead_time,
    arm)`, cada um rodando `run_unit` (5 alphas em série). Devolve
    `{"lt{N}_{arm}": sucesso}` e grava o mesmo dicionário em
    `results_dir/sensibilidade/sweep_summary.json`."""
    params = load_params(params_path)
    sales, items, suppliers, stock = _load_canonical(params)
    subset_cache_path = results_dir / "subset_selection.json"
    warm_subset_cache(
        params, sales=sales, items=items, suppliers=suppliers, stock=stock,
        subset_cache_path=subset_cache_path,
    )
    print(f"subset_selection.json pronto em {subset_cache_path}")

    expected_quantiles = list(params.model.quantiles)
    units = [(lt, arm) for lt in lead_times for arm in arms]
    pending = [
        (lt, arm)
        for lt, arm in units
        if force
        or not all(
            _cell_is_done(
                results_dir, lead_time_days=lt, alpha=a, arm_name=arm,
                expected_quantiles=expected_quantiles,
            )
            for a in alphas
        )
    ]
    print(f"{len(units)} unidades no total, {len(pending)} pendentes (retomada idempotente)")

    threads = polars_threads_for(workers)
    print(
        f"POLARS_MAX_THREADS por worker: {threads} "
        f"({TOTAL_CORES} núcleos totais / {workers} workers)"
    )
    env = {**os.environ, "POLARS_MAX_THREADS": str(threads)}

    def _launch(lt: int, arm: str) -> subprocess.CompletedProcess[str]:
        cmd = [
            sys.executable,
            "-m",
            "motor.experiments.sensitivity",
            "--run-unit",
            "--lead-time",
            str(lt),
            "--arm",
            arm,
            "--alphas",
            ",".join(str(a) for a in alphas),
            "--params",
            str(params_path),
            "--results-dir",
            str(results_dir),
        ]
        if force:
            cmd.append("--force")
        return subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)

    results: dict[tuple[int, str], subprocess.CompletedProcess[str]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_launch, lt, arm): (lt, arm) for lt, arm in pending}
        for future in as_completed(futures):
            lt, arm = futures[future]
            result = future.result()
            results[(lt, arm)] = result
            status = "ok" if result.returncode == 0 else f"FALHOU (exit={result.returncode})"
            print(f"[{status}] lead_time={lt} arm={arm}")
            if result.returncode != 0:
                print(f"--- stdout ---\n{result.stdout[-2000:]}")
                print(f"--- stderr ---\n{result.stderr[-2000:]}")

    summary = {f"lt{lt}_{arm}": (r.returncode == 0) for (lt, arm), r in results.items()}
    # unidades puladas (já prontas) contam como sucesso -- não rodaram, mas o estado é válido
    for lt, arm in units:
        key = f"lt{lt}_{arm}"
        if key not in summary:
            summary[key] = True
    summary_path = results_dir / "sensibilidade" / "sweep_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True))
    n_falhas = sum(1 for ok in summary.values() if not ok)
    print(
        f"\n{len(results)} unidades rodadas ({len(units) - len(results)} puladas), "
        f"{n_falhas} com falha. Resumo: {summary_path}"
    )
    return summary


def measure_one(
    *, params_path: Path, results_dir: Path, force: bool
) -> list[tuple[str, int, float, RunManifest, CellTiming]]:
    """Roda `_PROBE_PLAN` (5 células, não as 75), imprime a decomposição de
    tempo e a projeção do custo total, e CONFIRMA (não só assume) que
    alphas do mesmo lead_time compartilham o treino do braço 3 -- se não
    compartilharem, imprime o alerta e não calcula a projeção como se
    compartilhassem."""
    params = load_params(params_path)
    sales, items, suppliers, stock = _load_canonical(params)
    subset_cache_path = results_dir / "subset_selection.json"

    rows: list[tuple[str, int, float, RunManifest, CellTiming]] = []
    for arm_name, lead_time_days, alpha in _PROBE_PLAN:
        manifest, timing = run_cell(
            arm_name=arm_name,
            lead_time_days=lead_time_days,
            alpha=alpha,
            base_params=params,
            sales=sales,
            items=items,
            suppliers=suppliers,
            stock=stock,
            canonical_dir=Path(params.data.canonical_dir),
            results_root=results_dir,
            subset_cache_path=subset_cache_path,
            force=force,
        )
        rows.append((arm_name, lead_time_days, alpha, manifest, timing))
        print(
            f"[medido] {arm_name:24s} lt={lead_time_days:2d} alpha={alpha:.2f} "
            f"total={timing.total_seconds:8.1f}s treino={timing.train_seconds:8.1f}s "
            f"previsão={timing.predict_seconds:8.1f}s resto={timing.rest_seconds:7.1f}s "
            f"decision_metric={manifest.results.portfolio.decision_metric}"
        )

    by_key = {(arm, lt, a): (m, t) for arm, lt, a, m, t in rows}
    _, t_erp = by_key[("erp_baseline", 3, 0.90)]
    _, t_stat = by_key[("estatistico_basestock", 3, 0.90)]
    _, t_gbm_a90 = by_key[("quantile_gbm_basestock", 3, 0.90)]
    _, t_gbm_a95 = by_key[("quantile_gbm_basestock", 3, 0.95)]
    _, t_gbm_lt6 = by_key[("quantile_gbm_basestock", 6, 0.90)]

    cache_compartilhado = (
        t_gbm_a90.train_seconds < _CACHE_HIT_THRESHOLD_SECONDS
        and t_gbm_a95.train_seconds < _CACHE_HIT_THRESHOLD_SECONDS
    )
    print()
    print("--- verificação de compartilhamento de cache entre alphas (mesmo lead_time=3) ---")
    print(f"treino em alpha=0.90: {t_gbm_a90.train_seconds:.1f}s")
    print(f"treino em alpha=0.95: {t_gbm_a95.train_seconds:.1f}s")
    print(f"treino em lead_time=6 (referência de treino a frio): {t_gbm_lt6.train_seconds:.1f}s")
    if not cache_compartilhado:
        print(
            "ALERTA: alpha=0.90 e/ou alpha=0.95 treinaram de verdade (>60s) em vez de "
            "carregar do cache -- algo indevido está entrando em compute_config_hash. "
            "NÃO calculando projeção -- pare e reporte antes de seguir."
        )
        return rows
    print("confirmado: as duas células de alpha, mesmo lead_time, reusaram o cache de treino.")

    # projeção das 75 células
    t_train_por_lead_time = t_gbm_lt6.train_seconds  # única referência de treino a frio que temos
    t_predict_rest_por_celula_gbm = (
        (t_gbm_a90.total_seconds - t_gbm_a90.train_seconds)
        + (t_gbm_a95.total_seconds - t_gbm_a95.train_seconds)
        + (t_gbm_lt6.total_seconds - t_gbm_lt6.train_seconds)
    ) / 3

    total_arm1 = len(LEAD_TIMES) * len(ALPHAS) * t_erp.total_seconds
    total_arm2 = len(LEAD_TIMES) * len(ALPHAS) * t_stat.total_seconds
    total_arm3 = (
        len(LEAD_TIMES) * t_train_por_lead_time
        + len(LEAD_TIMES) * len(ALPHAS) * t_predict_rest_por_celula_gbm
    )
    total_geral = total_arm1 + total_arm2 + total_arm3

    print()
    print("--- projeção das 75 células (5 lead_times x 5 alphas x 3 braços) ---")
    print(
        f"braço 1 (erp_baseline):        {len(LEAD_TIMES) * len(ALPHAS)} células x "
        f"{t_erp.total_seconds:.1f}s = {total_arm1:.0f}s ({total_arm1 / 60:.1f}min)"
    )
    print(
        f"braço 2 (estatistico_basestock): {len(LEAD_TIMES) * len(ALPHAS)} células x "
        f"{t_stat.total_seconds:.1f}s = {total_arm2:.0f}s ({total_arm2 / 60:.1f}min)"
    )
    print(
        f"braço 3 (quantile_gbm_basestock): {len(LEAD_TIMES)} treinos x "
        f"{t_train_por_lead_time:.1f}s + {len(LEAD_TIMES) * len(ALPHAS)} células x "
        f"{t_predict_rest_por_celula_gbm:.1f}s (previsão+resto) = "
        f"{total_arm3:.0f}s ({total_arm3 / 3600:.2f}h)"
    )
    print(f"TOTAL projetado: {total_geral:.0f}s = {total_geral / 3600:.2f}h")
    print(f"orçamento (enunciado da sprint): ~{_BUDGET_SECONDS / 3600:.0f}h")
    if total_geral > _BUDGET_SECONDS:
        print(
            "PROJEÇÃO ACIMA DO ORÇAMENTO -- não rodando a varredura completa. "
            "Ver alternativas no relatório."
        )
    else:
        print("projeção dentro do orçamento.")

    return rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Varredura de sensibilidade em lead_time e alpha (Sprint 16)."
    )
    parser.add_argument("--params", type=Path, default=Path("config/params.yaml"))
    parser.add_argument("--results-dir", type=Path, default=Path("results"))
    parser.add_argument(
        "--measure-one",
        action="store_true",
        help=(
            "roda o plano de sondagem (5 células) e projeta o custo das 75 "
            "-- não a varredura cheia"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "sobrescreve célula já existente em --results-dir/sensibilidade/... "
            "(ver ExistingResultError)"
        ),
    )
    parser.add_argument(
        "--run-unit",
        action="store_true",
        help="roda os alphas de UMA unidade (--lead-time, --arm) em série neste processo",
    )
    parser.add_argument("--lead-time", type=int, help="obrigatório com --run-unit")
    parser.add_argument("--arm", type=str, help="obrigatório com --run-unit")
    parser.add_argument(
        "--alphas",
        type=str,
        default=",".join(str(a) for a in ALPHAS),
        help="lista separada por vírgula (--run-unit/--run-grid); default: todos os 5 alphas",
    )
    parser.add_argument(
        "--run-grid",
        action="store_true",
        help="varredura completa (75 células), paralelizada por unidade (lead_time, arm)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        help="obrigatório com --run-grid/--run-directed-grid -- nº de unidades concorrentes",
    )
    parser.add_argument(
        "--run-directed-unit",
        action="store_true",
        help="calibra e roda os 3 braços de UMA unidade (--lead-time, --review-period)",
    )
    parser.add_argument("--review-period", type=int, help="obrigatório com --run-directed-unit")
    parser.add_argument(
        "--run-directed-grid",
        action="store_true",
        help=(
            "varredura dirigida completa (Etapa 3.4/3.6), paralelizada por "
            "(lead_time, review_period)"
        ),
    )
    args = parser.parse_args(argv)

    if args.measure_one:
        measure_one(params_path=args.params, results_dir=args.results_dir, force=args.force)
        return

    if args.run_unit:
        if args.lead_time is None or not args.arm:
            parser.error("--run-unit precisa de --lead-time e --arm")
        alphas = [float(a) for a in args.alphas.split(",")]
        ok = run_unit(
            lead_time_days=args.lead_time,
            arm_name=args.arm,
            alphas=alphas,
            params_path=args.params,
            results_dir=args.results_dir,
            force=args.force,
        )
        sys.exit(0 if ok else 1)

    if args.run_grid:
        if not args.workers:
            parser.error("--run-grid precisa de --workers")
        alphas = [float(a) for a in args.alphas.split(",")]
        summary = run_grid(
            params_path=args.params,
            results_dir=args.results_dir,
            workers=args.workers,
            force=args.force,
            alphas=alphas,
        )
        sys.exit(0 if all(summary.values()) else 1)

    if args.run_directed_unit:
        if args.lead_time is None or args.review_period is None:
            parser.error("--run-directed-unit precisa de --lead-time e --review-period")
        resultados = run_directed_unit(
            lead_time_days=args.lead_time,
            review_period_days=args.review_period,
            params_path=args.params,
            results_dir=args.results_dir,
            force=args.force,
        )
        sys.exit(0 if len(resultados) == len(ARMS) else 1)

    if args.run_directed_grid:
        if not args.workers:
            parser.error("--run-directed-grid precisa de --workers")
        summary = run_directed_grid(
            params_path=args.params,
            results_dir=args.results_dir,
            workers=args.workers,
            force=args.force,
        )
        sys.exit(0 if all(summary.values()) else 1)

    parser.error(
        "nada a fazer -- use --measure-one, --run-unit (--lead-time/--arm), --run-grid "
        "(--workers), --run-directed-unit (--lead-time/--review-period) ou "
        "--run-directed-grid (--workers)"
    )


if __name__ == "__main__":
    main()

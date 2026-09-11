"""Modelo pydantic de `Params` e carregamento de `config/params.yaml`.

Toda premissa numérica do projeto vem daqui -- nenhum número mágico no
código (CLAUDE.md, seção 2). O arquivo `config/params.yaml` comenta, campo a
campo, todo valor que foi arbitrado em vez de medido, para que a Sprint 17
(lista de premissas assumidas) não vire arqueologia.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import yaml
from annotated_types import Ge, Gt, Le, MinLen
from pydantic import BaseModel, ConfigDict

NonNegativeFloat = Annotated[float, Ge(0.0)]
PositiveFloat = Annotated[float, Gt(0.0)]
PositiveInt = Annotated[int, Gt(0)]
Fraction = Annotated[float, Ge(0.0), Le(1.0)]
Weekday = Annotated[int, Ge(1), Le(7)]  # 1 = segunda .. 7 = domingo (ISO)


class ParamsSection(BaseModel):
    """Classe-base das seções de `Params`: imutável, sem chave além do contrato."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class DataParams(ParamsSection):
    """Caminhos dos dados e período coberto pelo dataset bruto."""

    raw_dir: Path
    raw_parquet_dir: Path
    canonical_dir: Path
    start_date: date
    end_date: date


class ProfilingWindowParams(ParamsSection):
    """Uma janela candidata de análise para o perfil do subconjunto (Sprint 2).

    Existem várias porque a escolha da janela é ela mesma um trade-off a ser
    visto em número, não decidido a priori: janela mais curta tem promoção
    completa e evita o terremoto de 16/04/2016, janela mais longa tem mais
    histórico mas inclui a distorção do terremoto.
    """

    name: str
    start: date
    end: date


class ProfilingParams(ParamsSection):
    """Parâmetros do relatório de perfil (Sprint 2): janelas candidatas e grade
    de cortes de densidade usada por `count_candidates`."""

    windows: Annotated[list[ProfilingWindowParams], MinLen(1)]
    density_cuts: Annotated[list[Fraction], MinLen(1)]


class SubsetSelectionParams(ParamsSection):
    """Critério de seleção do subconjunto de trabalho (Sprint 4).

    Uma loja, 150-300 SKUs de demanda regular. Todo valor aqui é medido ou
    decidido na Fase A da Sprint 4 (ver relatório da sprint) -- nenhum é
    alterável por quem chama `motor.selection.select_subset`: a função lê
    estes campos de `Params`, nunca os recebe como argumento separado, para
    que a janela de medição de densidade (`density_window_*`) não vire um
    parâmetro que alguém desavisado troca pelo período de simulação (D3).

    `density_window_start`/`density_window_end` (D3): fatia em que a
    regularidade de demanda é medida -- estritamente ANTES do início do loop
    do simulador (`simulation.start_date`), nunca sobrepõe o trecho avaliado.
    Ver `simulation.start_date`/`evaluation_start_date` para a derivação.
    """

    store_id: str  # D1: loja 44 -- maior volume, histórico completo, tipo A
    n_stores: PositiveInt
    n_items_min: PositiveInt
    n_items_max: PositiveInt
    min_weeks_of_history: PositiveInt
    density_window_start: date
    density_window_end: date
    density_threshold: Fraction
    promo_days_max_share: Fraction
    family_min_items: PositiveInt
    family_cap: PositiveInt


class SimulationParams(ParamsSection):
    """Parâmetros do loop diário do simulador (CLAUDE.md, seção 6).

    `start_date` é quando o LOOP começa a rodar (precisa de
    `min_weeks_of_history` semanas de histórico antes dele para o primeiro
    `fit` do forecaster). Os primeiros `warmup_days` dias a partir daí são
    simulados mas descartados das métricas -- `evaluation_start_date` é onde
    a métrica financeira de fato começa a contar (Sprint 4, D2). Nenhum dos
    dois pode anteceder `canonical.window_start`, e `end_date` é
    `canonical.window_end` -- ver `config/params.yaml` para a derivação
    exata.
    """

    warmup_days: PositiveInt
    start_date: date
    evaluation_start_date: date
    end_date: date
    seed: int


class ForecastNaiveParams(ParamsSection):
    """Parâmetros de `motor.forecast.naive.NaiveForecaster` (Sprint 7).

    `moving_average_weeks` é compartilhado, de propósito, com
    `motor.policy.erp_baseline.ErpBaselinePolicy` -- a política recupera a
    mesma média móvel a partir do quantil mediano do forecast (ver comentário
    no topo de `erp_baseline.py`), então os dois lados precisam concordar
    sobre o tamanho da janela. Não são valores calibrados: `moving_average_weeks`
    é fixado em 4 pelo enunciado da sprint ("últimas 4 semanas");
    `min_residual_samples` é arbitrado (piso plausível para o backtest de
    resíduos não degenerar em poucas amostras).
    """

    moving_average_weeks: PositiveInt
    min_residual_samples: PositiveInt


class ErpBaselineParams(ParamsSection):
    """Parâmetros calibrados de `motor.policy.erp_baseline.ErpBaselinePolicy`
    (Sprint 7). Ver `config/params.yaml` para o registro completo por escrito
    do critério, da grade varrida e da interpretação do resultado -- não
    repetir aqui, é o mesmo pecado de número mágico duplicado."""

    factor: NonNegativeFloat
    min_order_units: NonNegativeFloat


class SupplierAssumptionsParams(ParamsSection):
    """Premissas de fornecedor usadas quando o cadastro não traz o dado.

    `items.pack_multiple` e afins são nuláveis no contrato canônico porque o
    dado público não os tem (ver `motor.io.contracts`); estes defaults
    preenchem essa lacuna até a arbitragem virar coluna obrigatória.

    `default_order_weekdays` alimenta `Supplier.order_days` (Sprint 3, D8): o
    Favorita não tem calendário de fornecedor, então todo fornecedor gerado
    recebe os mesmos dias -- arbitrado, ver `params.yaml`.
    """

    default_pack_multiple: PositiveFloat
    default_lead_time_days: PositiveInt
    default_review_period_days: PositiveInt
    default_min_order_value: NonNegativeFloat
    default_min_order_units: NonNegativeFloat
    default_order_weekdays: Annotated[list[Weekday], MinLen(1)]


class SupplierOrderPolicyParams(ParamsSection):
    """Parâmetros de `motor.policy.supplier.apply_supplier_constraints` (Sprint 10).

    Separado de `GuardrailsParams` de propósito -- aquela seção é Sprint 13
    (as seis regras de guarda), esta é só o teto do preenchimento até o
    pedido mínimo, que já existe nesta sprint.
    """

    max_additional_packs_for_minimum: PositiveInt


class EconomicsParams(ParamsSection):
    """Margem por categoria, custo de capital, e alpha (nível de serviço-alvo) por categoria.

    `uniform_unit_price` (Sprint 8): preço único por unidade vendida, aplicado
    a todo item -- o Favorita não tem preço em nenhuma linha do bruto.
    `motor.metrics.financial` prova que a escala desse valor não afeta a
    métrica ordenadora nem o giro (só o tamanho dos R$ absolutos reportados);
    ver a docstring daquele módulo para a prova e para as limitações que essa
    escolha introduz.
    """

    capital_cost_annual: NonNegativeFloat
    uniform_unit_price: PositiveFloat
    default_margin_pct: Fraction
    category_margin_pct: dict[str, Fraction]
    default_alpha: Fraction
    category_alpha: dict[str, Fraction]


class GuardrailsParams(ParamsSection):
    """Regras de guarda aplicadas depois da política, antes do pedido final (Sprint 8)."""

    max_coverage_days: PositiveFloat
    max_order_variation_pct: NonNegativeFloat
    weekly_budget: NonNegativeFloat | None = None


class ModelParams(ParamsSection):
    """Quantis previstos e cadência de re-treino do forecaster.

    CLAUDE.md, seção 8: re-treino semanal, nunca diário.
    """

    quantiles: Annotated[list[Fraction], MinLen(1)]
    retrain_cadence_days: PositiveInt


class ExperimentArmParams(ParamsSection):
    """Um braço de experimento: nome, forecaster e política usados."""

    name: str
    forecaster: str
    policy: str


class ExperimentsParams(ParamsSection):
    """Os braços comparados pelo runner (Sprint 9)."""

    arms: Annotated[list[ExperimentArmParams], MinLen(1)]


class AnomalyPeriodParams(ParamsSection):
    """Um período de distorção conhecida na série (Sprint 3, D1: ex. terremoto).

    Marca `Sale.is_anomaly`/`anomaly_reason` no reindex -- nunca remove linha.
    Apagar dado em silêncio é o mesmo pecado de descartar negativo em
    silêncio (CLAUDE.md, seção 8).
    """

    name: str
    start: date
    end: date
    reason: str


class CanonicalParams(ParamsSection):
    """Parâmetros da normalização canônica do Favorita (Sprint 3, `motor.io.loaders`).

    `window_start`/`window_end` são a janela de trabalho (D1). Cada valor em
    `params.yaml` carrega a etiqueta `# medido:` ou `# arbitrado:` de origem
    (CLAUDE.md, seção 2) -- ver comentários lá, não aqui.
    """

    window_start: date
    window_end: date
    delisting_gap_days: PositiveInt
    fractional_threshold: Fraction
    anomalies: list[AnomalyPeriodParams]


class Params(ParamsSection):
    """Todas as premissas numéricas do projeto, carregadas de `config/params.yaml`."""

    data: DataParams
    profiling: ProfilingParams
    subset_selection: SubsetSelectionParams
    simulation: SimulationParams
    forecast_naive: ForecastNaiveParams
    erp_baseline: ErpBaselineParams
    supplier_assumptions: SupplierAssumptionsParams
    supplier_order_policy: SupplierOrderPolicyParams
    economics: EconomicsParams
    guardrails: GuardrailsParams
    model: ModelParams
    experiments: ExperimentsParams
    canonical: CanonicalParams


def load_params(path: Path) -> Params:
    """Carrega `params.yaml` e valida contra `Params`."""
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Params.model_validate(raw)

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
from pydantic import BaseModel, ConfigDict, model_validator

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


class ForecastStatisticalParams(ParamsSection):
    """Parâmetros de `motor.forecast.statistical.StatisticalForecaster` (Sprint 12).

    `level_window_weeks` (nível recente) e `seasonal_window_weeks` (índice de
    sazonalidade semanal) são janelas INDEPENDENTES uma da outra e de
    `forecast_naive.moving_average_weeks` -- ao contrário do braço 1, este
    modelo não precisa concordar com nenhuma política sobre o tamanho da
    janela (`BasestockPolicy` não deriva nada do histórico bruto, só consome
    `predict_quantiles`). Todos os três valores são arbitrados: pisos
    plausíveis para o nível não ficar refém de poucos dias e para o índice
    sazonal ter pelo menos ~12 ocorrências de cada dia da semana sem usar
    dado velho demais.
    """

    level_window_weeks: PositiveInt
    seasonal_window_weeks: PositiveInt
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


class PurchaseListSupplierAssumptionsParams(ParamsSection):
    """Premissas de fornecedor REALISTAS, só para `motor.reporting.
    purchase_list` (Sprint 17, Etapa 3.15) -- NÃO usadas por `motor.io.
    loaders`, `motor.experiments.run`/`sensitivity`/`iso_service`, nem por
    nenhum resultado já medido (a comparação iso-serviço da Etapa 3.12 usa
    `pack_multiple=1,0`/`min_order=0,0` uniformes, do canônico, e não foi
    recalculada com isto).

    O canônico Favorita não tem fardo nem pedido mínimo reais (Sprint 3, D7)
    -- `Item.pack_multiple`/`Supplier.min_order_value` chegam nulos/zerados
    do bruto e o resto do projeto os trata com o default arbitrado mais
    simples (1,0 / 0,0), documentado como tal. Isso é honesto para medir a
    política, mas esvazia a lista de compra como peça de venda: nenhuma
    restrição de fornecedor tem chance de disparar. Este bloco arbitra
    valores plausíveis, por família de categoria, do mesmo jeito que
    `motor.assumptions`/`EconomicsParams` já arbitram margem e alpha -- a
    origem real dessas regras (documento de negócio) é a entrevista de
    onboarding com o fornecedor, não o ERP.

    `pack_multiple_by_category`: por família --
    perecível fresco vendido a peça/peso, sem fardo real (1,0): PRODUCE,
    MEATS, POULTRY, SEAFOOD, DELI; giro rápido, fardo pequeno (6,0):
    BREAD/BAKERY, DAIRY, EGGS, FROZEN FOODS, PREPARED FOODS; mercearia seca/
    limpeza/higiene, fardo padrão (12,0): GROCERY I, GROCERY II, CLEANING,
    PERSONAL CARE, HOME CARE, BABY CARE; bebidas, pallet fechado (24,0):
    BEVERAGES, LIQUOR,WINE,BEER; bazar/não-alimentar, fardo pequeno (6,0):
    as 15 categorias restantes.

    `min_order_value_by_category`: R$ 2.000,00 para fornecedor de categoria
    com MENOS DE 50 ITENS no canônico completo (proxy de fornecedor pequeno/
    especializado -- entrega dedicada não se paga sozinha em volume baixo);
    R$ 0,00 para os demais (alto volume, entrega já frequente e justificada
    por si). Critério calculado uma vez sobre o canônico, valores
    congelados aqui -- não recalculado em runtime.
    """

    pack_multiple_by_category: dict[str, PositiveFloat]
    min_order_value_by_category: dict[str, NonNegativeFloat]


class EconomicsParams(ParamsSection):
    """Margem por categoria, custo de capital, e alpha (nível de serviço-alvo) por categoria.

    `uniform_unit_price` (Sprint 8): preço único por unidade vendida, aplicado
    a todo item -- o Favorita não tem preço em nenhuma linha do bruto.
    `motor.metrics.financial` prova que a escala desse valor não afeta a
    métrica ordenadora nem o giro (só o tamanho dos R$ absolutos reportados);
    ver a docstring daquele módulo para a prova e para as limitações que essa
    escolha introduz.

    `default_alpha` (Sprint 12): `motor.policy.basestock.BasestockPolicy` usa
    este valor, UNIFORME para todo item -- decisão explícita da sprint, não
    esquecimento: braço 2 e braço 3 (sprint futura) precisam compartilhar o
    mesmo alpha para que a diferença de R$ entre eles seja atribuível só à
    previsão, não a uma mudança simultânea de alpha por categoria. Ver
    `config/params.yaml` para o registro completo do trade-off.

    `category_alpha` continua com as chaves genéricas antigas (hortifruti/
    mercearia/bebidas/limpeza), que NÃO batem com `Item.category` real do
    subconjunto de trabalho -- ainda não está ligado a nenhuma política
    (`default_alpha` sempre vence). Remapear para as categorias reais,
    como a Sprint 8 fez para `category_margin_pct`, é decisão de negócio
    (qual categoria tolera mais ruptura vs. mais capital parado) adiada de
    propósito para uma sprint de calibração dedicada -- não confundir "não
    wireado ainda" com "sem risco": todo valor aqui é validado contra
    `model.quantiles` mesmo assim (ver `Params._alpha_bate_com_a_grade_de_quantis`),
    porque um valor fora da grade quebraria `compute_order_quantity` no
    instante em que alguém finalmente ligasse essa chave.
    """

    capital_cost_annual: NonNegativeFloat
    uniform_unit_price: PositiveFloat
    default_margin_pct: Fraction
    category_margin_pct: dict[str, Fraction]
    default_alpha: Fraction
    category_alpha: dict[str, Fraction]


class GuardrailsParams(ParamsSection):
    """Regras de guarda aplicadas depois da política, antes do pedido final
    -- Sprint 13, implementadas em `motor.policy.guardrails` (CLAUDE.md,
    emenda Sprint 17: até aqui, este bloco nunca tinha sido lido por
    nenhuma função).

    Seis regras no desenho original; quatro implementadas aqui, duas
    declaradas como não implementadas (promoção prevista -- precisa de
    calendário promocional que o canônico não carrega; item âncora --
    precisa de análise de cesta, fora de escopo da v1) -- ver
    `motor.policy.guardrails.NOT_IMPLEMENTED_GUARDRAILS`.

    `shelf_life_days_by_category` substitui o antigo campo escalar
    `max_coverage_days` (nunca lido) -- VALIDADE física por FAMÍLIA de
    categoria (perecível fresco 7 dias, giro rápido 14, bebidas 30,
    mercearia seca e bazar 45), não um teto de negócio arbitrário e não um
    número único para o portfólio inteiro. Decisão de negócio, não
    estimada -- valores corretos como validade (Etapa 3.16.2).

    Emenda (Etapa 3.16.2, Sprint 17): o teto EFETIVO de cobertura de
    `motor.policy.guardrails.apply_coverage_cap` é
    `max(shelf_life_days, risk_window_days)` -- NUNCA a validade sozinha.
    Pedir menos que a própria janela de risco (`lead_time_days +
    review_period_days`) garante ruptura estrutural; isso não é proteção,
    é bug. A Etapa 3.16 original aplicou a validade como teto sem esse
    piso: nas famílias de perecível fresco/giro rápido, a janela de risco
    da célula de teste (lt=7/rp=14 -> 21 dias) já é maior que a validade
    (7/14 dias) -- 100% dos itens dessas famílias batiam o teto, não
    porque a política pedisse demais (mediana de cobertura pré-corte era
    ~22 dias em TODAS as famílias, igual à janela), mas porque o teto era
    fisicamente menor que o ciclo de compra testado. Quando
    `risk_window_days > shelf_life_days`, é a guarda detectando um
    parâmetro de fornecedor impossível para aquela família (comprar
    hortifruti a cada 14 dias não é uma prática real) -- registrado no
    motivo do item, não escondido atrás de um corte silencioso.

    `variation_limit_multiple`/`variation_lookback_days`: sugestão acima de
    `variation_limit_multiple` vezes a média das compras (não vendas) dos
    últimos `variation_lookback_days` dias do item vai para revisão humana
    -- SINALIZADA, não cortada.

    `new_item_min_history_days`/`new_item_min_days_with_sales`: item com
    menos de `new_item_min_history_days` dias desde o primeiro registro de
    venda, OU menos de `new_item_min_days_with_sales` dias com venda no
    histórico, é "novo" -- sai por quantidade fixa (mediana da categoria),
    nunca por modelo.

    `weekly_budget_rs`: orçamento semanal arbitrado. Recalibrado na Etapa
    3.16.3 para R$250.000 (R$500k/ciclo de 2 semanas) -- o valor original
    (R$200k) foi calibrado contra um total contaminado pelo teto de
    cobertura quebrado; corrigido o teto, a necessidade real da política
    ficou em ~R$462k/ciclo, e R$400k (o orçamento antigo x2) cortava 13,5%
    do pedido TODA semana -- subfinanciamento crônico, não restrição de
    caixa. Critério do novo valor: pouco ACIMA da necessidade típica, para
    a regra disparar só em semana atípica, não toda semana. Fora do
    orçamento, itens são cortados por ordem de margem gerada por real
    investido (maior margem primeiro), do fim pra trás -- nunca
    proporcionalmente.

    `cash_constraint_category_floor_fraction`: piso de negócio (Etapa
    3.16.4) -- nenhuma categoria cai abaixo desta fração do seu próprio
    valor originalmente sugerido, qualquer que seja a margem. Sem este
    piso, o corte por margem (acima) zerava categorias inteiras de baixa
    margem -- perecível fresco, mercearia -- que são item ÂNCORA por
    desenho (margem baixa DE PROPÓSITO, para trazer o cliente à loja),
    exatamente o padrão que faz um dono de mercado achar que o sistema não
    entende varejo. Valor de 0,60 é ARBITRADO -- critério: preserva
    presença de gôndola em toda categoria, cortando fundo o suficiente
    (40%) para a restrição de caixa ainda ter efeito real; não é resultado
    de otimização. Quando a SOMA dos pisos de todas as categorias sozinha
    excede o orçamento, a guarda não tenta preservar todos -- corta por
    margem MÉDIA da categoria sobre os próprios pisos (ver
    `motor.policy.guardrails.apply_cash_constraint`) e registra um alerta
    separado: isso significa que o orçamento não cobre nem o mínimo
    operacional da loja, informação de negócio, não detalhe de algoritmo.
    """

    shelf_life_days_by_category: dict[str, PositiveFloat]
    variation_limit_multiple: PositiveFloat
    variation_lookback_days: PositiveInt
    new_item_min_history_days: PositiveInt
    new_item_min_days_with_sales: PositiveInt
    weekly_budget_rs: PositiveFloat
    cash_constraint_category_floor_fraction: Fraction


class FeatureCalendarParams(ParamsSection):
    """Parâmetros de `motor.features.calendar` (Sprint 14): início de mês,
    quinzena e dia de pagamento. Feriado não tem parâmetro aqui -- vem
    inteiramente do dado bruto (`holidays_events`), sem limiar arbitrado.

    `payday_days_of_month`: cada valor é um dia do mês (1-31) em que cai
    pagamento, ou `-1` como sentinela do ÚLTIMO dia do mês (calendário, não
    número mágico de dia-31 que erraria em fevereiro). Arbitrado: convenção
    comum de folha de pagamento na América Latina (dia 15 e fechamento do
    mês) -- não medido, o dataset público não traz data de pagamento real.
    """

    month_start_max_day: PositiveInt
    quinzena_split_day: PositiveInt
    payday_days_of_month: Annotated[list[int], MinLen(1)]

    @model_validator(mode="after")
    def _payday_days_validos(self) -> FeatureCalendarParams:
        for dia in self.payday_days_of_month:
            if dia != -1 and not 1 <= dia <= 31:
                msg = (
                    f"payday_days_of_month deve conter -1 (sentinela de último dia do "
                    f"mês) ou um dia entre 1 e 31; recebeu {dia!r}"
                )
                raise ValueError(msg)
        return self


class FeatureHistoricoParams(ParamsSection):
    """Janelas de `motor.features.build` (Sprint 14): lags, médias/somas
    móveis e proporções, todas em dias corridos -- fixas no config, não
    derivadas do `lead_time`/`review_period` de cada item.

    Fixas de propósito: o braço 3 é um modelo GLOBAL (CLAUDE.md, seção 3/9),
    treinado sobre o painel inteiro de itens com o MESMO esquema de colunas.
    Se a janela de cada feature viesse do fornecedor de cada item, a mesma
    coluna significaria janelas diferentes em linhas diferentes, quebrando a
    comparabilidade entre linhas que um modelo global pressupõe.

    `risk_window_reference_days` é INDEPENDENTE das outras seções -- não
    deriva automaticamente de `supplier_assumptions.default_lead_time_days` +
    `default_review_period_days`, mesmo espelhando o valor deles hoje (3+7=10).
    Motivo: acoplar as duas seções faria uma mudança de premissa de
    fornecedor alterar silenciosamente o esquema de features. Se fornecedores
    reais divergirem desse default uniforme, é uma decisão de calibração
    futura revisitar este valor -- não uma inconsistência a esconder.
    """

    lag_days: Annotated[list[PositiveInt], MinLen(1)]
    rolling_windows_days: Annotated[list[PositiveInt], MinLen(1)]
    risk_window_reference_days: PositiveInt


class FeaturesParams(ParamsSection):
    """Parâmetros de `motor.features` (Sprint 14). `active_features` é a
    lista exata de colunas de feature emitidas por `build_features`/
    `build_training_matrix`, na ordem dada -- desliga feature sem mexer no
    código (CLAUDE.md, seção 2). Cada nome tem que bater com uma coluna de
    fato calculada a partir de `calendar`/`historico` acima (`build_features`
    valida isso e levanta erro claro se não bater, nunca ignora silenciosamente
    um nome desconhecido nem se cala sobre uma feature esquecida na lista)."""

    calendar: FeatureCalendarParams
    historico: FeatureHistoricoParams
    active_features: Annotated[list[str], MinLen(1)]


class ModelParams(ParamsSection):
    """Quantis previstos e cadência de re-treino do forecaster.

    CLAUDE.md, seção 8: re-treino semanal, nunca diário.
    """

    quantiles: Annotated[list[Fraction], MinLen(1)]
    retrain_cadence_days: PositiveInt


class QuantileGbmParams(ParamsSection):
    """Parâmetros de `motor.forecast.quantile_gbm` (Sprint 15): um LightGBM
    por quantil de `model.quantiles` (grade compartilhada -- não uma lista
    nova), modelo GLOBAL sobre o painel inteiro, re-treinado a cada
    `model.retrain_cadence_days` dentro de uma origem móvel.

    `training_window`: EXPANSIVA, com piso mínimo de origens
    (`min_training_origins`) -- decisão aprovada explicitamente (não
    deslizante). `min_training_origins` é o piso: a primeira origem do
    backtest cujo histórico disponível não o atinge levanta erro claro
    (`InsufficientTrainingHistoryError`), nunca um fit silencioso com poucas
    origens.

    `decay_half_life_days`: resolve por dentro a tensão "expansiva mistura
    regime antigo com recente" -- peso de amostra por idade da linha,
    `weight = 0.5 ** (idade_dias / decay_half_life_days)`. `None` é o valor
    NEUTRO e é o default: sem decaimento, todo peso = 1.0, byte a byte igual
    a uma janela expansiva sem ponderação nenhuma. Comparar janela expansiva
    "pura" contra decaimento de meia-vida diferente vira, a partir de agora,
    um experimento de config (Sprint 16), não uma escolha arquitetural
    enterrada nesta sprint.

    `stock` NÃO tem parâmetro aqui nem em `FeaturesParams`: decisão explícita
    (Sprint 15) -- o dataset público não tem saldo de estoque, e uma feature
    derivada dele só existiria dentro da simulação, nunca num cliente real
    sem esse dado. Ver CLAUDE.md, seção 4, para o registro completo.

    Determinismo (CLAUDE.md, seção 2): `seed`, `num_threads` fixos,
    `deterministic=True` e `force_row_wise=True` sempre ativados no treino
    -- não são configuráveis, são invariantes do módulo (ver
    `motor.forecast.quantile_gbm._LGBM_FIXED_PARAMS`).
    """

    learning_rate: PositiveFloat
    num_leaves: PositiveInt
    num_boost_round: PositiveInt
    num_threads: PositiveInt
    min_training_origins: PositiveInt
    decay_half_life_days: PositiveFloat | None = None
    seed: int
    model_cache_dir: Path


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


class ClientLoaderParams(ParamsSection):
    """Premissas do loader de dado de cliente (Sprint 22, `motor.io.loaders_cliente`).

    Nenhum limiar das decisões DC1-DC9 vive no código -- todos aqui, com a
    origem de cada um em `config/params.yaml`.

    `weekly_budget_rs` é OPCIONAL de propósito (`None`): a escala do
    `guardrails.weekly_budget_rs` do Favorita não serve para um cliente, e
    inventar um orçamento seria inventar uma restrição. Sem ele, a restrição
    de caixa fica DESLIGADA no modo `canonical` -- declarado na aba Notas da
    lista de compra, não escondido.
    """

    principal_supplier_window_days: PositiveInt
    generic_codes: list[str]
    generic_description_patterns: list[str]
    generic_revenue_share_warn: Fraction
    emergency_name_patterns: list[str]
    emergency_cnae_prefixes: list[str]
    emergency_warn_max_notes: PositiveInt
    cost_divergence_tolerance: Fraction
    idle_days_threshold: PositiveInt
    default_shelf_life_days: PositiveInt
    default_perishable_shelf_life_days: PositiveInt
    simulation_start_after_days: PositiveInt
    weekly_budget_rs: PositiveFloat | None = None


class Params(ParamsSection):
    """Todas as premissas numéricas do projeto, carregadas de `config/params.yaml`."""

    data: DataParams
    profiling: ProfilingParams
    subset_selection: SubsetSelectionParams
    simulation: SimulationParams
    forecast_naive: ForecastNaiveParams
    forecast_statistical: ForecastStatisticalParams
    erp_baseline: ErpBaselineParams
    supplier_assumptions: SupplierAssumptionsParams
    supplier_order_policy: SupplierOrderPolicyParams
    purchase_list_supplier_assumptions: PurchaseListSupplierAssumptionsParams
    economics: EconomicsParams
    guardrails: GuardrailsParams
    features: FeaturesParams
    model: ModelParams
    quantile_gbm: QuantileGbmParams
    experiments: ExperimentsParams
    canonical: CanonicalParams
    client_loader: ClientLoaderParams

    @model_validator(mode="after")
    def _alpha_bate_com_a_grade_de_quantis(self) -> Params:
        """`compute_order_quantity` (motor.policy.target_level, regra do
        enunciado) rejeita `alpha` que não seja uma chave presente nos
        quantis produzidos pelo forecaster -- sem esta guarda, um
        `default_alpha`/`category_alpha` fora de `model.quantiles` só
        estouraria `ValueError` lá dentro, decisão a decisão, longe da causa
        raiz (config/params.yaml). `category_alpha` ainda não está ligado a
        nenhuma política (Sprint 12: `BasestockPolicy` usa só
        `default_alpha`, uniforme -- ver docstring de `EconomicsParams` e o
        manifesto do braço), mas é validado do mesmo jeito: um valor fora da
        grade hoje é uma armadilha armada para quem remapear as chaves
        amanhã, não um erro inofensivo por estar inerte.
        """
        grade = self.model.quantiles
        grade_set = set(grade)
        if self.economics.default_alpha not in grade_set:
            msg = (
                f"economics.default_alpha={self.economics.default_alpha!r} não é um dos "
                f"quantis produzidos pelo forecaster (model.quantiles={grade!r}) -- "
                "compute_order_quantity rejeitaria esse alpha; ajuste default_alpha ou "
                "acrescente o valor a model.quantiles."
            )
            raise ValueError(msg)
        for categoria, alpha in self.economics.category_alpha.items():
            if alpha not in grade_set:
                msg = (
                    f"economics.category_alpha[{categoria!r}]={alpha!r} não é um dos "
                    f"quantis produzidos pelo forecaster (model.quantiles={grade!r}) -- "
                    "mesmo não estando ligado a nenhuma política ainda, um valor fora da "
                    "grade quebraria compute_order_quantity assim que essa chave for consumida."
                )
                raise ValueError(msg)
        return self


def load_params(path: Path) -> Params:
    """Carrega `params.yaml` e valida contra `Params`."""
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Params.model_validate(raw)

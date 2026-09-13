"""Gerador da lista de compra (Sprint 5, entregue nas Etapas 3.14-3.16 da
Sprint 17): um xlsx por fornecedor, para uma data de decisão dentro do
período simulado.

Braço 2 (estatístico + nível-alvo) em `alpha=0,66` -- o iso-serviço medido
na Etapa 3.12, célula `lead_time=7`/`review_period=14` (`motor.experiments.
iso_service`). Não o braço 3: a vantagem do braço 3 sobre o 2 é pequena e a
grade dele é mais grosseira (ver `results/iso_servico/README.md`); para a
peça de venda, o modelo simples, auditável e sem retreino semanal é o que
faz sentido mostrar -- argumento de produto, não concessão. `alpha=0,66` só
foi validado NESTA janela de risco (lt=7/rp=14); por isso este módulo
sobrescreve `suppliers` para a mesma célula, em vez de usar o lead_time/
review_period real do canônico (lt=3/rp=7) -- usar o alpha calibrado numa
janela diferente da que ele foi medido seria uma combinação nova, nunca
testada.

ORDEM DE APLICAÇÃO (fixa, não reordenar sem reabrir o desenho)
--------------------------------------------------------------
1. Política (braço 2) decide a quantidade DESEJADA por item, ponto a
   ponto, sem saber de fornecedor nem de guarda nenhuma.
2. Item novo (`motor.policy.guardrails.is_new_item`) substitui a decisão
   inteira por quantidade fixa (mediana da categoria) -- itens novos NÃO
   passam pelas regras 3/4 abaixo, saem só pela regra 5.
3. Teto de cobertura (`apply_coverage_cap`) corta a quantidade, só para
   item NÃO-novo -- teto EFETIVO = max(validade da família, janela de
   risco do item); nunca a validade sozinha (Etapa 3.16.2: validade menor
   que a janela garantiria ruptura estrutural, não seria proteção).
4. Limite de variação (`check_order_variation`) sinaliza (não corta), só
   para item NÃO-novo -- precisa de média de compras recentes, que item
   novo não tem por definição.
5. `apply_supplier_constraints` (Sprint 10): fardo, pedido mínimo,
   calendário -- por fornecedor, sobre a quantidade já filtrada pelas
   regras 2-4.
6. Restrição de caixa (`apply_cash_constraint`) -- ÚLTIMA, sobre o
   portfólio INTEIRO (todos os fornecedores juntos), porque orçamento é
   uma restrição da empresa, não de um fornecedor isolado. Roda depois do
   fardo/mínimo porque o orçamento é sobre R$ de fato gastos, não sobre a
   sugestão bruta.

LIMITAÇÃO DECLARADA: a restrição de caixa (passo 6) pode cortar um item
depois que seu fornecedor já bateu o próprio pedido mínimo (passo 5) --
isso reabriria "mínimo inatingível" para aquele fornecedor, e esta versão
NÃO revalida esse ciclo (re-rodar `apply_supplier_constraints` depois de
cortar por caixa poderia cortar outro item por mínimo, que poderia mudar o
corte de caixa de novo -- um loop de ponto-fixo fora do escopo desta
etapa). Fica registrado aqui, não escondido.

REGRAS DE GUARDA -- as quatro implementadas, e as duas que não
--------------------------------------------------------------
As quatro regras de `GuardrailsParams`/`motor.policy.guardrails` (teto de
cobertura, limite de variação, restrição de caixa, item novo) foram
implementadas na Etapa 3.16 -- até ali, `Params.guardrails` nunca tinha
sido lido por nenhuma função (CLAUDE.md, emenda Sprint 17). As duas
restantes do desenho original (promoção prevista, item âncora) NÃO estão
implementadas -- ver `motor.policy.guardrails.NOT_IMPLEMENTED_GUARDRAILS`
para o motivo de cada uma.

A coluna "motivo" da aba Exceções combina os `AdjustmentReason` de
`apply_supplier_constraints` (Sprint 10) com os `GuardrailFlag` das quatro
regras acima -- os dois tipos de registro estruturado que este módulo
consome, nenhum dos dois inventado aqui.

PREMISSAS DE FORNECEDOR -- Etapa 3.15
--------------------------------------------------------------
`Params.purchase_list_supplier_assumptions` arbitra fardo por família de
categoria e pedido mínimo em R$ para fornecedor pequeno -- ver a docstring
de `PurchaseListSupplierAssumptionsParams`. Como qualquer premissa deste
projeto, é arbitrada e declarada, nunca escondida.

ESCOPO -- só a lista de compra, não a comparação iso-serviço
--------------------------------------------------------------
As premissas de fornecedor (Etapa 3.15) E as regras de guarda (Etapa 3.16)
valem SÓ para este módulo. A comparação iso-serviço da Etapa 3.12
(`results/iso_servico/`) foi medida sem nenhuma das duas e NÃO foi
recalculada -- os números de lá continuam os números de lá. As guardas
mudam a política (cortam/substituem quantidade) e por isso mudariam
`decision_metric` se rodadas sobre o período inteiro; medir esse efeito é
um experimento próprio e declarado, não um efeito colateral desta lista.

DESCRIÇÃO DE ITEM -- limitação do dataset, não deste módulo
--------------------------------------------------------------
`Item.description`/`Item.ean` são 100% nulos no canônico Favorita (Sprint 3,
D7 -- CLAUDE.md): o dataset não identifica produto por nome. Este módulo NÃO
inventa descrição -- usa `category` (33 valores, sempre presente) como único
identificador legível além do `item_id`. Está declarado explicitamente na
planilha (aba "Notas", ver `write_supplier_workbook`), não escondido.
"""

from __future__ import annotations

import argparse
import statistics
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final

import polars as pl
import xlsxwriter

from motor.config import Params, load_params
from motor.experiments.iso_service import (
    ARM2_CHOSEN_ALPHA,
    CELL_REVIEW_PERIOD_DAYS,
    CanonicalTables,
    build_arm2_single_alpha_params,
    cell_suppliers,
    load_canonical_tables,
)
from motor.experiments.run import load_or_select_subset
from motor.experiments.shared import build_simulator_for_pair
from motor.forecast.statistical import StatisticalForecaster
from motor.io.contracts import Supplier
from motor.policy.base import DecisionContext
from motor.policy.basestock import BasestockPolicy
from motor.policy.guardrails import (
    NOT_IMPLEMENTED_GUARDRAILS,
    CashConstraintCandidate,
    CategoryFloorAlert,
    GuardrailFlag,
    GuardrailReason,
    apply_cash_constraint,
    apply_coverage_cap,
    check_order_variation,
    is_new_item,
    new_item_quantity,
)
from motor.policy.supplier import (
    AdjustmentReason,
    ItemPurchaseInfo,
    OrderOutcome,
    apply_supplier_constraints,
)

_TRAILING_DEMAND_WINDOW_DAYS: Final[int] = 28
"""Janela de demanda diária esperada usada pra cobertura em dias e pro
preenchimento até o mínimo -- últimos 28 dias de histórico REAL antes de
`as_of` (não a média do warmup inteiro, que fica velha demais conforme a
simulação avança); mesma ideia de `forecast_naive.moving_average_weeks=4`,
mas medida no ponto de decisão, não herdada de um parâmetro de outro braço."""

_ADJUSTMENT_LABELS: Final[dict[AdjustmentReason, str]] = {
    AdjustmentReason.ARREDONDAMENTO_DE_FARDO: "arredondado para cima (fardo)",
    AdjustmentReason.PREENCHIMENTO_DE_MINIMO: "aumentado para bater pedido mínimo do fornecedor",
    AdjustmentReason.PEDIDO_ADIADO: "pedido adiado -- mínimo do fornecedor inatingível hoje",
}

_OUTCOME_LABELS: Final[dict[OrderOutcome, str]] = {
    OrderOutcome.PEDIDO_EMITIDO: "pedido emitido",
    OrderOutcome.FORA_DO_CALENDARIO: "fora do calendário de pedido",
    OrderOutcome.MINIMO_INATINGIVEL: "mínimo do fornecedor inatingível",
}

_EXCEPTION_SUPPLIER_REASONS: Final[frozenset[AdjustmentReason]] = frozenset(
    {AdjustmentReason.PREENCHIMENTO_DE_MINIMO, AdjustmentReason.PEDIDO_ADIADO}
)

REALISTIC_SUPPLIER_ASSUMPTIONS_NOTE: Final[str] = (
    "Fardo (pack_multiple) e pedido mínimo (min_order_value) desta lista vêm de "
    "Params.purchase_list_supplier_assumptions (config/params.yaml), arbitrados por "
    "família de categoria -- NÃO do canônico (que tem os dois zerados/unitários, "
    "premissa mais simples). Fardo: perecível fresco vendido a peça/peso = 1 (sem "
    "fardo real); giro rápido (padaria, laticínios, ovos, congelados, prontos) = 6; "
    "mercearia seca/limpeza/higiene = 12; bebidas (pallet fechado) = 24; bazar/não-"
    "alimentar = 6. Pedido mínimo: R$ 2.000,00 para fornecedor de categoria com menos "
    "de 50 itens no canônico completo (fornecedor pequeno/especializado); R$ 0,00 "
    "para os demais."
)

GUARDRAILS_NOTE: Final[str] = (
    "Quatro regras de guarda ativas (Sprint 13, implementadas na Etapa 3.16, teto "
    "corrigido na 3.16.2, orçamento recalibrado na 3.16.3, piso de categoria na "
    "3.16.4): teto de cobertura = max(validade da família, janela de risco) -- nunca "
    "a validade sozinha, ver nota abaixo; limite de variação (2x a média de compras "
    "recentes, sinaliza sem cortar); restrição de caixa com piso de 60% por categoria "
    "(orçamento do ciclo, corta por margem só acima do piso, nunca proporcionalmente "
    "-- ver nota abaixo); item novo (quantidade fixa pela mediana da categoria). Duas "
    "regras do desenho original NÃO implementadas: " + " | ".join(NOT_IMPLEMENTED_GUARDRAILS)
)

ISO_SERVICE_SCOPE_NOTE: Final[str] = (
    "Premissas de fornecedor (Etapa 3.15) e regras de guarda (Etapa 3.16) valem SÓ "
    "para esta lista de compra. A comparação iso-serviço da Etapa 3.12 "
    "(results/iso_servico/) foi medida sem nenhuma das duas e NÃO foi recalculada -- "
    "os dois cenários NÃO são comparáveis linha a linha. As guardas mudam a política "
    "(cortam/substituem quantidade); rodadas sobre o período inteiro, mudariam "
    "decision_metric -- medir esse efeito é experimento próprio, declarado, não feito "
    "aqui."
)

CASH_CONSTRAINT_LIMITATION_NOTE: Final[str] = (
    "A restrição de caixa roda por último, sobre o portfólio inteiro, depois do fardo/"
    "mínimo de fornecedor -- ela PODE cortar um item cujo fornecedor já tinha batido o "
    "próprio pedido mínimo, o que reabriria 'mínimo inatingível' para esse fornecedor. "
    "Esta versão NÃO revalida esse ciclo (um loop de ponto-fixo ficou fora do escopo "
    "desta etapa) -- declarado, não escondido."
)

CASH_CONSTRAINT_CATEGORY_FLOOR_NOTE: Final[str] = (
    "CORRIGIDO na Etapa 3.16.4: 'margem gerada por real investido' é o critério certo "
    "para alocar capital marginal, mas sem piso por categoria ele zerava categorias "
    "inteiras de baixa margem quando a regra disparava -- na medição da Etapa 3.16.3 "
    "(antes desta correção), 3 categorias inteiras (GROCERY II, MEATS, SEAFOOD) e "
    "mais 5 quase inteiras (DAIRY, EGGS, GROCERY I, POULTRY, PRODUCE -- 75-95% dos "
    "itens) foram cortadas, todas com margem 14-20%, exatamente os itens perecíveis/"
    "de mercearia que trazem o cliente à loja -- itens ÂNCORA por desenho (margem "
    "baixa DE PROPÓSITO). Agora nenhuma categoria cai abaixo de 60% do seu próprio "
    "valor originalmente sugerido, qualquer que seja a margem -- ver "
    "Params.guardrails.cash_constraint_category_"
    "floor_fraction (arbitrado, critério: preserva presença de gôndola cortando "
    "fundo o suficiente pra regra ainda ter efeito real). Quando a soma dos pisos "
    "sozinha excede o orçamento, a guarda não tenta salvar todas as categorias -- "
    "corta por margem média sobre os PRÓPRIOS pisos e emite um alerta separado "
    "(informação de negócio: o orçamento não cobre nem o mínimo operacional)."
)

RISK_WINDOW_ARCHITECTURE_LIMITATION_NOTE: Final[str] = (
    "O teto de cobertura só é uma guarda ATIVA quando a janela de risco (lead_time + "
    "review_period) é menor que a validade da família -- quando a janela é MAIOR (caso "
    "de perecível fresco/giro rápido nesta célula, ver Etapa 3.16.2), o teto efetivo "
    "vira a própria janela, e a guarda para de proteger contra excesso: ela só evita "
    "que o pedido peça MENOS que o mínimo estrutural, não pode evitar pedir mais que a "
    "validade permite. Em famílias assim, a proteção real teria que vir de um "
    "review_period MENOR, por fornecedor -- que o simulador hoje não suporta (é global "
    "para toda a simulação, motor.experiments.shared). Isto é DÉBITO DE ARQUITETURA, "
    "não bug: medir com uma janela de risco única penaliza estruturalmente a família "
    "onde o motor mais teria a ganhar (perecível, giro rápido)."
)

DESCRIPTION_MISSING_NOTE: Final[str] = (
    "Item.description e Item.ean são 100% nulos no dataset Favorita (Sprint 3, D7, "
    "CLAUDE.md) -- não há nome de produto no dado público. Esta lista usa apenas "
    "item_id (código) e category (33 categorias) para identificar o item; nenhuma "
    "descrição foi inventada."
)

ALPHA_CELL_MISMATCH_NOTE: Final[str] = (
    "alpha=0,66 foi calibrado (Etapa 3.12) na célula lead_time=7/review_period=14 -- "
    "esta lista roda NESSA célula (suppliers sobrescritos), não no lead_time=3/"
    "review_period=7 real do canônico. Usar este alpha numa janela de risco diferente "
    "seria uma combinação nova, nunca medida."
)


@dataclass(frozen=True)
class PurchaseListRow:
    """Uma linha da lista de compra de um fornecedor."""

    item_id: str
    category: str
    unit_of_sale: str
    quantity_units: float
    quantity_packs: float
    on_hand: float
    in_transit: float
    coverage_days_after_order: float | None
    value_rs: float
    margin_pct: float
    adjustments: tuple[str, ...]
    is_exception: bool


@dataclass(frozen=True)
class SupplierPurchaseList:
    """Lista de compra de um fornecedor, já separada em principal/exceções."""

    supplier_id: str
    category: str
    outcome: OrderOutcome
    min_order_value: float
    main: tuple[PurchaseListRow, ...]
    exceptions: tuple[PurchaseListRow, ...]


@dataclass(frozen=True)
class GuardrailFiringReport:
    """Quantas vezes cada regra de guarda disparou nesta lista -- o "log de
    disparo" pedido na Etapa 3.16. `counts` só tem as quatro regras
    implementadas; as duas não implementadas aparecem em `not_implemented`,
    nunca com contagem (contar disparo de uma regra que não existe seria
    fingir que ela foi checada)."""

    counts: dict[GuardrailReason, int]
    not_implemented: tuple[str, ...]
    category_floor_alert: CategoryFloorAlert | None = None
    """Presente quando a SOMA dos pisos de categoria sozinha excede o
    orçamento do ciclo (Etapa 3.16.4) -- informação de negócio (o
    orçamento não cobre o mínimo operacional da loja), não detalhe de
    algoritmo."""


def _trailing_avg_daily_demand(history: pl.DataFrame, as_of: date) -> float:
    """Média diária dos últimos `_TRAILING_DEMAND_WINDOW_DAYS` dias ANTES de
    `as_of` -- `0.0` se não houver nenhuma linha na janela (item sem venda
    recente; evita divisão por zero na cobertura em dias, ver `_coverage_days`)."""
    window_start = as_of - timedelta(days=_TRAILING_DEMAND_WINDOW_DAYS)
    window = history.filter((pl.col("date") >= window_start) & (pl.col("date") < as_of))
    if window.height == 0:
        return 0.0
    return float(window["units_sold"].mean())  # type: ignore[arg-type]


def _cycle_budget_rs(weekly_budget_rs: float, review_period_days: int) -> float:
    """Converte `weekly_budget_rs` (premissa SEMANAL, config/params.yaml)
    para o orçamento do CICLO desta decisão (`review_period_days` dias) --
    `weekly_budget_rs * review_period_days / 7`.

    Bug corrigido na Etapa 3.16.3: até aqui, `generate_purchase_list`
    passava `weekly_budget_rs` direto como orçamento do ciclo de 14 dias
    (`CELL_REVIEW_PERIOD_DAYS`), sem multiplicar por 2 -- todo disparo de
    `restricao_de_caixa` reportado nas Etapas 3.16/3.16.2/3.16.3 (antes
    desta correção) foi medido contra a METADE do orçamento pretendido
    (R$200k/250k tratados como orçamento de 2 semanas, quando deveriam
    valer R$400k/500k). Erro de implementação meu, não do valor arbitrado
    pelo usuário -- documentado aqui, não escondido.
    """
    return weekly_budget_rs * review_period_days / 7


def _coverage_days(position_after_order: float, expected_daily_demand: float) -> float | None:
    """`None` quando não há demanda esperada -- "dias de cobertura" não tem
    sentido para um item sem venda recente (divisão por zero disfarçada de
    número gigante seria pior que declarar ausência)."""
    if expected_daily_demand <= 0.0:
        return None
    return position_after_order / expected_daily_demand


def _pack_multiple_for(category: str, cell_params: Params) -> float:
    """Fardo REALISTA por família de categoria (Etapa 3.15) -- substitui o
    `Item.pack_multiple` do canônico (uniformemente 1,0, arbitrado como
    default mais simples) só para esta lista. Ver
    `PurchaseListSupplierAssumptionsParams` para os valores e o critério."""
    return cell_params.purchase_list_supplier_assumptions.pack_multiple_by_category[category]


def _min_order_value_for(category: str, cell_params: Params) -> float:
    """Pedido mínimo REALISTA por família de categoria (Etapa 3.15) --
    substitui o `Supplier.min_order_value` do canônico (uniformemente 0,0)
    só para esta lista. `min_order_units` NÃO é tocado por esta etapa --
    continua 0,0, herdado do canônico."""
    return cell_params.purchase_list_supplier_assumptions.min_order_value_by_category[category]


def _first_sale_and_days_with_sales(demand: pl.DataFrame, as_of: date) -> tuple[date | None, int]:
    """`(primeira data de venda > 0, nº de dias com venda > 0)`, sobre TODO
    o histórico disponível antes de `as_of` (não só a janela do
    subconjunto simulado) -- item novo é definido pelo histórico de venda
    real do item, não pela janela de simulação."""
    history = demand.filter(pl.col("date") < as_of)
    sold_days = history.filter(pl.col("units_sold") > 0.0)
    if sold_days.height == 0:
        return None, 0
    first_sale = sold_days["date"].min()
    assert isinstance(first_sale, date)
    return first_sale, sold_days.height


def _decide_item(
    *,
    lead_time_days: int,
    review_period_days: int,
    demand: pl.DataFrame,
    cell_params: Params,
    as_of: date,
    variation_lookback_days: int,
) -> tuple[float, float, float, float, float]:
    """Roda o `Simulator` do item até a véspera de `as_of` (posição real, não
    inventada), decide `as_of` explicitamente e devolve
    `(quantidade_desejada, on_hand, in_transit, demanda_diaria_esperada,
    media_de_compras_recentes)`.

    `media_de_compras_recentes`: média dos `order_placed` não-nulos e
    positivos dos últimos `variation_lookback_days` dias ANTES de `as_of`,
    lidos dos `DailyEvent` do próprio run parcial -- é a "média das compras
    dos últimos 90 dias" do limite de variação (Etapa 3.16), medida sobre
    compras SIMULADAS por este mesmo braço/alpha, não inventada e não
    confundida com venda. `0.0` sem nenhuma compra na janela (item novo, ou
    ainda não passou por um ciclo de revisão).

    Reescreve a lógica de `Simulator._decide` (privada) em vez de chamá-la
    porque este módulo precisa da quantidade DESEJADA antes de
    `apply_supplier_constraints` consolidar por fornecedor -- o loop por par
    loja-item não faz essa consolidação, de propósito (CLAUDE.md, seção 5).
    """
    forecaster = StatisticalForecaster(
        level_window_weeks=cell_params.forecast_statistical.level_window_weeks,
        seasonal_window_weeks=cell_params.forecast_statistical.seasonal_window_weeks,
        min_residual_samples=cell_params.forecast_statistical.min_residual_samples,
    )
    policy = BasestockPolicy(
        alpha=ARM2_CHOSEN_ALPHA, expected_window_days=lead_time_days + review_period_days
    )
    simulator = build_simulator_for_pair(
        demand=demand,
        forecaster=forecaster,
        policy=policy,
        lead_time_days=lead_time_days,
        review_period_days=review_period_days,
        start=cell_params.simulation.start_date,
        warmup_days=cell_params.simulation.warmup_days,
        quantiles=cell_params.model.quantiles,
    )
    events = simulator.run(cell_params.simulation.start_date, as_of - timedelta(days=1))
    on_hand, in_transit = simulator.position()

    lookback_start = as_of - timedelta(days=variation_lookback_days)
    recent_orders = [
        e.order_placed
        for e in events
        if e.order_placed is not None and e.order_placed > 0.0 and lookback_start <= e.day < as_of
    ]
    recent_average_purchase = statistics.mean(recent_orders) if recent_orders else 0.0

    history = demand.filter(pl.col("date") < as_of)
    forecaster.fit(history, as_of=as_of)
    forecast = forecaster.predict_quantiles(
        as_of, lead_time_days + review_period_days, [ARM2_CHOSEN_ALPHA]
    )
    ctx = DecisionContext(as_of=as_of, on_hand=on_hand, in_transit=in_transit, forecast=forecast)
    raw_quantity = policy.order(ctx)

    expected_daily_demand = _trailing_avg_daily_demand(demand, as_of)
    return raw_quantity, on_hand, in_transit, expected_daily_demand, recent_average_purchase


@dataclass(frozen=True)
class _ItemDecisions:
    """Saída intermediária de `_decide_all_items` -- um dict por atributo do
    item, todos com o mesmo conjunto de chaves (`item_id`)."""

    desired: dict[str, float]
    on_hand: dict[str, float]
    in_transit: dict[str, float]
    expected_daily_demand: dict[str, float]
    recent_average_purchase: dict[str, float]
    first_sale_date: dict[str, date | None]
    days_with_sales: dict[str, int]
    margin_pct: dict[str, float]
    risk_window_days: dict[str, float]
    item_purchase_info: dict[str, ItemPurchaseInfo]
    supplier_of: dict[str, str]
    category_of: dict[str, str]

    def position(self, item_id: str) -> float:
        return self.on_hand[item_id] + self.in_transit[item_id]


def _decide_all_items(
    item_supplier: pl.DataFrame, *, sales_subset: pl.DataFrame, cell_params: Params, as_of: date
) -> _ItemDecisions:
    """Roda `_decide_item` para cada linha de `item_supplier` (item + dados
    de fornecedor já resolvidos por join) e agrega os resultados por item_id."""
    decisions = _ItemDecisions(
        desired={},
        on_hand={},
        in_transit={},
        expected_daily_demand={},
        recent_average_purchase={},
        first_sale_date={},
        days_with_sales={},
        margin_pct={},
        risk_window_days={},
        item_purchase_info={},
        supplier_of={},
        category_of={},
    )
    lookback_days = cell_params.guardrails.variation_lookback_days
    for row in item_supplier.iter_rows(named=True):
        item_id = row["item_id"]
        decisions.supplier_of[item_id] = row["supplier_id"]
        decisions.category_of[item_id] = row["category"]
        pack_multiple = _pack_multiple_for(row["category"], cell_params)
        decisions.item_purchase_info[item_id] = ItemPurchaseInfo(
            pack_multiple=pack_multiple, cost=float(row["cost"]), unit_of_sale=row["unit_of_sale"]
        )
        price_ref = float(row["price_ref"])
        cost = float(row["cost"])
        decisions.margin_pct[item_id] = (price_ref - cost) / price_ref if price_ref > 0 else 0.0

        demand = sales_subset.filter(pl.col("item_id") == item_id).select("date", "units_sold")
        first_sale, days_with_sales = _first_sale_and_days_with_sales(demand, as_of)
        decisions.first_sale_date[item_id] = first_sale
        decisions.days_with_sales[item_id] = days_with_sales

        lead_time_days = int(row["lead_time_days"])
        review_period_days = int(row["review_period_days"])
        decisions.risk_window_days[item_id] = float(lead_time_days + review_period_days)

        raw_quantity, on_hand, in_transit, daily_demand, recent_avg = _decide_item(
            lead_time_days=lead_time_days,
            review_period_days=review_period_days,
            demand=demand,
            cell_params=cell_params,
            as_of=as_of,
            variation_lookback_days=lookback_days,
        )
        decisions.desired[item_id] = raw_quantity
        decisions.on_hand[item_id] = on_hand
        decisions.in_transit[item_id] = in_transit
        decisions.expected_daily_demand[item_id] = daily_demand
        decisions.recent_average_purchase[item_id] = recent_avg
    return decisions


def _classify_new_items(
    decisions: _ItemDecisions, cell_params: Params, as_of: date
) -> dict[str, bool]:
    """Regra 4 (item novo), parte 1: só a classificação, sem decidir a
    quantidade ainda -- a quantidade depende da mediana da categoria, que
    só existe depois que a regra 1 (teto de cobertura) já rodou sobre os
    itens não-novos (ver `_apply_item_level_guardrails`)."""
    g = cell_params.guardrails
    return {
        item_id: is_new_item(
            first_sale_date=decisions.first_sale_date[item_id],
            days_with_sales=decisions.days_with_sales[item_id],
            as_of=as_of,
            min_history_days=g.new_item_min_history_days,
            min_days_with_sales=g.new_item_min_days_with_sales,
        )
        for item_id in decisions.desired
    }


def _apply_item_level_guardrails(
    decisions: _ItemDecisions, *, is_new: dict[str, bool], cell_params: Params
) -> tuple[dict[str, float], dict[str, list[GuardrailFlag]]]:
    """Regras 1, 2 e 4 (teto de cobertura, limite de variação, item novo) --
    a 3 (restrição de caixa) roda depois, no portfólio inteiro
    (`_finalize_with_cash_constraint`), fora desta função.

    Ordem interna, fixa: regras 1+2 sobre os não-novos primeiro (porque a
    mediana da regra 4 usa a quantidade JÁ cortada pela regra 1 dos
    não-novos); regra 4 sobre os novos depois.
    """
    g = cell_params.guardrails
    quantities: dict[str, float] = {}
    flags: dict[str, list[GuardrailFlag]] = {item_id: [] for item_id in decisions.desired}

    for item_id, raw_qty in decisions.desired.items():
        if is_new[item_id]:
            continue
        category = decisions.category_of[item_id]
        capped_qty, cap_flag = apply_coverage_cap(
            item_id,
            raw_qty,
            position=decisions.position(item_id),
            expected_daily_demand=decisions.expected_daily_demand[item_id],
            shelf_life_days=g.shelf_life_days_by_category[category],
            risk_window_days=decisions.risk_window_days[item_id],
        )
        if cap_flag is not None:
            flags[item_id].append(cap_flag)

        variation_flag = check_order_variation(
            item_id,
            capped_qty,
            recent_average_purchase=decisions.recent_average_purchase[item_id],
            limit_multiple=g.variation_limit_multiple,
        )
        if variation_flag is not None:
            flags[item_id].append(variation_flag)

        quantities[item_id] = capped_qty

    by_category: dict[str, list[float]] = {}
    for item_id, qty in quantities.items():
        by_category.setdefault(decisions.category_of[item_id], []).append(qty)
    medians_by_category = {cat: statistics.median(qs) for cat, qs in by_category.items()}
    global_median = statistics.median(quantities.values()) if quantities else 0.0

    for item_id, item_is_new in is_new.items():
        if not item_is_new:
            continue
        category = decisions.category_of[item_id]
        used_global_fallback = category not in medians_by_category
        median_qty = medians_by_category.get(category, global_median)
        flag = new_item_quantity(
            item_id,
            model_suggested_quantity=decisions.desired[item_id],
            category_median_quantity=median_qty,
            used_global_fallback=used_global_fallback,
        )
        flags[item_id].append(flag)
        quantities[item_id] = median_qty

    return quantities, flags


def _build_supplier_list(
    supplier_id: str,
    supplier_item_ids: list[str],
    *,
    sup_row: dict[str, Any],
    decisions: _ItemDecisions,
    final_desired: dict[str, float],
    guardrail_flags: dict[str, list[GuardrailFlag]],
    cell_params: Params,
    as_of: date,
) -> SupplierPurchaseList | None:
    """`None` quando o fornecedor está fora do calendário de pedido hoje --
    ausência, não exceção (ver docstring de `OrderOutcome`).

    `min_order_value` vem de `_min_order_value_for` (Etapa 3.15), não do
    canônico (`sup_row["min_order_value"]`, sempre 0,0) -- assume que todo
    item de um fornecedor compartilha a mesma `category` (verdade neste
    dataset: `supplier_id` é literalmente `SUP-<CATEGORY>`), checado abaixo
    em vez de silenciosamente confiado.

    A restrição de caixa (regra 3) NÃO é aplicada aqui -- roda depois,
    sobre o portfólio inteiro (`_finalize_with_cash_constraint`).
    """
    categories = {decisions.category_of[item_id] for item_id in supplier_item_ids}
    if len(categories) != 1:
        msg = (
            f"fornecedor {supplier_id!r} tem itens de categorias diferentes "
            f"({sorted(categories)}) -- _min_order_value_for assume uma categoria só "
            "por fornecedor, verdade no dataset atual (supplier_id=SUP-<CATEGORY>); "
            "isso quebrou."
        )
        raise ValueError(msg)
    category = next(iter(categories))

    supplier = Supplier(
        supplier_id=supplier_id,
        lead_time_days=sup_row["lead_time_days"],
        order_days=sup_row["order_days"],
        review_period_days=sup_row["review_period_days"],
        min_order_value=_min_order_value_for(category, cell_params),
        min_order_units=sup_row["min_order_units"],
    )
    if as_of.isoweekday() not in supplier.order_days:
        return None

    supplier_desired = {item_id: final_desired[item_id] for item_id in supplier_item_ids}
    supplier_position = {item_id: decisions.position(item_id) for item_id in supplier_item_ids}
    supplier_daily_demand = {
        item_id: decisions.expected_daily_demand[item_id] for item_id in supplier_item_ids
    }
    supplier_purchase_info = {
        item_id: decisions.item_purchase_info[item_id] for item_id in supplier_item_ids
    }

    order_result = apply_supplier_constraints(
        supplier_desired,
        position=supplier_position,
        expected_daily_demand=supplier_daily_demand,
        item_purchase_info=supplier_purchase_info,
        supplier=supplier,
        as_of=as_of,
        max_additional_packs_for_minimum=(
            cell_params.supplier_order_policy.max_additional_packs_for_minimum
        ),
    )

    adjustments_by_item: dict[str, list[AdjustmentReason]] = {}
    for adj in order_result.adjustments:
        adjustments_by_item.setdefault(adj.item_id, []).append(adj.reason)

    main_rows: list[PurchaseListRow] = []
    exception_rows: list[PurchaseListRow] = []
    for item_id in sorted(supplier_item_ids):
        final_qty = order_result.order[item_id]
        supplier_reasons = adjustments_by_item.get(item_id, [])
        item_guardrail_flags = guardrail_flags.get(item_id, [])
        is_exception = bool(item_guardrail_flags) or any(
            r in _EXCEPTION_SUPPLIER_REASONS for r in supplier_reasons
        )
        pack_multiple = supplier_purchase_info[item_id].pack_multiple
        adjustments = tuple(_ADJUSTMENT_LABELS[r] for r in supplier_reasons) + tuple(
            f.detail for f in item_guardrail_flags
        )
        row = PurchaseListRow(
            item_id=item_id,
            category=decisions.category_of[item_id],
            unit_of_sale=str(supplier_purchase_info[item_id].unit_of_sale),
            quantity_units=final_qty,
            quantity_packs=final_qty / pack_multiple if pack_multiple > 0 else final_qty,
            on_hand=decisions.on_hand[item_id],
            in_transit=decisions.in_transit[item_id],
            coverage_days_after_order=_coverage_days(
                supplier_position[item_id] + final_qty, supplier_daily_demand[item_id]
            ),
            value_rs=final_qty * supplier_purchase_info[item_id].cost,
            margin_pct=decisions.margin_pct[item_id],
            adjustments=adjustments,
            is_exception=is_exception,
        )
        (exception_rows if is_exception else main_rows).append(row)

    return SupplierPurchaseList(
        supplier_id=supplier_id,
        category=category,
        outcome=order_result.outcome,
        min_order_value=supplier.min_order_value,
        main=tuple(main_rows),
        exceptions=tuple(exception_rows),
    )


def _finalize_with_cash_constraint(
    supplier_lists: dict[str, SupplierPurchaseList],
    *,
    budget_rs: float,
    category_floor_fraction: float,
) -> tuple[dict[str, SupplierPurchaseList], tuple[GuardrailFlag, ...], CategoryFloorAlert | None]:
    """Regra 3 (restrição de caixa, com piso de categoria -- Etapa 3.16.4),
    a última do pipeline -- sobre TODOS os fornecedores juntos.

    Um `GuardrailFlag` de `apply_cash_constraint` vem em duas formas,
    distinguidas por `adjusted_quantity`: `== 0.0` é item CORTADO
    ("reduzido por restrição de caixa" -- zera quantidade/valor, migra pra
    exceções); `== original_quantity` é item PROTEGIDO pelo piso
    ("protegido pelo piso de categoria" -- quantidade INTACTA, mas ainda
    migra pra exceções, porque é informação que o comprador precisa ver).
    Item sem flag e sem outra razão de exceção fica em "principal", como
    antes (ver `CASH_CONSTRAINT_LIMITATION_NOTE` para o que isto NÃO
    revalida).
    """
    row_owner: dict[str, tuple[str, PurchaseListRow]] = {}
    for supplier_id, supplier_list in supplier_lists.items():
        for row in (*supplier_list.main, *supplier_list.exceptions):
            row_owner[row.item_id] = (supplier_id, row)

    candidates = [
        CashConstraintCandidate(
            item_id=item_id,
            category=row.category,
            quantity=row.quantity_units,
            value_rs=row.value_rs,
            margin_pct=row.margin_pct,
        )
        for item_id, (_, row) in row_owner.items()
        if row.quantity_units > 0.0
    ]
    _kept, cash_flags, alert = apply_cash_constraint(
        candidates, budget_rs=budget_rs, category_floor_fraction=category_floor_fraction
    )
    flag_by_item = {flag.item_id: flag for flag in cash_flags}

    new_main: dict[str, list[PurchaseListRow]] = {sid: [] for sid in supplier_lists}
    new_exceptions: dict[str, list[PurchaseListRow]] = {sid: [] for sid in supplier_lists}
    for item_id, (supplier_id, original_row) in row_owner.items():
        flag = flag_by_item.get(item_id)
        if flag is not None:
            is_cut = flag.adjusted_quantity == 0.0
            adjusted_row = replace(
                original_row,
                quantity_units=flag.adjusted_quantity,
                # protegido -- fardos não mudam, quantidade não mudou
                quantity_packs=(0.0 if is_cut else original_row.quantity_packs),
                value_rs=0.0 if is_cut else original_row.value_rs,
                adjustments=(*original_row.adjustments, flag.detail),
                is_exception=True,
            )
            new_exceptions[supplier_id].append(adjusted_row)
        elif original_row.is_exception:
            new_exceptions[supplier_id].append(original_row)
        else:
            new_main[supplier_id].append(original_row)

    finalized = {
        supplier_id: replace(
            supplier_list,
            main=tuple(sorted(new_main[supplier_id], key=lambda r: r.item_id)),
            exceptions=tuple(sorted(new_exceptions[supplier_id], key=lambda r: r.item_id)),
        )
        for supplier_id, supplier_list in supplier_lists.items()
    }
    return finalized, cash_flags, alert


def generate_purchase_list(
    as_of: date, *, base_params: Params, tables: CanonicalTables
) -> tuple[dict[str, SupplierPurchaseList], GuardrailFiringReport]:
    """Gera a lista de compra de todos os fornecedores do subconjunto para
    `as_of`, com as quatro regras de guarda ativas (Etapa 3.16). Fornecedor
    fora do calendário de pedido hoje (`OrderOutcome.FORA_DO_CALENDARIO`)
    não entra no dict -- ausência, não exceção."""
    cell_params = build_arm2_single_alpha_params(base_params, ARM2_CHOSEN_ALPHA)
    suppliers = cell_suppliers(tables.suppliers)

    subset = load_or_select_subset(
        tables.sales,
        tables.items,
        suppliers,
        tables.stock,
        cell_params,
        cache_path=tables.subset_cache_path,
    )
    item_ids = list(subset.item_ids)

    items_df = tables.items.filter(pl.col("item_id").is_in(item_ids))
    item_supplier = items_df.select(
        "item_id", "category", "unit_of_sale", "cost", "price_ref", "supplier_id"
    ).join(
        suppliers.select("supplier_id", "lead_time_days", "review_period_days"),
        on="supplier_id",
        how="left",
    )
    sales_subset = (
        tables.sales.filter(
            (pl.col("store_id") == subset.store_id) & (pl.col("item_id").is_in(item_ids))
        )
        .select("item_id", "date", "units_sold")
        .sort("item_id", "date")
        .collect()
    )

    decisions = _decide_all_items(
        item_supplier, sales_subset=sales_subset, cell_params=cell_params, as_of=as_of
    )
    is_new = _classify_new_items(decisions, cell_params, as_of)
    final_desired, guardrail_flags = _apply_item_level_guardrails(
        decisions, is_new=is_new, cell_params=cell_params
    )

    supplier_by_id = {row["supplier_id"]: row for row in suppliers.iter_rows(named=True)}
    items_by_supplier: dict[str, list[str]] = {}
    for item_id, supplier_id in decisions.supplier_of.items():
        items_by_supplier.setdefault(supplier_id, []).append(item_id)

    preliminary: dict[str, SupplierPurchaseList] = {}
    for supplier_id, supplier_item_ids in items_by_supplier.items():
        supplier_list = _build_supplier_list(
            supplier_id,
            supplier_item_ids,
            sup_row=supplier_by_id[supplier_id],
            decisions=decisions,
            final_desired=final_desired,
            guardrail_flags=guardrail_flags,
            cell_params=cell_params,
            as_of=as_of,
        )
        if supplier_list is not None:
            preliminary[supplier_id] = supplier_list

    cycle_budget_rs = _cycle_budget_rs(
        cell_params.guardrails.weekly_budget_rs, CELL_REVIEW_PERIOD_DAYS
    )
    results, cash_flags, category_floor_alert = _finalize_with_cash_constraint(
        preliminary,
        budget_rs=cycle_budget_rs,
        category_floor_fraction=cell_params.guardrails.cash_constraint_category_floor_fraction,
    )

    counts: Counter[GuardrailReason] = Counter()
    for flags in guardrail_flags.values():
        counts.update(f.reason for f in flags)
    counts.update(f.reason for f in cash_flags)
    for reason in GuardrailReason:
        counts.setdefault(reason, 0)

    report = GuardrailFiringReport(
        counts=dict(counts),
        not_implemented=NOT_IMPLEMENTED_GUARDRAILS,
        category_floor_alert=category_floor_alert,
    )
    return results, report


# --------------------------------------------------------------------------
# xlsx -- um arquivo por fornecedor
# --------------------------------------------------------------------------

_MAIN_HEADERS: Final[tuple[str, ...]] = (
    "código",
    "categoria",
    "unidade de venda",
    "sugestão (unidades)",
    "sugestão (fardos)",
    "estoque atual",
    "em trânsito",
    "cobertura após pedido (dias)",
    "valor (R$)",
)
"""Sem coluna de ajustes -- Etapa 3.15: com pack_multiple real (não mais
1,0), a coluna "sugestão (fardos)" já comunica o efeito do arredondamento
(12 unidades -> 2 fardos) sozinha; repetir "arredondado para cima (fardo)"
em toda linha da lista principal era ruído (dispara em quase todo item)."""

_EXCEPTION_HEADERS: Final[tuple[str, ...]] = (*_MAIN_HEADERS, "motivo")
""""Exceções" mantém a coluna de motivo -- aqui o texto É o sinal (pedido
adiado / preenchido até o mínimo / regra de guarda), não ruído de rotina."""

_COLUMN_WIDTHS: Final[tuple[int, ...]] = (12, 20, 14, 16, 14, 12, 12, 22, 12, 60)


def _write_rows_sheet(
    workbook: xlsxwriter.Workbook,
    sheet_name: str,
    rows: tuple[PurchaseListRow, ...],
    *,
    headers: tuple[str, ...],
    header_format: object,
    money_format: object,
    number_format: object,
    empty_note: str,
) -> None:
    sheet = workbook.add_worksheet(sheet_name)
    sheet.freeze_panes(1, 0)
    for col, header in enumerate(headers):
        sheet.write(0, col, header, header_format)
    for col, width in enumerate(_COLUMN_WIDTHS[: len(headers)]):
        sheet.set_column(col, col, width)

    if not rows:
        sheet.write(1, 0, empty_note)
        return

    for r, row in enumerate(rows, start=1):
        sheet.write(r, 0, row.item_id)
        sheet.write(r, 1, row.category)
        sheet.write(r, 2, row.unit_of_sale)
        sheet.write_number(r, 3, row.quantity_units, number_format)
        sheet.write_number(r, 4, row.quantity_packs, number_format)
        sheet.write_number(r, 5, row.on_hand, number_format)
        sheet.write_number(r, 6, row.in_transit, number_format)
        if row.coverage_days_after_order is None:
            sheet.write(r, 7, "sem demanda recente")
        else:
            sheet.write_number(r, 7, row.coverage_days_after_order, number_format)
        sheet.write_number(r, 8, row.value_rs, money_format)
        if len(headers) > 9:  # aba Exceções -- motivo
            sheet.write(r, 9, "; ".join(row.adjustments))
    sheet.autofilter(0, 0, len(rows), len(headers) - 1)


def write_supplier_workbook(
    supplier_list: SupplierPurchaseList, *, as_of: date, out_dir: Path
) -> Path:
    """Grava um xlsx com três abas: Lista principal, Exceções, Notas.

    "Lista principal" é a de aprovação em bloco -- arredondamento de fardo
    não aparece linha a linha (Etapa 3.15: a coluna "fardos" já comunica o
    efeito). "Exceções" recebe item com pedido adiado, preenchido até o
    mínimo, ou qualquer uma das quatro regras de guarda (Etapa 3.16).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{supplier_list.supplier_id}.xlsx"
    workbook = xlsxwriter.Workbook(str(path))

    header_format = workbook.add_format(
        {"bold": True, "bg_color": "#1f3864", "font_color": "white", "border": 1}
    )
    money_format = workbook.add_format({"num_format": "R$ #,##0.00"})
    number_format = workbook.add_format({"num_format": "#,##0.00"})
    note_format = workbook.add_format({"text_wrap": True, "valign": "top"})

    _write_rows_sheet(
        workbook,
        "Lista principal",
        supplier_list.main,
        headers=_MAIN_HEADERS,
        header_format=header_format,
        money_format=money_format,
        number_format=number_format,
        empty_note="Nenhum item nesta lista para esta data de decisão.",
    )
    if supplier_list.min_order_value > 0.0:
        exceptions_empty_note = (
            f"Nenhuma exceção hoje -- o pedido bateu o mínimo de "
            f"R$ {supplier_list.min_order_value:,.2f} sem precisar de preenchimento, "
            "não ficou inatingível, e nenhuma regra de guarda disparou."
        )
    else:
        exceptions_empty_note = (
            f"Categoria {supplier_list.category!r} tem min_order_value=R$ 0,00 (>=50 "
            "itens no canônico completo, ver aba Notas) -- e nenhuma regra de guarda "
            "disparou para este fornecedor hoje."
        )
    _write_rows_sheet(
        workbook,
        "Exceções",
        supplier_list.exceptions,
        headers=_EXCEPTION_HEADERS,
        header_format=header_format,
        money_format=money_format,
        number_format=number_format,
        empty_note=exceptions_empty_note,
    )

    notes_sheet = workbook.add_worksheet("Notas")
    notes_sheet.set_column(0, 0, 110)
    min_order_note = (
        f"min_order_value desta categoria ({supplier_list.category}): "
        f"R$ {supplier_list.min_order_value:,.2f}."
    )
    notes = [
        f"Fornecedor: {supplier_list.supplier_id} -- data de decisão: {as_of.isoformat()} "
        f"-- resultado do pedido: {_OUTCOME_LABELS[supplier_list.outcome]}.",
        f"Política: braço 2 (estatístico + nível-alvo), alpha={ARM2_CHOSEN_ALPHA} "
        "(iso-serviço, Etapa 3.12).",
        ALPHA_CELL_MISMATCH_NOTE,
        REALISTIC_SUPPLIER_ASSUMPTIONS_NOTE,
        min_order_note,
        GUARDRAILS_NOTE,
        CASH_CONSTRAINT_LIMITATION_NOTE,
        CASH_CONSTRAINT_CATEGORY_FLOOR_NOTE,
        RISK_WINDOW_ARCHITECTURE_LIMITATION_NOTE,
        ISO_SERVICE_SCOPE_NOTE,
        DESCRIPTION_MISSING_NOTE,
        '"Sugestão (fardos)" = "sugestão (unidades)" / pack_multiple (fardo real por '
        "família de categoria, Etapa 3.15 -- ver nota acima).",
    ]
    for r, text in enumerate(notes):
        notes_sheet.write(r, 0, text, note_format)
        notes_sheet.set_row(r, 34)

    workbook.close()
    return path


def write_all_workbooks(
    results: dict[str, SupplierPurchaseList], *, as_of: date, out_dir: Path
) -> list[Path]:
    return [
        write_supplier_workbook(supplier_list, as_of=as_of, out_dir=out_dir)
        for supplier_list in results.values()
    ]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Gera a lista de compra (um xlsx por fornecedor) para uma data de decisão."
    )
    parser.add_argument("--params", type=Path, default=Path("config/params.yaml"))
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--weekly-budget-rs",
        type=float,
        default=None,
        help=(
            "sobrescreve guardrails.weekly_budget_rs -- para cenário de estresse "
            "(Etapa 3.16.4), declarado, não um valor de produção"
        ),
    )
    args = parser.parse_args(argv)

    base_params = load_params(args.params)
    if args.weekly_budget_rs is not None:
        base_params = base_params.model_copy(
            update={
                "guardrails": base_params.guardrails.model_copy(
                    update={"weekly_budget_rs": args.weekly_budget_rs}
                )
            }
        )
        print(
            "CENÁRIO DE ESTRESSE: weekly_budget_rs sobrescrito para "
            f"R$ {args.weekly_budget_rs:,.2f}"
        )
    tables = load_canonical_tables(base_params)
    results, report = generate_purchase_list(args.as_of, base_params=base_params, tables=tables)
    paths = write_all_workbooks(results, as_of=args.as_of, out_dir=args.output_dir)

    n_exceptions = sum(len(r.exceptions) for r in results.values())
    print(
        f"{len(paths)} fornecedor(es) com pedido em {args.as_of.isoformat()}, "
        f"{n_exceptions} item(ns) em exceção. Arquivos em {args.output_dir}/"
    )
    print("Disparos por regra de guarda:")
    for reason, count in sorted(report.counts.items(), key=lambda kv: kv[0].value):
        print(f"  {reason.value}: {count}")
    if report.category_floor_alert is not None:
        alert = report.category_floor_alert
        print(
            f"ALERTA: soma dos pisos de categoria (R$ {alert.total_floor_rs:,.2f}) excede o "
            f"orçamento do ciclo (R$ {alert.budget_rs:,.2f}) em R$ {alert.shortfall_rs:,.2f} -- "
            "o orçamento não cobre nem o mínimo operacional da loja (informação de negócio, "
            "não detalhe de algoritmo)."
        )
    print("Regras não implementadas:")
    for text in report.not_implemented:
        print(f"  - {text}")


if __name__ == "__main__":
    main()

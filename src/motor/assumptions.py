"""Registro auditável de premissas arbitradas (Sprint 16.5, Etapa 3.1).

Achado da Sprint 16: o simulador roda de forma matematicamente consistente
mesmo quando os NÚMEROS que alimentam essa matemática nunca foram medidos --
`lead_time_days=3` nos 16 fornecedores do subconjunto, por exemplo, é 100%
`supplier_assumptions.default_lead_time_days` (arbitrado), não algo lido do
cadastro real de nenhum fornecedor (o Favorita não tem esse dado -- ver
Etapa 3.2). Isso não é problema NOVO desta sprint: cada valor em
`params.yaml` já carrega um comentário `# medido:` ou `# arbitrado:` desde a
Sprint 0 (CLAUDE.md, seção 2). O que faltava era isso ser MÁQUINA-LEGÍVEL e
OBRIGATÓRIO no resultado, não só um comentário que alguém precisa ler no
arquivo de config para descobrir.

Este módulo formaliza esse registro: lê as mesmas premissas de `Params`,
etiqueta cada uma com sua origem, e devolve uma estrutura que
`motor.experiments.run` embute em TODO manifesto (`RunManifest.assumptions`,
campo obrigatório -- gravar um resultado sem isso levanta erro do próprio
pydantic, explícito, não um manifesto incompleto em silêncio).

TRÊS origens, não duas -- a distinção importa:
    MEDIDO           -- tem fonte externa citável (documento de negócio,
                        medição sobre o dado real). Nem toda "medição" é
                        sobre o dataset -- ver GROCERY I/II abaixo, medido
                        de um documento de negócio, não do Favorita.
    ARBITRADO        -- chute plausível, sem fonte -- precisa ser revisto
                        com o cliente antes do relatório final (CLAUDE.md,
                        topo de params.yaml).
    DEFAULT_DATASET  -- vem de um atributo REAL do dataset bruto (ex.:
                        `Item.is_perishable`, direto da coluna `perishable`
                        do Favorita) -- não é chute, mas também não é uma
                        medição de NEGÓCIO. Nenhuma das premissas cobertas
                        por este registro hoje se qualifica aqui -- nenhuma
                        das 8 exigidas tem contraparte no dado bruto (Etapa
                        3.2 verificou isso: `items.csv`/`train.csv`/
                        `transactions.csv` não têm fornecedor, prazo de
                        entrega, custo nem preço). A categoria existe para
                        quando (se) isso mudar, não para preencher hoje.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from motor.config import Params


class AssumptionOrigin(StrEnum):
    """Origem de uma premissa numérica -- ver docstring do módulo para a
    distinção completa entre as três."""

    MEDIDO = "medido"
    ARBITRADO = "arbitrado"
    DEFAULT_DATASET = "default_dataset"


class Assumption(BaseModel):
    """Uma premissa numérica, com proveniência explícita. `valor` aceita
    qualquer tipo serializável em JSON (float, dict, list) -- premissas como
    `category_margin_pct` são, elas mesmas, um dicionário de valores, não um
    escalar."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    valor: Any
    origem: AssumptionOrigin
    justificativa: str
    fonte: str | None = None
    """Arquivo/coluna/documento de origem -- só quando `origem == MEDIDO`.
    `None` para `ARBITRADO` é o esperado, não uma lacuna a preencher: um
    chute não tem fonte por definição."""


class AssumptionsRegistry(BaseModel):
    """Todo o conjunto de premissas cobertas por esta etapa. Ver docstring
    do módulo -- `extra="forbid"` é deliberado: uma premissa nova precisa
    ser adicionada aqui explicitamente, nunca vazar por acaso."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lead_time_days: Assumption
    review_period_days: Assumption
    min_order_value: Assumption
    min_order_units: Assumption
    pack_multiple: Assumption
    category_margin_pct: dict[str, Assumption]
    """Uma `Assumption` POR CATEGORIA, não uma origem única -- GROCERY I/II
    são `MEDIDO` (documento de negócio), o resto é `ARBITRADO` (analogia).
    Colapsar isso numa origem só apagaria uma heterogeneidade real (o
    inverso do erro que a Etapa 3.2 pede pra evitar do lado do lead_time:
    lá o risco é INVENTAR heterogeneidade que não existe; aqui seria
    ESCONDER heterogeneidade que existe)."""
    capital_cost_annual: Assumption
    estoque_inicial: Assumption
    default_alpha: Assumption
    category_alpha: Assumption


_LEAD_TIME_JUSTIFICATIVA = (
    "Prazo comum de fornecedor de mercearia local -- chute plausível, não medido. "
    "Verificado na Etapa 3.2 (Sprint 16.5): os 16 fornecedores do subconjunto de "
    "trabalho têm lead_time_days=3 uniforme -- 100% vindo deste default, 0% do "
    "cadastro real (o Favorita não tem cadastro de fornecedor)."
)

_REVIEW_PERIOD_JUSTIFICATIVA = (
    "Revisão semanal como piso -- sem calendário de fornecedor real (Favorita não "
    "tem), todo fornecedor do subconjunto herda este default (Sprint 3, D8)."
)

_ESTOQUE_INICIAL_JUSTIFICATIVA = (
    "Fórmula (motor.experiments.shared.initial_stock_units), não um número solto: "
    "avg_daily_demand(warmup) x (lead_time_days + review_period_days) -- a demanda "
    "média é MEDIDA (observada nos primeiros warmup_days dias reais de cada item), "
    "mas a REGRA de cobertura (cobrir exatamente um ciclo de risco) é uma escolha "
    "de desenho, não uma medição -- por isso ARBITRADO, com a ressalva de que o "
    "insumo de demanda em si vem de dado real."
)


def build_assumptions_registry(params: Params) -> AssumptionsRegistry:
    """Lê `Params` e devolve o registro completo. Nenhum valor é recalculado
    aqui -- só relido de onde já mora (`params.yaml`) e etiquetado."""
    sa = params.supplier_assumptions
    eco = params.economics

    category_margin_pct = {
        categoria: Assumption(
            valor=valor,
            origem=(
                AssumptionOrigin.MEDIDO
                if categoria in ("GROCERY I", "GROCERY II")
                else AssumptionOrigin.ARBITRADO
            ),
            justificativa=(
                "Mercearia seca, faixa 15-22% do documento de negócio, ponto médio."
                if categoria in ("GROCERY I", "GROCERY II")
                else "Arbitrado por analogia com varejo brasileiro, sem medição -- "
                "ver params.yaml/economics.category_margin_pct para o raciocínio "
                "categoria a categoria (Sprint 8)."
            ),
            fonte=(
                "documento de negócio (faixa de margem de mercearia seca)"
                if categoria in ("GROCERY I", "GROCERY II")
                else None
            ),
        )
        for categoria, valor in eco.category_margin_pct.items()
    }

    return AssumptionsRegistry(
        lead_time_days=Assumption(
            valor=sa.default_lead_time_days,
            origem=AssumptionOrigin.ARBITRADO,
            justificativa=_LEAD_TIME_JUSTIFICATIVA,
        ),
        review_period_days=Assumption(
            valor=sa.default_review_period_days,
            origem=AssumptionOrigin.ARBITRADO,
            justificativa=_REVIEW_PERIOD_JUSTIFICATIVA,
        ),
        min_order_value=Assumption(
            valor=sa.default_min_order_value,
            origem=AssumptionOrigin.ARBITRADO,
            justificativa="Sem pedido mínimo conhecido -- default não restringe (0.0).",
        ),
        min_order_units=Assumption(
            valor=sa.default_min_order_units,
            origem=AssumptionOrigin.ARBITRADO,
            justificativa=(
                "Sem mínimo em unidades conhecido -- default não restringe (0.0), Sprint 10."
            ),
        ),
        pack_multiple=Assumption(
            valor=sa.default_pack_multiple,
            origem=AssumptionOrigin.ARBITRADO,
            justificativa="Sem fardo conhecido -- assume unidade avulsa (1.0).",
        ),
        category_margin_pct=category_margin_pct,
        capital_cost_annual=Assumption(
            valor=eco.capital_cost_annual,
            origem=AssumptionOrigin.ARBITRADO,
            justificativa=(
                "Custo de capital anualizado plausível para varejo pequeno/médio no Brasil."
            ),
        ),
        estoque_inicial=Assumption(
            valor="avg_daily_demand(warmup) x (lead_time_days + review_period_days)",
            origem=AssumptionOrigin.ARBITRADO,
            justificativa=_ESTOQUE_INICIAL_JUSTIFICATIVA,
        ),
        default_alpha=Assumption(
            valor=eco.default_alpha,
            origem=AssumptionOrigin.ARBITRADO,
            justificativa=(
                "Nível de serviço-alvo default, uniforme para todo item (Sprint 12) -- "
                "decisão explícita para isolar o efeito da previsão entre braços 2 e 3, "
                "não uma medição de quanto cada categoria de fato tolera ruptura."
            ),
        ),
        category_alpha=Assumption(
            valor=dict(eco.category_alpha),
            origem=AssumptionOrigin.ARBITRADO,
            justificativa=(
                "INERTE: chaves genéricas antigas (hortifruti/mercearia/bebidas/limpeza) que "
                "NÃO correspondem a Item.category real do subconjunto -- nenhuma política lê "
                "este dict hoje (default_alpha sempre vence). Arbitrado por analogia, nunca "
                "remapeado para as categorias reais (Sprint 12; ver EconomicsParams)."
            ),
        ),
    )

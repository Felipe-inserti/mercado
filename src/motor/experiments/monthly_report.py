"""Sprint 19 (Fase 4, Etapa 4.2) -- o relatório mensal em R$.

Ancorado no achado da Sprint 18: o valor do produto tem DOIS ANDARES, e
este relatório os mantém separados o tempo todo, nunca somados numa única
linha "ganho total" (isso escondia a Sprint 18 sozinha):

    ANDAR 1 -- correção de cadastro: recalibrar `ErpBaselinePolicy.factor`
    na célula real (lt=7/rp=14) em vez de manter o factor de quando o
    fornecedor entregava mais rápido. NÃO precisa de modelo -- é o baseline
    de sempre, só com o número certo. Sozinho leva o nível de serviço de
    ~60-66% para ~94,85% (Sprint 18).

    ANDAR 2 -- refinamento do modelo: braço 2 (estatístico + nível-alvo),
    alpha iso-serviço, rodando SOBRE um baseline já recalibrado, no MESMO
    nível de serviço. Ganho menor, real, medido: -2,8% de capital, +2,9%
    de decision_metric (Sprint 17).

NENHUM CAMINHO NOVO DE EXECUÇÃO -- este módulo não roda simulação nenhuma.
Todos os números vêm de resultados já em disco (Sprints 17/18):

    - motor (braço 2, alpha=0,66 iso-serviço):
      `results/iso_servico/item_decomposition_alpha066.parquet` (por item)
      e `results/iso_servico/arm2_alpha_grid.parquet` (nivel_servico/
      decision_metric/capital_medio_rs agregados, via
      `motor.experiments.stale_baseline.load_motor_iso_servico`).
    - baseline recalibrado (lt=7/rp=14):
      `results/sensibilidade_dirigida/lt7_rp14/erp_baseline/` (manifest +
      item_metrics), via `motor.experiments.stale_baseline.load_baseline_recalibrado`.
    - baseline desatualizado (duas magnitudes, Sprint 18):
      `results/baseline_desatualizado/<label>/erp_baseline/`, via
      `motor.experiments.stale_baseline.load_stale_scenario`.

ESCOPO -- O QUE ESTE RELATÓRIO NÃO INCLUI
--------------------------------------------
As 4 regras de guarda (Sprint 13, `motor.policy.guardrails`) e a restrição
de caixa por orçamento semanal NÃO entram nestes números -- elas mudam a
política aplicada na LISTA DE COMPRA semanal (`results/lista_compra/`),
não a simulação de portfólio usada aqui (`motor.experiments.iso_service`/
`sensitivity` nunca chamam `guardrails.py`). Quantificar o custo do seguro
das guardas sobre as métricas financeiras deste relatório é um experimento
declarado à parte, ainda não feito -- mesma disciplina da Sprint 13
("guardrails mudam a política e mudariam o decision_metric; isso é
experimento separado").

"MENSAL" -- SOBRE O QUÊ, EXATAMENTE
--------------------------------------
Não existe um mês real de produção -- isto é um backtest sobre dado
histórico (`simulation_window`, ~277 dias avaliados após aquecimento). Os
valores "mensalizados" deste relatório são o total do período dividido por
`n_evaluation_days / 30` (uma média de 30 dias, não um mês-calendário
específico) -- declarado explicitamente em toda tabela e na aba Premissas,
nunca apresentado como se fosse um mês real medido.

A SENSIBILIDADE DE MARGEM (±30%) -- POR QUE É EXATA, NÃO APROXIMADA
------------------------------------------------------------------------
`motor.metrics.financial` prova, na própria docstring do módulo, que com
`uniform_unit_price` (premissa ativa desde a Sprint 8) `margem_realizada_rs`
e `ruptura_rs` de QUALQUER braço são lineares em `margin_pct` (que não entra
em nenhuma decisão de quantidade destes braços -- só na tradução pra R$
depois). Escalar TODO `category_margin_pct` pelo mesmo fator global (0,7x
ou 1,3x) escala `margem_realizada_rs`/`ruptura_rs`/`ruptura_evitada`
EXATAMENTE pelo mesmo fator -- não precisa rodar o `Simulator` de novo pra
cada ponto de sensibilidade, é aritmética exata sobre o que já foi medido.
`capital_medio_rs` NÃO tem essa propriedade (depende de `cost = price x
(1 - margin_pct)`, direção oposta) -- por isso a sensibilidade de margem
aqui é só sobre ruptura evitada/margem recuperada (o que a Etapa 4.2 pediu),
nunca sobre capital liberado.

CORREÇÃO EM RELAÇÃO AO PEDIDO DA ETAPA (declarada aqui, não escondida): o
enunciado da Sprint 19 fala em "a correção de demanda censurada está
projetada". Não está -- `motor.features.build.build_feature_row` documenta
explicitamente que a correção é "fora de escopo desta sprint (nenhum
modelo, nenhuma alteração)" enquanto não houver saldo de estoque real de
cliente; hoje o motor só declara a premissa (venda observada = demanda),
CLAUDE.md seção 8. A aba Limitações usa a formulação correta.

Formato: xlsx, mesmas convenções visuais de
`motor.reporting.purchase_list` (header azul-escuro, `R$ #,##0.00`,
`text_wrap` nas notas) -- é o formato que o cliente já sabe abrir.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import polars as pl
import xlsxwriter

from motor.config import load_params
from motor.experiments.iso_service import ARM2_CHOSEN_ALPHA
from motor.experiments.stale_baseline import (
    STALE_SOURCES,
    ScenarioMetrics,
    load_baseline_recalibrado,
    load_motor_iso_servico,
    load_stale_scenario,
)

RESULTS_DIR: Final[Path] = Path("results")
ISO_SERVICE_DIR: Final[Path] = RESULTS_DIR / "iso_servico"
SENSITIVITY_DIR: Final[Path] = RESULTS_DIR / "sensibilidade_dirigida"
STALE_BASELINE_DIR: Final[Path] = RESULTS_DIR / "baseline_desatualizado"
PARAMS_PATH: Final[Path] = Path("config/params.yaml")

MARGIN_SENSITIVITY_FACTORS: Final[tuple[float, ...]] = (0.7, 1.0, 1.3)
"""±30% sobre TODO category_margin_pct, arbitrado (pedido da Etapa 4.2) --
não é uma faixa medida, é a magnitude de erro de premissa que o relatório
declara suportar. Ver docstring do módulo para a prova de que escalar por
este fator é aritmética exata sobre margem_realizada_rs/ruptura_rs, não
uma nova simulação."""

DAYS_PER_MONTH: Final[float] = 30.0
"""Conversão "total do período -> equivalente mensal" -- mês de 30 dias,
não um mês-calendário específico (não existe produção real para reportar
sobre um mês de verdade nesta etapa). Ver docstring do módulo."""

TOP_N_ITENS_SANGRANDO: Final[int] = 20

STALE_LABEL_HEADLINE: Final[str] = "calibrado_lt3_rp7"
"""Magnitude usada como número de manchete do Andar 1 -- a mais provável
de bater com "o fornecedor mudou de lead_time e ninguém atualizou o ERP"
há mais tempo (Sprint 18). A outra magnitude (`calibrado_lt5_rp7`) aparece
lado a lado em toda tabela -- nunca escondida, é a checagem de
sensibilidade da PRÓPRIA Sprint 18."""


@dataclass(frozen=True)
class ArmFinancials:
    """Métricas financeiras agregadas de um braço, em R$ -- soma exata dos
    `item_metrics`, não os valores arredondados do manifesto (exceto
    `nivel_servico`/`decision_metric`, que exigem a agregação correta por
    `sum(sold)/sum(demand)`, não a média das linhas -- lidos do manifesto/
    `ScenarioMetrics`, já agregados certo)."""

    label: str
    nivel_servico: float
    decision_metric: float
    capital_medio_rs: float
    margem_realizada_rs: float
    ruptura_rs: float
    perda_rs: float
    n_items: int


def _sum_item_metrics(path: Path) -> tuple[float, float, float, int]:
    df = pl.read_parquet(path)
    return (
        float(df["margem_realizada_rs"].sum()),
        float(df["ruptura_rs"].sum()),
        float(df["perda_rs"].sum()),
        df.height,
    )


def load_motor_financials() -> ArmFinancials:
    scenario = load_motor_iso_servico()
    margem, ruptura, perda, n = _sum_item_metrics(
        ISO_SERVICE_DIR / "item_decomposition_alpha066.parquet"
    )
    return ArmFinancials(
        label=scenario.cenario,
        nivel_servico=scenario.nivel_servico,
        decision_metric=scenario.decision_metric,
        capital_medio_rs=scenario.capital_medio_rs,
        margem_realizada_rs=margem,
        ruptura_rs=ruptura,
        perda_rs=perda,
        n_items=n,
    )


def load_recalibrado_financials() -> ArmFinancials:
    scenario = load_baseline_recalibrado()
    margem, ruptura, perda, n = _sum_item_metrics(
        SENSITIVITY_DIR / "lt7_rp14" / "erp_baseline" / "item_metrics.parquet"
    )
    return ArmFinancials(
        label=scenario.cenario,
        nivel_servico=scenario.nivel_servico,
        decision_metric=scenario.decision_metric,
        capital_medio_rs=scenario.capital_medio_rs,
        margem_realizada_rs=margem,
        ruptura_rs=ruptura,
        perda_rs=perda,
        n_items=n,
    )


def load_stale_financials(label: str) -> ArmFinancials:
    scenario: ScenarioMetrics = load_stale_scenario(label)
    margem, ruptura, perda, n = _sum_item_metrics(
        STALE_BASELINE_DIR / label / "erp_baseline" / "item_metrics.parquet"
    )
    return ArmFinancials(
        label=scenario.cenario,
        nivel_servico=scenario.nivel_servico,
        decision_metric=scenario.decision_metric,
        capital_medio_rs=scenario.capital_medio_rs,
        margem_realizada_rs=margem,
        ruptura_rs=ruptura,
        perda_rs=perda,
        n_items=n,
    )


def _evaluation_window() -> dict[str, object]:
    manifest = json.loads(
        (SENSITIVITY_DIR / "lt7_rp14" / "erp_baseline" / "manifest.json").read_text()
    )
    return dict(manifest["simulation_window"])


def n_months_no_periodo() -> float:
    n_evaluation_days = _evaluation_window()["n_evaluation_days"]
    assert isinstance(n_evaluation_days, int)
    return n_evaluation_days / DAYS_PER_MONTH


def mensalizar(valor_total_periodo: float) -> float:
    return valor_total_periodo / n_months_no_periodo()


def ruptura_evitada(pior: ArmFinancials, melhor: ArmFinancials) -> float:
    """Margem recuperada indo de `pior` (mais ruptura) para `melhor`."""
    return pior.ruptura_rs - melhor.ruptura_rs


def capital_liberado(pior: ArmFinancials, melhor: ArmFinancials) -> float:
    return pior.capital_medio_rs - melhor.capital_medio_rs


def perda_evitada(pior: ArmFinancials, melhor: ArmFinancials) -> float:
    return pior.perda_rs - melhor.perda_rs


def sensibilidade_margem(
    valor_base: float, *, factors: tuple[float, ...] = MARGIN_SENSITIVITY_FACTORS
) -> dict[float, float]:
    """`valor_base` escalado por cada fator -- exato, ver docstring do
    módulo (prova de linearidade em `motor.metrics.financial`)."""
    return {factor: valor_base * factor for factor in factors}


def itens_sangrando_margem(top_n: int = TOP_N_ITENS_SANGRANDO) -> pl.DataFrame:
    """Os `top_n` itens com maior ruptura_rs ABSOLUTA sob o motor (braço 2,
    alpha iso-serviço) -- os que ainda sangram margem mesmo com a
    ferramenta ativa. `pct_margem_potencial_perdida` normaliza por item
    (margem potencial = margem_realizada_rs + ruptura_rs, invariante entre
    braços -- mesma demanda, mesma margin_pct)."""
    base_params = load_params(PARAMS_PATH)
    items = pl.read_parquet(Path(base_params.data.canonical_dir) / "items.parquet").select(
        "item_id", "category", "unit_of_sale"
    )
    motor = pl.read_parquet(ISO_SERVICE_DIR / "item_decomposition_alpha066.parquet")
    joined = motor.join(items, on="item_id", how="left")
    return (
        joined.with_columns(
            (pl.col("ruptura_rs") / (pl.col("ruptura_rs") + pl.col("margem_realizada_rs"))).alias(
                "pct_margem_potencial_perdida"
            )
        )
        .sort("ruptura_rs", descending=True)
        .head(top_n)
        .select(
            "item_id",
            "category",
            "unit_of_sale",
            "price",
            "cost",
            "margin_pct",
            "margem_realizada_rs",
            "ruptura_rs",
            "pct_margem_potencial_perdida",
            "nivel_servico",
        )
    )


# --------------------------------------------------------------------------
# xlsx
# --------------------------------------------------------------------------

_HEADER_FORMAT_SPEC: Final[dict[str, object]] = {
    "bold": True,
    "bg_color": "#1f3864",
    "font_color": "white",
    "border": 1,
}


@dataclass(frozen=True)
class _Formats:
    header: object
    money: object
    number: object
    pct: object
    note: object
    bold: object


@dataclass(frozen=True)
class _ReportData:
    """Tudo que as funções `_write_*_sheet` precisam -- montado uma vez em
    `write_monthly_report_workbook`, nunca recarregado por aba."""

    motor: ArmFinancials
    recalibrado: ArmFinancials
    stale: dict[str, ArmFinancials]
    window: dict[str, object]
    n_months: float
    andar1_ruptura_evitada: dict[str, float]
    andar2_ruptura_evitada: float
    andar1_aumento_capital: dict[str, float]
    """POSITIVO -- ver docstring de `_write_andar1_sheet`: recalibrar EXIGE
    mais capital empregado que o baseline desatualizado, nunca libera. É o
    espelho do resgate de serviço (Sprint 18): sub-abastecer em 60-66% de
    serviço naturalmente amarra menos capital -- corrigir isso amarra mais,
    não menos. 'Capital liberado' só existe no Andar 2."""
    andar2_capital_liberado: float


def _build_report_data() -> _ReportData:
    motor = load_motor_financials()
    recalibrado = load_recalibrado_financials()
    stale = {label: load_stale_financials(label) for label in STALE_SOURCES}
    return _ReportData(
        motor=motor,
        recalibrado=recalibrado,
        stale=stale,
        window=_evaluation_window(),
        n_months=n_months_no_periodo(),
        andar1_ruptura_evitada={
            label: ruptura_evitada(stale[label], recalibrado) for label in STALE_SOURCES
        },
        andar2_ruptura_evitada=ruptura_evitada(recalibrado, motor),
        andar1_aumento_capital={
            label: capital_liberado(recalibrado, stale[label]) for label in STALE_SOURCES
        },
        andar2_capital_liberado=capital_liberado(recalibrado, motor),
    )


def _write_resumo_cabecalho(sheet: object, data: _ReportData, fmt: _Formats) -> int:
    sheet.write(0, 0, "RELATÓRIO MENSAL EM R$ -- MOTOR DE DECISÃO DE COMPRA", fmt.bold)  # type: ignore[attr-defined]
    sheet.write(  # type: ignore[attr-defined]
        1,
        0,
        f"Período simulado avaliado: {data.window['evaluation_start']} a {data.window['end']} "
        f"({data.window['n_evaluation_days']} dias -- equivalente a {data.n_months:.2f} meses "
        f"de 30 dias). Braço 2 (estatístico + nível-alvo), alpha={ARM2_CHOSEN_ALPHA} "
        "(iso-serviço). Célula lead_time=7/review_period=14 -- ver aba Premissas.",
    )
    sheet.set_row(1, 30)  # type: ignore[attr-defined]
    return 3


def _write_resumo_andar1_bloco(sheet: object, r: int, data: _ReportData, fmt: _Formats) -> int:
    stale_headline = data.stale[STALE_LABEL_HEADLINE]
    sheet.write(r, 0, "ANDAR 1 -- CORREÇÃO DE CADASTRO (recalibrar, sem modelo)", fmt.header)  # type: ignore[attr-defined]
    sheet.write(r, 1, "", fmt.header)  # type: ignore[attr-defined]
    r += 1
    sheet.write(  # type: ignore[attr-defined]
        r, 0, f"Ruptura evitada (margem recuperada) -- mensal, magnitude {STALE_LABEL_HEADLINE}"
    )
    sheet.write_number(  # type: ignore[attr-defined]
        r, 1, mensalizar(data.andar1_ruptura_evitada[STALE_LABEL_HEADLINE]), fmt.money
    )
    r += 1
    faixa = sensibilidade_margem(data.andar1_ruptura_evitada[STALE_LABEL_HEADLINE])
    sheet.write(r, 0, "  faixa de sensibilidade de margem (±30%, mensal) -- ver aba Andar 1")  # type: ignore[attr-defined]
    sheet.write(r, 1, f"{mensalizar(faixa[0.7]):,.2f} a {mensalizar(faixa[1.3]):,.2f}")  # type: ignore[attr-defined]
    r += 1
    sheet.write(r, 0, "Nível de serviço: de")  # type: ignore[attr-defined]
    sheet.write_number(r, 1, stale_headline.nivel_servico, fmt.pct)  # type: ignore[attr-defined]
    r += 1
    sheet.write(r, 0, "  para (baseline recalibrado)")  # type: ignore[attr-defined]
    sheet.write_number(r, 1, data.recalibrado.nivel_servico, fmt.pct)  # type: ignore[attr-defined]
    r += 1
    sheet.write(  # type: ignore[attr-defined]
        r,
        0,
        "  custo: aumento de capital empregado -- mensal (recalibrar exige mais estoque, "
        "não libera; ver aba Andar 1)",
    )
    sheet.write_number(  # type: ignore[attr-defined]
        r, 1, mensalizar(data.andar1_aumento_capital[STALE_LABEL_HEADLINE]), fmt.money
    )
    return r + 2


def _write_resumo_andar2_bloco(sheet: object, r: int, data: _ReportData, fmt: _Formats) -> int:
    sheet.write(r, 0, "ANDAR 2 -- REFINAMENTO DO MODELO (sobre baseline já certo)", fmt.header)  # type: ignore[attr-defined]
    sheet.write(r, 1, "", fmt.header)  # type: ignore[attr-defined]
    r += 1
    sheet.write(r, 0, "Capital liberado -- mensal (equivalente, ver nota)")  # type: ignore[attr-defined]
    sheet.write_number(r, 1, mensalizar(data.andar2_capital_liberado), fmt.money)  # type: ignore[attr-defined]
    r += 1
    sheet.write(  # type: ignore[attr-defined]
        r,
        0,
        "Capital liberado -- % vs. baseline recalibrado "
        f"({data.recalibrado.capital_medio_rs:,.2f})",
    )
    sheet.write_number(  # type: ignore[attr-defined]
        r, 1, data.andar2_capital_liberado / data.recalibrado.capital_medio_rs, fmt.pct
    )
    r += 1
    sheet.write(r, 0, "decision_metric: baseline recalibrado")  # type: ignore[attr-defined]
    sheet.write_number(r, 1, data.recalibrado.decision_metric, fmt.number)  # type: ignore[attr-defined]
    r += 1
    sheet.write(r, 0, "  motor")  # type: ignore[attr-defined]
    sheet.write_number(r, 1, data.motor.decision_metric, fmt.number)  # type: ignore[attr-defined]
    r += 1
    sheet.write(  # type: ignore[attr-defined]
        r,
        0,
        "Margem recuperada adicional pelo modelo -- mensal (pequena de propósito: "
        "mesmo nível de serviço do baseline recalibrado, por construção iso-serviço)",
    )
    sheet.write_number(r, 1, mensalizar(data.andar2_ruptura_evitada), fmt.money)  # type: ignore[attr-defined]
    return r + 2


def _write_resumo_rodape(sheet: object, r: int, fmt: _Formats) -> None:
    sheet.write(r, 0, "Perda evitada (validade/expiração) -- os 2 andares", fmt.header)  # type: ignore[attr-defined]
    sheet.write(r, 1, "R$ 0,00 -- ver aba Limitações", fmt.header)  # type: ignore[attr-defined]
    r += 1
    sheet.write(r, 0, "Taxa de aceitação das sugestões")  # type: ignore[attr-defined]
    sheet.write(r, 1, "n/d -- ver aba Taxa de aceitação")  # type: ignore[attr-defined]
    r += 2
    sheet.write(  # type: ignore[attr-defined]
        r,
        0,
        "O andar 1 abre a conta (não precisa de modelo); o andar 2 e a operação semanal "
        "da lista de compra são o que a mantêm -- ver Sprint 18.",
        fmt.note,
    )
    sheet.set_row(r, 34)  # type: ignore[attr-defined]


def _write_resumo_sheet(workbook: xlsxwriter.Workbook, data: _ReportData, fmt: _Formats) -> None:
    sheet = workbook.add_worksheet("Resumo executivo")
    sheet.set_column(0, 0, 46)
    sheet.set_column(1, 1, 20)
    r = _write_resumo_cabecalho(sheet, data, fmt)
    r = _write_resumo_andar1_bloco(sheet, r, data, fmt)
    r = _write_resumo_andar2_bloco(sheet, r, data, fmt)
    _write_resumo_rodape(sheet, r, fmt)


def _write_andar1_sheet(workbook: xlsxwriter.Workbook, data: _ReportData, fmt: _Formats) -> None:
    sheet = workbook.add_worksheet("Andar 1 - Correção de cadastro")
    sheet.set_column(0, 0, 46)
    sheet.set_column(1, 4, 22)
    headers = (
        "indicador",
        *(f"desatualizado ({label})" for label in STALE_SOURCES),
        "recalibrado",
    )
    for c, h in enumerate(headers):
        sheet.write(0, c, h, fmt.header)

    stale = data.stale
    recalibrado = data.recalibrado
    linhas: list[tuple[str, tuple[float, ...], object]] = [
        (
            "nível de serviço",
            (*(stale[label].nivel_servico for label in STALE_SOURCES), recalibrado.nivel_servico),
            fmt.pct,
        ),
        (
            "ruptura_rs (total do período)",
            (*(stale[label].ruptura_rs for label in STALE_SOURCES), recalibrado.ruptura_rs),
            fmt.money,
        ),
        (
            "capital_medio_rs",
            (
                *(stale[label].capital_medio_rs for label in STALE_SOURCES),
                recalibrado.capital_medio_rs,
            ),
            fmt.money,
        ),
        (
            "decision_metric",
            (
                *(stale[label].decision_metric for label in STALE_SOURCES),
                recalibrado.decision_metric,
            ),
            fmt.number,
        ),
    ]
    r = 1
    for _nome, valores, cell_fmt in linhas:
        sheet.write(r, 0, _nome)
        for c, v in enumerate(valores, start=1):
            sheet.write_number(r, c, v, cell_fmt)
        r += 1
    r += 1

    sheet.write(r, 0, "RUPTURA EVITADA (total do período, margem recuperada)", fmt.header)
    for c in range(1, len(STALE_SOURCES) + 1):
        sheet.write(r, c, "", fmt.header)
    r += 1
    for label in STALE_SOURCES:
        sheet.write(r, 0, f"  vs. {label}")
        sheet.write_number(r, 1, data.andar1_ruptura_evitada[label], fmt.money)
        r += 1
    r += 1

    sheet.write(
        r,
        0,
        "AUMENTO DE CAPITAL EMPREGADO (total do período, NÃO é capital liberado)",
        fmt.header,
    )
    for c in range(1, len(STALE_SOURCES) + 1):
        sheet.write(r, c, "", fmt.header)
    r += 1
    for label in STALE_SOURCES:
        sheet.write(r, 0, f"  vs. {label}")
        sheet.write_number(r, 1, data.andar1_aumento_capital[label], fmt.money)
        r += 1
    r += 1
    sheet.write(
        r,
        0,
        "Recalibrar EXIGE mais capital empregado, não libera -- é o espelho do resgate de "
        "serviço (sair de ~60-66% para ~94,85% de serviço significa guardar mais estoque, "
        "não menos). 'Capital liberado' só acontece no Andar 2, sobre o baseline já "
        "recalibrado (ver aba Andar 2).",
        fmt.note,
    )
    sheet.set_row(r, 48)
    r += 2

    sheet.write(
        r, 0, f"SENSIBILIDADE DE MARGEM (±30%) -- magnitude {STALE_LABEL_HEADLINE}", fmt.header
    )
    sheet.write(r, 1, "", fmt.header)
    r += 1
    base = data.andar1_ruptura_evitada[STALE_LABEL_HEADLINE]
    for factor, valor in sensibilidade_margem(base).items():
        if factor == 0.7:
            rotulo = "margem -30%"
        elif factor == 1.3:
            rotulo = "margem +30%"
        else:
            rotulo = "margem medida"
        sheet.write(r, 0, f"  {rotulo} (fator {factor})")
        sheet.write_number(r, 1, valor, fmt.money)
        r += 1
    r += 1

    sheet.write(
        r,
        0,
        "Faixa por transparência: category_margin_pct é premissa arbitrada (analogia com "
        "varejo brasileiro, ver aba Premissas), não medida no cliente. A ruptura evitada "
        "escala linearmente com margem -- ver docstring do módulo para a prova. Capital "
        "liberado NÃO tem faixa de sensibilidade de margem (não escala linearmente).",
        fmt.note,
    )
    sheet.set_row(r, 60)


def _write_andar2_sheet(workbook: xlsxwriter.Workbook, data: _ReportData, fmt: _Formats) -> None:
    sheet = workbook.add_worksheet("Andar 2 - Refinamento do modelo")
    sheet.set_column(0, 0, 46)
    sheet.set_column(1, 2, 22)
    for c, h in enumerate(("indicador", "baseline recalibrado", "motor")):
        sheet.write(0, c, h, fmt.header)

    recalibrado, motor = data.recalibrado, data.motor
    linhas = [
        ("nível de serviço", recalibrado.nivel_servico, motor.nivel_servico, fmt.pct),
        ("ruptura_rs (total do período)", recalibrado.ruptura_rs, motor.ruptura_rs, fmt.money),
        ("capital_medio_rs", recalibrado.capital_medio_rs, motor.capital_medio_rs, fmt.money),
        ("decision_metric", recalibrado.decision_metric, motor.decision_metric, fmt.number),
        (
            "margem_realizada_rs (total do período)",
            recalibrado.margem_realizada_rs,
            motor.margem_realizada_rs,
            fmt.money,
        ),
    ]
    r = 1
    for nome, a, b, cell_fmt in linhas:
        sheet.write(r, 0, nome)
        sheet.write_number(r, 1, a, cell_fmt)
        sheet.write_number(r, 2, b, cell_fmt)
        r += 1
    r += 1

    sheet.write(r, 0, "Capital liberado (total do período)")
    sheet.write_number(r, 1, data.andar2_capital_liberado, fmt.money)
    r += 1
    sheet.write(r, 0, "Capital liberado (%)")
    sheet.write_number(r, 1, data.andar2_capital_liberado / recalibrado.capital_medio_rs, fmt.pct)
    r += 1
    sheet.write(r, 0, "decision_metric (%)")
    sheet.write_number(r, 1, motor.decision_metric / recalibrado.decision_metric - 1, fmt.pct)
    r += 2

    sheet.write(
        r,
        0,
        "O ganho do modelo aqui é quase todo em capital liberado, não em margem recuperada: "
        "motor e baseline recalibrado operam no MESMO nível de serviço por construção "
        "iso-serviço (Sprint 17) -- a diferença de margem realizada entre os dois "
        f"(R$ {data.andar2_ruptura_evitada:,.2f} no período) é resíduo de granularidade da "
        "grade de alpha, não um efeito de negócio a vender separadamente.",
        fmt.note,
    )
    sheet.set_row(r, 60)


_SANGRANDO_HEADERS: Final[tuple[str, ...]] = (
    "código",
    "categoria",
    "unidade de venda",
    "preço (R$)",
    "custo (R$)",
    "margem (%)",
    "margem realizada (R$)",
    "ruptura (R$)",
    "% da margem potencial perdida",
    "nível de serviço do item",
)


def _write_sangrando_sheet(workbook: xlsxwriter.Workbook, fmt: _Formats) -> None:
    sheet = workbook.add_worksheet("Itens sangrando margem")
    for c, h in enumerate(_SANGRANDO_HEADERS):
        sheet.write(0, c, h, fmt.header)
    for c, w in enumerate((12, 20, 16, 12, 12, 12, 20, 16, 22, 20)):
        sheet.set_column(c, c, w)

    df = itens_sangrando_margem()
    for r_idx, row in enumerate(df.iter_rows(named=True), start=1):
        sheet.write(r_idx, 0, row["item_id"])
        sheet.write(r_idx, 1, row["category"])
        sheet.write(r_idx, 2, row["unit_of_sale"])
        sheet.write_number(r_idx, 3, row["price"], fmt.money)
        sheet.write_number(r_idx, 4, row["cost"], fmt.money)
        sheet.write_number(r_idx, 5, row["margin_pct"], fmt.pct)
        sheet.write_number(r_idx, 6, row["margem_realizada_rs"], fmt.money)
        sheet.write_number(r_idx, 7, row["ruptura_rs"], fmt.money)
        sheet.write_number(r_idx, 8, row["pct_margem_potencial_perdida"], fmt.pct)
        sheet.write_number(r_idx, 9, row["nivel_servico"], fmt.pct)
    sheet.autofilter(0, 0, df.height, len(_SANGRANDO_HEADERS) - 1)

    note_row = df.height + 2
    sheet.write(
        note_row,
        0,
        f"Top {TOP_N_ITENS_SANGRANDO} itens por ruptura_rs ABSOLUTA sob o motor (braço 2, "
        "alpha iso-serviço) -- os que ainda sangram margem mesmo com a ferramenta ativa, "
        "candidatos a revisão manual/escalonamento com o fornecedor. "
        "'% da margem potencial perdida' = ruptura / (ruptura + margem realizada), por item.",
        fmt.note,
    )
    sheet.set_row(note_row, 48)


_ACEITACAO_NOTES: Final[tuple[str, ...]] = (
    "n/d nesta etapa -- esta métrica NÃO EXISTE sem um comprador humano decidindo, ciclo a "
    "ciclo, se aceita, ajusta ou ignora a sugestão do motor. O período simulado usado neste "
    "relatório não tem esse comprador: é um backtest onde a política decide sozinha, sem "
    "intervenção.",
    "O que ela vai medir, quando existir: por ciclo de decisão, a fração do valor (R$) "
    "sugerido pelo motor que o comprador mantém sem alteração -- a métrica nasce no MODO "
    "SOMBRA (o motor sugere, o comprador decide de verdade, as duas listas ficam registradas "
    "lado a lado) e não antes disso.",
)


def _write_aceitacao_sheet(workbook: xlsxwriter.Workbook, fmt: _Formats) -> None:
    sheet = workbook.add_worksheet("Taxa de aceitação")
    sheet.set_column(0, 0, 110)
    sheet.write(0, 0, "TAXA DE ACEITAÇÃO DAS SUGESTÕES", fmt.bold)
    for r_idx, text in enumerate(_ACEITACAO_NOTES, start=1):
        sheet.write(r_idx, 0, text, fmt.note)
        sheet.set_row(r_idx, 48)


def _write_premissas_sheet(workbook: xlsxwriter.Workbook, fmt: _Formats) -> None:
    base_params = load_params(PARAMS_PATH)
    sheet = workbook.add_worksheet("Premissas")
    sheet.set_column(0, 0, 40)
    sheet.set_column(1, 1, 20)
    sheet.set_column(2, 2, 70)
    for c, h in enumerate(("premissa", "valor", "origem/justificativa")):
        sheet.write(0, c, h, fmt.header)

    linhas_premissas: list[tuple[str, object, str]] = [
        ("lead_time_days (célula)", 7, "arbitrado -- célula real de hoje, Sprint 16.5/17"),
        ("review_period_days (célula)", 14, "arbitrado -- célula real de hoje, Sprint 16.5/17"),
        (
            "capital_cost_annual",
            base_params.economics.capital_cost_annual,
            "arbitrado por analogia, varejo pequeno/médio no Brasil (config/params.yaml)",
        ),
        (
            "uniform_unit_price (R$)",
            base_params.economics.uniform_unit_price,
            "Favorita não tem preço em nenhuma linha do bruto -- preço único aplicado a todo "
            "item; prova em motor.metrics.financial de que a escala não afeta decision_metric",
        ),
        (
            "sensibilidade de margem",
            "±30% (0,7x / 1,3x)",
            "arbitrada -- magnitude de erro de premissa que este relatório declara suportar, "
            "não uma faixa medida",
        ),
        (
            "conversão para mensal",
            f"{DAYS_PER_MONTH:.0f} dias",
            "mês de 30 dias -- não existe mês-calendário real de produção nesta etapa",
        ),
        (
            "validade/shelf life",
            "não modelada",
            "shelf_life_from_arrival_days=None para todo item em todo braço -- perda_rs "
            "estruturalmente R$ 0,00, ver aba Limitações",
        ),
        (
            "guardrails/orçamento (Sprint 13)",
            "fora de escopo deste relatório",
            "as 4 regras de guarda e a restrição de caixa mudam a lista de compra semanal "
            "(results/lista_compra/), não a simulação de portfólio usada aqui",
        ),
    ]
    r = 1
    for nome, valor, origem in linhas_premissas:
        sheet.write(r, 0, nome)
        if isinstance(valor, float):
            sheet.write_number(r, 1, valor, fmt.number)
        else:
            sheet.write(r, 1, str(valor))
        sheet.write(r, 2, origem, fmt.note)
        sheet.set_row(r, 34)
        r += 1
    r += 1

    sheet.write(r, 0, "category_margin_pct (por categoria)", fmt.header)
    sheet.write(r, 1, "", fmt.header)
    sheet.write(r, 2, "", fmt.header)
    r += 1
    for categoria, margem in sorted(base_params.economics.category_margin_pct.items()):
        sheet.write(r, 0, f"  {categoria}")
        sheet.write_number(r, 1, float(margem), fmt.pct)
        r += 1
    sheet.write(r, 0, "  (categoria fora da lista acima)")
    sheet.write_number(r, 1, float(base_params.economics.default_margin_pct), fmt.pct)
    sheet.write(r, 2, "default_margin_pct -- piso quando a categoria não está mapeada", fmt.note)


def _write_limitacoes_sheet(workbook: xlsxwriter.Workbook, fmt: _Formats) -> None:
    sheet = workbook.add_worksheet("Limitações")
    sheet.set_column(0, 0, 110)
    sheet.write(0, 0, "LIMITAÇÕES DECLARADAS", fmt.bold)
    for r_idx, text in enumerate(LIMITATIONS, start=1):
        sheet.write(r_idx, 0, text, fmt.note)
        sheet.set_row(r_idx, 60)


def write_monthly_report_workbook(out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = xlsxwriter.Workbook(str(out_path))
    fmt = _Formats(
        header=workbook.add_format(_HEADER_FORMAT_SPEC),
        money=workbook.add_format({"num_format": "R$ #,##0.00"}),
        number=workbook.add_format({"num_format": "#,##0.00"}),
        pct=workbook.add_format({"num_format": "0.0%"}),
        note=workbook.add_format({"text_wrap": True, "valign": "top"}),
        bold=workbook.add_format({"bold": True}),
    )

    data = _build_report_data()
    _write_resumo_sheet(workbook, data, fmt)
    _write_andar1_sheet(workbook, data, fmt)
    _write_andar2_sheet(workbook, data, fmt)
    _write_sangrando_sheet(workbook, fmt)
    _write_aceitacao_sheet(workbook, fmt)
    _write_premissas_sheet(workbook, fmt)
    _write_limitacoes_sheet(workbook, fmt)

    workbook.close()
    return out_path


LIMITATIONS: Final[tuple[str, ...]] = (
    "Ruptura (demanda não atendida) NÃO é observada -- é inferida pelo simulador comparando "
    "a demanda prevista (forecaster) contra o estoque simulado, nunca contra saldo de "
    "estoque real de loja (o dado público Favorita não tem essa coluna). Todo R$ de ruptura "
    "neste relatório é simulado, não medido em produção.",
    "NÃO existe hoje nenhuma correção de demanda censurada implementada no motor -- "
    "correção deste ponto: o texto original desta etapa dizia 'está projetada'; o código "
    "(`motor.features.build.build_feature_row`) documenta explicitamente que está FORA DE "
    "ESCOPO enquanto não houver saldo de estoque real de cliente (dias de saldo zero "
    "teriam demanda subestimada, se o dado tivesse estoque). O que existe é a premissa "
    "declarada (venda observada = demanda), CLAUDE.md seção 8 -- não uma feature construída "
    "à espera de validação.",
    "Perda evitada é R$ 0,00 nos dois andares, sempre -- não é resultado, é ausência de "
    "premissa: nenhum braço modela validade/expiração (shelf_life_from_arrival_days=None "
    "para todo item, todo braço). Um cliente real com produto perecível físico teria perda "
    "por vencimento que este relatório não captura.",
    "Taxa de aceitação das sugestões não existe sem comprador humano -- ver aba dedicada. "
    "Métrica que só nasce no modo sombra.",
    "'Mensal' aqui é o total do período simulado dividido por uma média de 30 dias -- não um "
    "mês-calendário real medido em produção. Ver aba Premissas.",
    "As 4 regras de guarda (Sprint 13) e a restrição de caixa por orçamento NÃO entram "
    "nestas métricas -- elas mudam a lista de compra semanal, não a simulação de portfólio "
    "usada aqui. Quantificar o custo do seguro das guardas sobre decision_metric/capital é "
    "um experimento declarado à parte, ainda não feito.",
    "Validade restrita a UMA célula (lead_time=7, review_period=14) -- generalizar para "
    "outras combinações é hipótese, não resultado (Sprint 17).",
    "A sensibilidade de margem (±30%) cobre só ruptura evitada/margem recuperada -- "
    "capital_medio_rs não escala linearmente com margin_pct (direção oposta: cost = price x "
    "(1 - margin_pct)) e não tem faixa de sensibilidade calculada nesta etapa.",
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("results/relatorio_mensal/relatorio_mensal.xlsx")
    )
    args = parser.parse_args(argv)
    path = write_monthly_report_workbook(args.output)
    print(f"relatório salvo em {path}")


if __name__ == "__main__":
    main()

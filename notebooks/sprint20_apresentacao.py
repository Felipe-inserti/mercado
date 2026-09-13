"""Apresentação de 15 minutos (Sprint 20, Fase 4, Etapa 4.3) -- pdf de uma
lâmina por página, gerado com matplotlib (já dependência do projeto, sem
biblioteca nova).

Lógica de negócio nenhuma vive aqui (CLAUDE.md, seção 2) -- só leitura dos
resultados já produzidos pelas Sprints 17/18/19 e montagem das lâminas.
Rodar depois que `results/iso_servico/`, `results/baseline_desatualizado/`
e `results/lista_compra/2017-03-06/` já existirem.

    python notebooks/sprint20_apresentacao.py

Ordem das lâminas (pedida na Etapa 4.3), e por que cada uma está onde está:

    1. O problema em R$
    2. O diagnóstico -- R$/mês de ruptura, sempre com a faixa de ±30% ao lado
    3. Andar 1 -- a correção, com o CUSTO em capital na MESMA lâmina (pedido
       explícito: "é exatamente o tipo de coisa que, descoberta no segundo
       mês de contrato, faz o dono concluir que foi enganado")
    4. Andar 2 -- o refinamento, com a nota que mata a tese de cauda
       (Spearman 0,275) na mesma lâmina onde o ganho aparece
    5. O produto -- a lista de compra de 2017-03-06, uma tela real
    6. As guardas -- o que existe e o que está declarado como não
       implementado
    7. O modo sombra -- o que está sendo vendido primeiro
    8. Limitações
    9. Perguntas antecipadas -- não pedida no enunciado, adicionada para
       tornar VERIFICÁVEL o critério de pronto ("a primeira pergunta
       cética que você mesmo faria já está respondida dentro dela") --
       cada pergunta aponta pra lâmina que já responde, em vez de confiar
       em releitura.

REGRA DE CONTEÚDO 1 (sem tese de cauda): a cobertura de 3.000 itens
aparece na lâmina 1 como argumento OPERACIONAL (ninguém revisa 3.000 itens
à mão) -- nunca como fonte do ganho medido. A lâmina 4 traz a nota
explícita (Spearman 0,275) no mesmo lugar onde o ganho de R$ aparece, para
que a moldura certa esteja ao lado do número, não numa lâmina separada que
alguém pode não abrir.

REGRA DE CONTEÚDO 2 (premissa ao lado de todo número): toda lâmina com um
R$ tem uma nota de rodapé citando a premissa que o gera (margem, lead
time, validade) -- nunca um número sozinho.

FONTE DA LÂMINA 5 (produto): os valores vêm de dois arquivos REAIS já
gerados (Sprint 17, `results/lista_compra/2017-03-06/`) -- `SUP-CLEANING.xlsx`
(lista principal, aprovação em bloco) e `SUP-BREAD_BAKERY.xlsx` (exceções,
teto de validade menor que a janela de risco). Citados como constantes
aqui (não relidos via biblioteca de leitura de xlsx -- não é dependência
do projeto, ver pyproject.toml) em vez de recomputados: reabrir o
`Simulator` só para uma tela ilustrativa de apresentação seria ~7-8 min de
custo por uma tabela que já existe em disco. Se a lista de compra for
regenerada, revisar estes números à mão contra o arquivo citado.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Final

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch

from motor.experiments.iso_service import CELL_LEAD_TIME_DAYS, CELL_REVIEW_PERIOD_DAYS
from motor.reporting.monthly_report import (
    STALE_LABEL_HEADLINE,
    load_motor_financials,
    load_recalibrado_financials,
    load_stale_financials,
    mensalizar,
    sensibilidade_margem,
)

RESULTS_DIR: Final[Path] = Path("results")
ISO_SERVICE_DIR: Final[Path] = RESULTS_DIR / "iso_servico"
OUT_PATH: Final[Path] = RESULTS_DIR / "apresentacao" / "motor_de_decisao_de_compra.pdf"

# -- paleta (mesma família de cor do relatório mensal/lista de compra) ------
NAVY: Final[str] = "#1f3864"
TEAL: Final[str] = "#1baf7a"
AMBER: Final[str] = "#c9760a"
INK: Final[str] = "#2b2b2b"
MUTED: Final[str] = "#6b6b6b"
PAPER: Final[str] = "#ffffff"
PANEL: Final[str] = "#f2f4f7"

FIG_W, FIG_H = 13.333, 7.5  # 16:9

# -- os dois arquivos-fonte da lâmina 5 (ver docstring do módulo) -----------
_PRODUTO_ARQUIVO_PRINCIPAL: Final[str] = "results/lista_compra/2017-03-06/SUP-CLEANING.xlsx"
_PRODUTO_ARQUIVO_EXCECAO: Final[str] = "results/lista_compra/2017-03-06/SUP-BREAD_BAKERY.xlsx"
_PRODUTO_LISTA_PRINCIPAL: Final[tuple[tuple[str, str, float, float], ...]] = (
    ("1057495", "CLEANING", 84.0, 588.00),
    ("158788", "CLEANING", 96.0, 672.00),
    ("168927", "CLEANING", 180.0, 1260.00),
    ("168930", "CLEANING", 336.0, 2352.00),
    ("214862", "CLEANING", 72.0, 504.00),
)
_PRODUTO_EXCECOES: Final[tuple[tuple[str, str, float, float, str], ...]] = (
    (
        "103665",
        "BREAD/BAKERY",
        60.0,
        408.00,
        "teto de validade (14d) menor que a janela de risco",
    ),
    (
        "311994",
        "BREAD/BAKERY",
        462.0,
        3141.60,
        "teto de validade (14d) menor que a janela de risco",
    ),
    (
        "502331",
        "BREAD/BAKERY",
        708.0,
        4814.40,
        "teto de validade (14d) menor que a janela de risco",
    ),
)


def _slide() -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(figsize=(FIG_W, FIG_H), facecolor=PAPER)
    ax = fig.add_axes((0.0, 0.0, 1.0, 1.0))
    ax.set_xlim(0, FIG_W)
    ax.set_ylim(0, FIG_H)
    ax.axis("off")
    return fig, ax


def _title_bar(ax: plt.Axes, numero: str, titulo: str, subtitulo: str = "") -> None:
    ax.add_patch(
        FancyBboxPatch((0, FIG_H - 1.15), FIG_W, 1.15, boxstyle="square,pad=0", fc=NAVY, ec=NAVY)
    )
    ax.text(0.55, FIG_H - 0.35, numero, fontsize=14, color=TEAL, fontweight="bold", va="center")
    ax.text(0.55, FIG_H - 0.68, titulo, fontsize=23, color=PAPER, fontweight="bold", va="center")
    if subtitulo:
        ax.text(0.55, FIG_H - 1.0, subtitulo, fontsize=11.5, color="#c7d3e6", va="center")


def _footnote(ax: plt.Axes, text: str) -> None:
    wrapped = "\n".join(textwrap.wrap(text, width=150))
    ax.text(0.55, 0.32, wrapped, fontsize=9.5, color=MUTED, va="top", style="italic")


def _bullets(
    ax: plt.Axes,
    items: list[str],
    *,
    x: float,
    y: float,
    fontsize: float = 15,
    pad: float = 0.22,
    width: int = 62,
) -> float:
    """`y` desce por ALTURA DE LINHA REAL (`1 ponto = 1/72 polegada`, e os
    eixos desta apresentação usam 1 unidade = 1 polegada -- `_slide` fixa
    `xlim`/`ylim` no tamanho da figura em polegadas) mais `pad` de respiro
    entre marcadores -- não um número arbitrário por marcador. Sem isto, um
    bullet de 3 linhas podia empurrar o próximo pra fora da lâmina em
    silêncio (achado real ao revisar a lâmina 1 -- 3º marcador cortado)."""
    line_h = 1.35 * fontsize / 72
    for item in items:
        wrapped = textwrap.fill(item, width=width)
        n_lines = wrapped.count("\n") + 1
        ax.text(x, y, "•", fontsize=fontsize, color=TEAL, fontweight="bold", va="top")
        ax.text(x + 0.35, y, wrapped, fontsize=fontsize, color=INK, va="top", linespacing=1.35)
        y -= line_h * n_lines + pad
    return y


def _big_number(
    ax: plt.Axes, *, x: float, y: float, w: float, h: float, value: str, label: str, color: str
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08", fc=PANEL, ec=color, lw=2
        )
    )
    ax.text(
        x + w / 2,
        y + h * 0.62,
        value,
        fontsize=30,
        color=color,
        fontweight="bold",
        ha="center",
        va="center",
    )
    ax.text(
        x + w / 2,
        y + h * 0.22,
        "\n".join(textwrap.wrap(label, width=int(w * 5.5))),
        fontsize=11.5,
        color=INK,
        ha="center",
        va="center",
    )


def _page_number(ax: plt.Axes, n: int, total: int) -> None:
    ax.text(FIG_W - 0.55, 0.32, f"{n} / {total}", fontsize=10, color=MUTED, ha="right", va="top")


# --------------------------------------------------------------------------
# dados (Sprints 17-19, reusados -- nenhum experimento novo)
# --------------------------------------------------------------------------


def _dados() -> dict[str, object]:
    motor = load_motor_financials()
    recalibrado = load_recalibrado_financials()
    stale = load_stale_financials(STALE_LABEL_HEADLINE)
    ruptura_evitada_mensal = mensalizar(stale.ruptura_rs - recalibrado.ruptura_rs)
    faixa = sensibilidade_margem(stale.ruptura_rs - recalibrado.ruptura_rs)
    aumento_capital_mensal = mensalizar(recalibrado.capital_medio_rs - stale.capital_medio_rs)
    capital_liberado_pct = (
        recalibrado.capital_medio_rs - motor.capital_medio_rs
    ) / recalibrado.capital_medio_rs
    decision_metric_pct = motor.decision_metric / recalibrado.decision_metric - 1
    spearman = json.loads((ISO_SERVICE_DIR / "resumo_decomposicao_alpha066.json").read_text())[
        "spearman_decision_metric_vs_pct_dias_com_venda"
    ]
    return {
        "nivel_servico_stale": stale.nivel_servico,
        "nivel_servico_recalibrado": recalibrado.nivel_servico,
        "ruptura_evitada_mensal": ruptura_evitada_mensal,
        "ruptura_evitada_mensal_menos30": mensalizar(faixa[0.7]),
        "ruptura_evitada_mensal_mais30": mensalizar(faixa[1.3]),
        "aumento_capital_mensal": aumento_capital_mensal,
        "capital_liberado_pct": capital_liberado_pct,
        "decision_metric_pct": decision_metric_pct,
        "spearman": spearman,
    }


# --------------------------------------------------------------------------
# lâminas
# --------------------------------------------------------------------------


def slide_titulo() -> plt.Figure:
    fig, ax = _slide()
    ax.add_patch(FancyBboxPatch((0, 0), FIG_W, FIG_H, boxstyle="square,pad=0", fc=NAVY, ec=NAVY))
    ax.text(
        FIG_W / 2,
        FIG_H / 2 + 0.9,
        "Motor de decisão de compra",
        fontsize=34,
        color=PAPER,
        fontweight="bold",
        ha="center",
    )
    ax.text(
        FIG_W / 2,
        FIG_H / 2 + 0.15,
        "Quanto pedir, de cada item, a cada fornecedor -- sem depender de memória",
        fontsize=15,
        color="#c7d3e6",
        ha="center",
    )
    ax.text(
        FIG_W / 2,
        FIG_H / 2 - 0.7,
        "Apresentação de 15 minutos -- proposta de entrada em modo sombra",
        fontsize=12,
        color=TEAL,
        ha="center",
    )
    return fig


def slide_problema() -> plt.Figure:
    fig, ax = _slide()
    _title_bar(ax, "1", "O problema em R$", "Por que o dono de uma loja não vê a própria perda")
    y = _bullets(
        ax,
        [
            "O ERP só registra o que foi VENDIDO -- ruptura (demanda que existia e não foi "
            "atendida) não aparece em nenhum relatório dele. O dinheiro perdido é invisível "
            "por desenho, não por acidente.",
            "A compra hoje é decidida por memória do encarregado e pressão de representante de "
            "fornecedor -- não por uma conta de quanto o item realmente precisa, dado o que já "
            "está em estoque e a caminho.",
            "O sortimento tem ~3.000 itens. Ninguém revisa 3.000 itens por semana à mão -- "
            "sobra atenção para os ~30 que mais chamam a atenção, o resto anda no piloto "
            "automático do fornecedor.",
        ],
        x=0.55,
        y=5.6,
        fontsize=15.5,
        pad=0.30,
        width=78,
    )
    del y
    _footnote(
        ax,
        "A cobertura de 3.000 itens é um argumento OPERACIONAL (ninguém revisa isso à mão) -- "
        "não é onde o ganho medido está. Ver lâmina 4.",
    )
    return fig


def slide_diagnostico(dados: dict[str, object]) -> plt.Figure:
    fig, ax = _slide()
    _title_bar(
        ax,
        "2",
        "O diagnóstico",
        f"Célula real: lead time {CELL_LEAD_TIME_DAYS}d / revisão {CELL_REVIEW_PERIOD_DAYS}d",
    )
    _bullets(
        ax,
        [
            "O ERP de hoje tem um fator de reposição calibrado para um lead time que o "
            "fornecedor já não tem mais -- ninguém voltou para atualizar quando ele mudou.",
        ],
        x=0.55,
        y=5.55,
        fontsize=15.5,
        pad=0.28,
        width=78,
    )
    _big_number(
        ax,
        x=0.7,
        y=1.55,
        w=3.6,
        h=2.4,
        value=f"{dados['nivel_servico_stale']:.0%}",
        label="nível de serviço com o fator desatualizado",
        color=AMBER,
    )
    _big_number(
        ax,
        x=4.6,
        y=1.55,
        w=3.6,
        h=2.4,
        value=f"R$ {dados['ruptura_evitada_mensal']:,.0f}",
        label="margem perdida em ruptura, por mês, medida contra o baseline já corrigido",
        color=AMBER,
    )
    _big_number(
        ax,
        x=8.5,
        y=1.55,
        w=4.1,
        h=2.4,
        value="±30%",
        label=(
            f"faixa de margem: R$ {dados['ruptura_evitada_mensal_menos30']:,.0f} a "
            f"R$ {dados['ruptura_evitada_mensal_mais30']:,.0f} / mês"
        ),
        color=NAVY,
    )
    _footnote(
        ax,
        "Nunca o número sozinho: margem por categoria é premissa ARBITRADA (analogia com "
        "varejo brasileiro, não medida neste cliente) -- a faixa de ±30% é a magnitude de "
        "erro que este diagnóstico declara suportar. Medido por simulação sobre o padrão de "
        "vendas passado real, célula única (lt=7/rp=14).",
    )
    return fig


def slide_andar1(dados: dict[str, object]) -> plt.Figure:
    fig, ax = _slide()
    _title_bar(ax, "3", "Andar 1 -- a correção", "Recalibrar. Sem modelo.")
    _bullets(
        ax,
        [
            "Ajustar o fator do PRÓPRIO ERP para o lead time real de hoje -- nenhum modelo, "
            "nenhum software novo, só o número certo no cadastro que já existe.",
        ],
        x=0.55,
        y=5.55,
        fontsize=15.5,
        pad=0.28,
        width=78,
    )
    _big_number(
        ax,
        x=1.3,
        y=1.6,
        w=4.7,
        h=2.5,
        value=f"~{dados['nivel_servico_recalibrado']:.0%}",
        label="nível de serviço alcançado -- sem trocar nada além do número",
        color=TEAL,
    )
    _big_number(
        ax,
        x=7.3,
        y=1.6,
        w=4.7,
        h=2.5,
        value=f"+R$ {dados['aumento_capital_mensal']:,.0f} / mês",
        label="capital adicional necessário -- servir mais exige estocar mais, não menos",
        color=AMBER,
    )
    ax.text(
        FIG_W / 2,
        1.25,
        "A conta tem dois lados. Você precisa saber dos dois ANTES de assinar, não depois.",
        fontsize=13,
        color=NAVY,
        fontweight="bold",
        ha="center",
        style="italic",
    )
    _footnote(
        ax,
        "Aumento de capital, não liberação -- é o espelho do resgate de serviço (sub-abastecer "
        "amarra menos capital; corrigir isso amarra mais). Premissas: custo de capital "
        "arbitrado (config), célula lt=7/rp=14.",
    )
    return fig


def slide_andar2(dados: dict[str, object]) -> plt.Figure:
    fig, ax = _slide()
    _title_bar(
        ax, "4", "Andar 2 -- o refinamento", "Sobre o baseline JÁ correto, mesmo nível de serviço"
    )
    _big_number(
        ax,
        x=0.9,
        y=3.5,
        w=5.5,
        h=2.35,
        value=f"{dados['capital_liberado_pct']:.1%}",
        label="capital liberado -- mesmo nível de serviço do baseline recalibrado",
        color=TEAL,
    )
    _big_number(
        ax,
        x=6.9,
        y=3.5,
        w=5.5,
        h=2.35,
        value=f"+{dados['decision_metric_pct']:.1%}",
        label="margem por real investido -- mesmo nível de serviço",
        color=TEAL,
    )
    _bullets(
        ax,
        [
            "Modelo estatístico simples (sazonalidade + nível-alvo por quantil) -- não é uma "
            "rede neural, não precisa de retreino semanal, e cada decisão é explicável em uma "
            'frase: "a demanda dos últimos ciclos, no quantil de risco certo".',
        ],
        x=0.55,
        y=3.15,
        fontsize=13.5,
        pad=0.25,
        width=90,
    )
    ax.text(
        0.55,
        1.75,
        textwrap.fill(
            f"O ganho é DISTRIBUÍDO pelo portfólio, não concentrado nos itens de venda "
            f"irregular (correlação fraca, Spearman {dados['spearman']:.3f}) -- a cobertura de "
            "3.000 itens (lâmina 1) continua um argumento operacional, não a fonte deste número.",
            width=110,
        ),
        fontsize=11.5,
        color=MUTED,
        va="top",
        style="italic",
    )
    _footnote(
        ax,
        "Medido contra o baseline JÁ recalibrado (lâmina 3), não contra o ERP desatualizado -- "
        "comparar contra o desatualizado infla o número por um artefato de razão (menos "
        "estoque, mais ruptura). Ver Sprint 18.",
    )
    return fig


_CHARS_PER_INCH_AT_10PT: Final[float] = 12.5
"""Estimativa grosseira (fonte sans-serif, 10pt) só para decidir a quebra de
linha da coluna de texto livre ('motivo') -- não precisa ser exata, só
evitar que o texto vaze para fora da coluna/da lâmina."""


def _tabela_produto(
    ax: plt.Axes,
    *,
    x: float,
    y: float,
    w: float,
    titulo: str,
    headers: tuple[str, ...],
    rows: tuple[tuple[str, ...], ...],
    accent: str,
    col_fracs: tuple[float, ...] | None = None,
) -> None:
    """`col_fracs` (frações de `w`, somando 1,0) -- se omitido, colunas
    uniformes. A ÚLTIMA coluna quebra linha automaticamente para caber na
    própria largura (é onde vai o texto livre, ex.: motivo de exceção) --
    a altura da linha cresce para acomodar o texto quebrado."""
    fracs = col_fracs or tuple(1.0 / len(headers) for _ in headers)
    col_widths = [w * f for f in fracs]
    col_x = [x + sum(col_widths[:i]) for i in range(len(headers))]

    ax.text(x, y + 0.42, titulo, fontsize=13, color=accent, fontweight="bold", va="bottom")
    header_h = 0.48
    header_y = y
    ax.add_patch(
        FancyBboxPatch(
            (x, header_y - header_h), w, header_h, boxstyle="square,pad=0", fc=accent, ec=accent
        )
    )
    for c, h in enumerate(headers):
        ax.text(
            col_x[c] + 0.1,
            header_y - header_h / 2,
            h,
            fontsize=10,
            color=PAPER,
            fontweight="bold",
            va="center",
        )

    last_col_chars = max(1, int(col_widths[-1] * _CHARS_PER_INCH_AT_10PT))
    row_top = header_y - header_h
    for r, row in enumerate(rows):
        wrapped_last = textwrap.wrap(row[-1], width=last_col_chars) or [""]
        n_lines = len(wrapped_last)
        row_h = 0.30 * n_lines + 0.18
        row_y = row_top - row_h
        bg = PANEL if r % 2 else PAPER
        ax.add_patch(
            FancyBboxPatch(
                (x, row_y), w, row_h, boxstyle="square,pad=0", fc=bg, ec="#dddddd", lw=0.5
            )
        )
        for c, val in enumerate(row[:-1]):
            ax.text(col_x[c] + 0.1, row_y + row_h / 2, val, fontsize=10, color=INK, va="center")
        ax.text(
            col_x[-1] + 0.1,
            row_y + row_h / 2,
            "\n".join(wrapped_last),
            fontsize=9,
            color=INK,
            va="center",
        )
        row_top = row_y


def slide_produto() -> plt.Figure:
    fig, ax = _slide()
    _title_bar(
        ax, "5", "O produto", "Lista de compra de 2017-03-06 -- uma tela real, não uma maquete"
    )
    principal_rows = tuple(
        (codigo, cat, f"{qtd:,.0f}", f"R$ {valor:,.2f}")
        for codigo, cat, qtd, valor in _PRODUTO_LISTA_PRINCIPAL
    )
    _tabela_produto(
        ax,
        x=0.55,
        y=5.35,
        w=6.3,
        titulo="Lista principal -- aprovação em bloco (SUP-CLEANING)",
        headers=("código", "categoria", "sugestão (un.)", "valor (R$)"),
        rows=principal_rows,
        accent=TEAL,
        col_fracs=(0.24, 0.26, 0.26, 0.24),
    )
    excecao_rows = tuple(
        (codigo, cat, f"{qtd:,.0f}", f"R$ {valor:,.2f}", motivo)
        for codigo, cat, qtd, valor, motivo in _PRODUTO_EXCECOES
    )
    _tabela_produto(
        ax,
        x=7.15,
        y=5.35,
        w=6.0,
        titulo="Exceções -- motivo sempre visível (SUP-BREAD/BAKERY)",
        headers=("código", "categoria", "sug.", "R$", "motivo"),
        rows=excecao_rows,
        accent=AMBER,
        col_fracs=(0.15, 0.20, 0.10, 0.15, 0.40),
    )
    _bullets(
        ax,
        [
            "Um arquivo xlsx por fornecedor -- o comprador abre, aprova a lista principal em "
            "bloco, e olha só as exceções (com o motivo escrito, nunca um número sem "
            "explicação).",
        ],
        x=0.55,
        y=1.9,
        fontsize=13,
        pad=0.22,
        width=100,
    )
    _footnote(
        ax,
        f"Dados reais de {_PRODUTO_ARQUIVO_PRINCIPAL} e {_PRODUTO_ARQUIVO_EXCECAO} "
        "(Sprint 17) -- braço estatístico, alpha iso-serviço 0,66, guardas da Sprint 13 ativas.",
    )
    return fig


def slide_guardas() -> plt.Figure:
    fig, ax = _slide()
    _title_bar(ax, "6", "As guardas", "O que impede o motor de sugerir uma quantidade absurda")
    _bullets(
        ax,
        [
            "Teto de cobertura -- nunca sugere mais que o maior entre a validade do produto e "
            "a janela de risco real do fornecedor.",
            "Limite de variação -- se o pedido passar de 2x a média histórica de compra, "
            "SINALIZA para revisão humana em vez de simplesmente executar.",
            "Item novo -- itens com menos de 90 dias de histórico saem por uma regra separada "
            "(quantidade fixa = mediana da categoria), nunca decididos pelo modelo.",
            "Restrição de caixa com piso de 60% por categoria -- corta por margem quando o "
            "orçamento aperta, mas nenhuma categoria fica zerada; o corte respeita presença "
            "mínima de gôndola.",
        ],
        x=0.55,
        y=5.6,
        fontsize=14.5,
        pad=0.28,
        width=82,
    )
    ax.add_patch(
        FancyBboxPatch(
            (0.55, 0.75),
            FIG_W - 1.1,
            1.0,
            boxstyle="round,pad=0.03",
            fc="#fdf1e3",
            ec=AMBER,
            lw=1.5,
        )
    )
    ax.text(
        0.85,
        1.25,
        textwrap.fill(
            "Duas de seis regras do desenho original NÃO estão implementadas: promoção "
            "prevista (o dado não anuncia promoção com antecedência) e item âncora (exige "
            "análise de cesta, fora do escopo desta versão). Declarado -- não escondido.",
            width=118,
        ),
        fontsize=11.5,
        color=INK,
        va="center",
    )
    return fig


def slide_sombra() -> plt.Figure:
    fig, ax = _slide()
    _title_bar(ax, "7", "O modo sombra", "É isso que está sendo vendido primeiro -- não o motor")
    _bullets(
        ax,
        [
            "4 a 8 semanas rodando em paralelo ao processo de compra atual -- o motor sugere, "
            "o comprador continua decidindo e emitindo pedidos exatamente como faz hoje.",
            "NENHUM pedido é alterado. Zero risco operacional na loja.",
            "Mede o baseline REAL do cliente, com o dado REAL do cliente -- não a simulação "
            "sobre dado público que sustenta os números desta apresentação.",
            "No fim do período: o relatório mensal em R$ (mesmo formato da lâmina 2) comparando "
            "o que o motor teria sugerido contra o que foi de fato comprado.",
        ],
        x=0.55,
        y=5.6,
        fontsize=15,
        pad=0.28,
        width=80,
    )
    _footnote(
        ax,
        "Só depois do modo sombra é que faz sentido decidir sobre o Andar 2 (o modelo) com "
        "números do PRÓPRIO cliente -- os desta apresentação vêm de dado público (Favorita), "
        "ver lâmina 8.",
    )
    return fig


def slide_limitacoes() -> plt.Figure:
    fig, ax = _slide()
    _title_bar(
        ax, "8", "Limitações", "Declaradas -- não é isso que separa quem entende do que finge"
    )
    _bullets(
        ax,
        [
            "Os números desta apresentação vêm de dado público (Favorita), sem saldo de "
            "estoque real de loja.",
            "Ruptura não é observada -- é inferida pelo simulador comparando demanda prevista "
            "contra estoque simulado.",
            "Perda por validade/vencimento é R$ 0,00 sempre nestes números -- nenhum braço "
            "modela expiração; um cliente com produto perecível físico teria perda que este "
            "diagnóstico não captura.",
            "Correção de demanda censurada está FORA DE ESCOPO enquanto não houver saldo de "
            "estoque real do cliente -- não é uma funcionalidade pronta esperando validação.",
            "Validade restrita a UMA célula (lead time 7 dias, revisão 14 dias) -- generalizar "
            "para outras combinações é hipótese, não resultado medido.",
            "Margem por categoria, custo de capital e validade são premissas ARBITRADAS por "
            "analogia com o varejo brasileiro -- nunca medidas neste cliente específico.",
        ],
        x=0.55,
        y=5.65,
        fontsize=13.5,
        pad=0.22,
        width=92,
    )
    return fig


def slide_perguntas() -> plt.Figure:
    fig, ax = _slide()
    _title_bar(
        ax, "9", "Perguntas que você já ia fazer", "Cada uma aponta para a lâmina que já responde"
    )
    perguntas = [
        (
            "Como vocês sabem que eu perco R$ 190 mil/mês se ninguém mede isso hoje?",
            "Lâmina 2 -- medido por simulação sobre o histórico real de vendas, "
            "com faixa de erro declarada.",
        ),
        (
            "Isso não é só a velha história de 'cobrimos mais itens que você'?",
            "Lâminas 1 e 4 -- cobertura é argumento operacional; o ganho medido "
            "é distribuído, não de cauda (Spearman 0,275).",
        ),
        (
            "Se eu preciso de mais caixa pra consertar isso, não é golpe?",
            "Lâmina 3 -- o custo em capital está na MESMA lâmina do benefício, não escondido.",
        ),
        (
            "O motor pode um dia sugerir uma quantidade absurda?",
            "Lâmina 6 -- 4 guardas ativas, e as 2 que faltam estão declaradas, não escondidas.",
        ),
        (
            "Isso já rodou de verdade ou é só simulação em dado público?",
            "Lâmina 7 -- o modo sombra mede com o dado REAL do cliente antes de "
            "qualquer decisão maior.",
        ),
        (
            "Que garantia eu tenho que esses números não estão inflados?",
            "Lâmina 8 -- toda premissa arbitrada nomeada, nenhum número sem a "
            "faixa ou a origem ao lado.",
        ),
    ]
    fs_pergunta, fs_resposta = 13.5, 12.0
    line_h_pergunta = 1.35 * fs_pergunta / 72
    line_h_resposta = 1.35 * fs_resposta / 72
    y = 5.55
    for pergunta, resposta in perguntas:
        pergunta_wrapped = textwrap.fill(pergunta, width=95)
        resposta_wrapped = textwrap.fill(resposta, width=105)
        ax.text(0.55, y, "?", fontsize=16, color=AMBER, fontweight="bold", va="top")
        ax.text(
            1.0, y, pergunta_wrapped, fontsize=fs_pergunta, color=INK, fontweight="bold", va="top"
        )
        y -= line_h_pergunta * (pergunta_wrapped.count("\n") + 1) + 0.16
        ax.text(1.0, y, resposta_wrapped, fontsize=fs_resposta, color=MUTED, va="top")
        y -= line_h_resposta * (resposta_wrapped.count("\n") + 1) + 0.28
    return fig


def gerar_apresentacao(out_path: Path = OUT_PATH) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dados = _dados()
    slides = [
        slide_titulo(),
        slide_problema(),
        slide_diagnostico(dados),
        slide_andar1(dados),
        slide_andar2(dados),
        slide_produto(),
        slide_guardas(),
        slide_sombra(),
        slide_limitacoes(),
        slide_perguntas(),
    ]
    with PdfPages(out_path) as pdf:
        total = len(slides)
        for n, fig in enumerate(slides, start=1):
            if n > 1:  # título não numera
                _page_number(fig.axes[0], n - 1, total - 1)
            pdf.savefig(fig)
            plt.close(fig)
    return out_path


if __name__ == "__main__":
    path = gerar_apresentacao()
    print(f"apresentação salva em {path}")

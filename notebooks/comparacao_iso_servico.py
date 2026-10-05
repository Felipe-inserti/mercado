"""Gráficos e tabelas do relatório da Sprint 17 -- comparação iso-serviço,
célula lead_time=7/review_period=14 (Etapas 3.10-3.13).

Lógica de negócio nenhuma vive aqui (CLAUDE.md, seção 2) -- só leitura dos
resultados já produzidos por `python -m motor.experiments.iso_service` e
montagem dos gráficos/tabelas. Rodar depois que `results/iso_servico/`
já existir (ver `results/iso_servico/README.md`).

Ordem do relatório (pedida na Etapa 3.13; seção 6 acrescentada no
fechamento da Sprint 13, Etapa 3.16.4 -- "Fechamento", 2026-09-12):
    1. Premissas arbitradas
    2. Curva alpha x serviço x capital x decision_metric, dois braços
    3. Comparação iso-serviço contra o baseline
    4. Decomposição por item
    5. Guardrails de negócio (Sprint 13, Etapas 3.16-3.16.4)
    6. Limitações

NOTA (2026-09-12): as seções 1-4 (premissas, curvas, comparação
iso-serviço, decomposição por item) descrevem o braço 2/3 SEM as regras
de guarda -- `results/iso_servico/` não foi recalculado com guardrails
ativos, por decisão explícita (Etapa 3.16: "não recalcule a comparação
iso-serviço -- guardrails mudam a política e mudariam o decision_metric;
isso é um experimento declarado à parte"). A seção 5 reporta o custo das
guardas sobre a LISTA DE COMPRA (valor em R$ do pedido), não sobre o
decision_metric da simulação completa -- são medidas de naturezas
diferentes, não comparáveis linha a linha.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import polars as pl

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "results"
ISO_DIR = RESULTS_DIR / "iso_servico"

# Chaves de motor.assumptions.AssumptionsRegistry que são {valor, origem,
# justificativa, fonte} escalares -- as duas exceções (category_margin_pct,
# category_alpha) são dicts aninhados por categoria, tratadas à parte.
_ASSUMPTION_SCALAR_KEYS = (
    "lead_time_days",
    "review_period_days",
    "min_order_value",
    "min_order_units",
    "pack_multiple",
    "capital_cost_annual",
    "estoque_inicial",
    "default_alpha",
)


def _load_baseline() -> dict:
    return json.loads((ISO_DIR / "baseline_lt7_rp14.json").read_text())


def _load_assumptions() -> dict:
    manifest = json.loads(
        (
            RESULTS_DIR / "sensibilidade_dirigida" / "lt7_rp14" / "erp_baseline" / "manifest.json"
        ).read_text()
    )
    return manifest["assumptions"]


# --------------------------------------------------------------------------
# 1. Premissas arbitradas
# --------------------------------------------------------------------------


def imprimir_premissas() -> None:
    assumptions = _load_assumptions()
    print("=" * 78)
    print("1. PREMISSAS ARBITRADAS (motor.assumptions.AssumptionsRegistry)")
    print("=" * 78)
    linhas = []
    for key in _ASSUMPTION_SCALAR_KEYS:
        a = assumptions[key]
        linhas.append(
            {
                "premissa": key,
                "origem": a["origem"],
                "valor": a["valor"],
                "justificativa": a["justificativa"],
            }
        )
    tabela = pl.DataFrame(linhas)
    with pl.Config(tbl_cols=-1, tbl_width_chars=200, fmt_str_lengths=120):
        print(tabela)

    margem = assumptions["category_margin_pct"]
    medidas = [c for c, v in margem.items() if v["origem"] == "medido"]
    arbitradas = [c for c, v in margem.items() if v["origem"] != "medido"]
    print(
        f"\ncategory_margin_pct: {len(medidas)} categoria(s) MEDIDA(s) do documento de "
        f"negócio ({', '.join(medidas)}), {len(arbitradas)} ARBITRADA(s) por analogia "
        f"(faixa {min(v['valor'] for v in margem.values()):.0%}-"
        f"{max(v['valor'] for v in margem.values()):.0%})."
    )
    print(
        "category_alpha: INERTE -- chaves genéricas antigas que não correspondem a "
        "Item.category real; nenhuma política lê este dict (default_alpha sempre vence)."
    )


# --------------------------------------------------------------------------
# 2. Curva alpha x serviço x capital x decision_metric
# --------------------------------------------------------------------------


def grafico_curvas_alpha() -> Path:
    arm2 = pl.read_parquet(ISO_DIR / "arm2_alpha_grid.parquet").sort("alpha")
    arm3 = pl.read_parquet(ISO_DIR / "arm3_alpha_grid.parquet").sort("alpha")
    baseline = _load_baseline()

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    specs = [
        ("nivel_servico", "nível de serviço", axes[0]),
        ("decision_metric", "decision_metric", axes[1]),
        ("capital_medio_rs", "capital médio (R$, escala arbitrária)", axes[2]),
    ]
    for col, label, ax in specs:
        ax.plot(
            arm2["alpha"],
            arm2[col],
            "o-",
            label="braço 2 (estatístico, grade fina)",
            color="#2a78d6",
        )
        ax.plot(
            arm3["alpha"],
            arm3[col],
            "s-",
            label="braço 3 (quantile_gbm, grade segura)",
            color="#eb6834",
        )
        ax.axhline(baseline[col], linestyle="--", color="#1baf7a", label="baseline (calibrado)")
        ax.set_xlabel("alpha")
        ax.set_title(label)
        ax.grid(alpha=0.3)
    axes[0].legend(fontsize=8)
    fig.suptitle(
        "Célula lead_time=7 / review_period=14 -- braço 2 (16 pontos) vs. braço 3 (5 pontos)"
    )
    fig.tight_layout()
    out_path = ISO_DIR / "curvas_alpha.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"\ngráfico salvo em {out_path}")
    return out_path


# --------------------------------------------------------------------------
# 3. Comparação iso-serviço contra o baseline
# --------------------------------------------------------------------------


def tabela_comparacao_iso_servico() -> pl.DataFrame:
    baseline = _load_baseline()
    arm2 = pl.read_parquet(ISO_DIR / "arm2_alpha_grid.parquet")
    arm3 = pl.read_parquet(ISO_DIR / "arm3_alpha_grid.parquet")

    escolhido2 = arm2.filter(pl.col("alpha") == 0.66).row(0, named=True)
    escolhido3 = arm3.filter(pl.col("alpha") == 0.70).row(0, named=True)

    def linha(nome: str, d: dict) -> dict:
        return {
            "braco": nome,
            "alpha": d.get("alpha"),
            "nivel_servico": d["nivel_servico"],
            "distancia_alvo_pp": round((d["nivel_servico"] - baseline["nivel_servico"]) * 100, 3),
            "decision_metric": d["decision_metric"],
            "gap_vs_baseline_pct": round(
                (d["decision_metric"] / baseline["decision_metric"] - 1) * 100, 2
            ),
            "capital_medio_rs": d["capital_medio_rs"],
            "capital_vs_baseline_pct": round(
                (d["capital_medio_rs"] / baseline["capital_medio_rs"] - 1) * 100, 2
            ),
        }

    tabela = pl.DataFrame(
        [
            linha("baseline (erp_baseline)", baseline),
            linha("braço 2 (estatístico, iso-serviço)", escolhido2),
            linha("braço 3 (quantile_gbm, mais próximo)", escolhido3),
        ]
    )
    print("\n" + "=" * 78)
    print("3. COMPARAÇÃO ISO-SERVIÇO CONTRA O BASELINE")
    print("=" * 78)
    with pl.Config(tbl_cols=-1, tbl_width_chars=200):
        print(tabela)
    out_path = ISO_DIR / "comparacao_iso_servico.csv"
    tabela.write_csv(out_path)
    print(f"\ntabela salva em {out_path}")
    print(
        "\nCLASSIFICAÇÃO: o gap inverte -- no ponto de comparação correto, os dois "
        "braços entregam serviço equivalente ao baseline com menos capital empregado "
        "e mais margem líquida por real empregado (ver README.md para os vizinhos e "
        "a nota de granularidade desigual das duas grades)."
    )
    return tabela


# --------------------------------------------------------------------------
# 4. Decomposição por item
# --------------------------------------------------------------------------


def grafico_decomposicao_item() -> Path:
    item_table = pl.read_parquet(ISO_DIR / "item_decomposition_alpha066.parquet")
    resumo = json.loads((ISO_DIR / "resumo_decomposicao_alpha066.json").read_text())

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))
    ax1.scatter(
        item_table["pct_dias_com_venda"],
        item_table["decision_metric"],
        alpha=0.5,
        color="#2a78d6",
        s=18,
    )
    ax1.set_xlabel("% dias com venda (regularidade)")
    ax1.set_ylabel("decision_metric por item")
    ax1.set_title(f"Spearman = {resumo['spearman_decision_metric_vs_pct_dias_com_venda']:.3f}")
    ax1.grid(alpha=0.3)

    quartis = (
        item_table.with_columns(
            pl.col("pct_dias_com_venda")
            .qcut(4, labels=["Q1 menos regular", "Q2", "Q3", "Q4 mais regular"])
            .alias("quartil")
        )
        .group_by("quartil")
        .agg(pl.col("decision_metric").median().alias("decision_metric_mediano"))
        .sort("quartil")
    )
    ax2.bar(
        quartis["quartil"].to_list(), quartis["decision_metric_mediano"].to_list(), color="#eb6834"
    )
    ax2.set_ylabel("decision_metric mediano")
    ax2.set_title("Por quartil de regularidade de venda")
    ax2.tick_params(axis="x", labelrotation=15)
    ax2.grid(alpha=0.3, axis="y")

    fig.suptitle(
        f"Decomposição por item -- braço 2, alpha={resumo['alpha']} (iso-serviço), "
        f"n={resumo['n_itens']} itens"
    )
    fig.tight_layout()
    out_path = ISO_DIR / "decomposicao_item.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"\ngráfico salvo em {out_path}")
    print(
        "\nA vantagem do portfólio é DISTRIBUÍDA, não concentrada numa cauda de itens "
        "irregulares -- correlação fraca-moderada e positiva no sentido oposto ao "
        "esperado (itens mais regulares tendem a decision_metric um pouco maior). "
        "Isso CONTRARIA a tese de cauda irregular do documento de negócio original."
    )
    return out_path


# --------------------------------------------------------------------------
# 5. Guardrails de negócio (Sprint 13, Etapas 3.16-3.16.4)
# --------------------------------------------------------------------------
#
# As quatro regras vivem em `motor.policy.guardrails` e são integradas em
# `motor.reporting.purchase_list.generate_purchase_list` -- não existiam
# antes da Sprint 13 (ver Emenda de Sprint 17 no CLAUDE.md: `Params.guardrails`
# nunca tinha sido lido por nenhuma função de produção). O texto abaixo é
# um RELATO do que foi implementado e medido, não um recálculo -- os
# números vêm da geração real da lista de compra em duas datas de decisão
# (`results/lista_compra/2017-03-06/` e o cenário de estresse declarado em
# `results/lista_compra/_estresse_2017-03-20/`, este último não versionado
# e não substituindo a lista principal).

GUARDRAILS_RESUMO = (
    (
        "As 4 regras (Sprint 3, seção 9 do CLAUDE.md) estão implementadas e testadas "
        "isoladamente antes da integração: teto de cobertura, limite de variação sobre "
        "a compra histórica (sinaliza, não corta), item novo (quantidade fixa = "
        "mediana da categoria, nunca decidida pelo modelo) e restrição de caixa por "
        "margem com piso de 60% por categoria."
    ),
    (
        "Custo real do seguro: as guardas juntas reduzem o valor da lista de compra "
        "em cerca de -7,0% frente à sugestão bruta da política (braço 2), na data de "
        "decisão principal -- não os -64,5% medidos com o teto de cobertura "
        "mal-parametrizado (ver item seguinte). É o preço do seguro, não uma "
        "regressão: quantificá-lo é informação de negócio, não um defeito a corrigir."
    ),
    (
        "Achado por trás do -64,5%: os tetos de cobertura (7/14/30/45 dias por "
        "família) são tetos de VALIDADE física, corretos como tal -- o bug era "
        "aplicá-los sem piso na janela de risco (lead_time + review_period = 21 dias "
        "nesta célula). Corrigido para cap_efetivo = max(validade, janela_de_risco); "
        "quando a janela vence a validade, a regra agora REGISTRA o conflito "
        "('teto de validade menor que a janela de risco; ciclo de compra incompatível "
        "com a família') em vez de cortar tudo pela validade sozinha. Depois da "
        "correção: teto de cobertura ainda dispara em 161/275 itens (58,5%) na data "
        "principal -- concentrado nas famílias onde risco > validade (perecível "
        "fresco, giro rápido), exatamente as duas famílias fisicamente incompatíveis "
        "com review_period=14 -- mas o VALOR cortado caiu de -64,5% para -7,0%: a "
        "maioria dos disparos já operava dentro da janela de risco normal, só era "
        "contada como corte pelo cálculo antigo sem piso."
    ),
    (
        "Restrição de caixa -- concentração do corte por margem pura (achado antes "
        "do piso, orçamento de R$200k/semana, contaminado pelo bug de escala abaixo): "
        "3 categorias zeradas por inteiro (GROCERY II, MEATS, SEAFOOD) e 5 cortadas "
        "em 75-95% (DAIRY, EGGS, GROCERY I, POULTRY, PRODUCE) -- todas de margem "
        "14-20%, a faixa mais baixa do portfólio. Um corte por margem pura, sem piso, "
        "zera categorias inteiras de baixa margem mesmo quando são categorias de "
        "presença obrigatória de gôndola -- nenhum dono de loja aceitaria essa lista."
    ),
    (
        "Piso de 60% por categoria (decisão de negócio, não otimização): nenhuma "
        "categoria cai abaixo de 60% do valor originalmente sugerido, corte por "
        "margem opera só sobre os 40% acima do piso. Verificado num cenário de "
        "estresse declarado (orçamento deliberadamente apertado, ~R$300k/ciclo, "
        "contra necessidade real da ordem de R$450-500k): a regra disparou 106 "
        "vezes -- 46 itens protegidos pelo piso em 5 categorias (DAIRY, EGGS, MEATS, "
        "POULTRY, SEAFOOD) e 60 itens cortados acima do piso em 11 categorias, sem "
        "nenhum caso de 'piso estoura o orçamento' (a soma dos pisos coube dentro do "
        "orçamento apertado). Na data de decisão principal a restrição de caixa não "
        "chega a disparar (necessidade real ~R$462k contra orçamento de R$500k/ciclo) "
        "-- 'parametrização não alcançada nesta data', não regra morta."
    ),
    (
        "Bug de escala do orçamento (achado e corrigido nesta sprint, não do usuário): "
        "`weekly_budget_rs` estava sendo usado direto como orçamento do ciclo de 14 "
        "dias, sem multiplicar por review_period_days/7=2 -- toda medição de "
        "restrição de caixa anterior a essa correção (Etapas 3.16, 3.16.2 e o início "
        "de 3.16.3) foi feita contra METADE do orçamento pretendido. Corrigido via "
        "`_cycle_budget_rs()`, com o bug documentado na própria docstring da função."
    ),
)


def imprimir_guardrails_sprint13() -> None:
    print("\n" + "=" * 78)
    print("5. GUARDRAILS DE NEGÓCIO (SPRINT 13, ETAPAS 3.16-3.16.4)")
    print("=" * 78)
    for i, texto in enumerate(GUARDRAILS_RESUMO, start=1):
        print(f"{i}. {texto}\n")


# --------------------------------------------------------------------------
# 6. Limitações
# --------------------------------------------------------------------------

LIMITACOES = (
    "Validade restrita a UMA célula (lead_time=7, review_period=14). Generalizar "
    "para outras combinações de lead_time/review_period é hipótese, não resultado.",
    "Determinismo: manifesto reprodutível (seed=42, POLARS_MAX_THREADS embutido em "
    "cada ponto novo desta etapa); eventos brutos têm ruído de ordem de ponto "
    "flutuante em nível de ULP (13a-14a casa) dependente da contagem de threads -- "
    "não afeta métricas agregadas arredondadas (Sprint 16.5, Etapas 3.7/3.9).",
    "Aquecimento (warmup_days) verificado mas não blindado por teste de regressão "
    "automatizado nesta etapa.",
    "Defeito de instrumentação do giro_anualizado (Sprint 16.5, Etapa 1) diagnosticado "
    "mas não reaberto aqui -- decision_metric, não giro, é a métrica de decisão.",
    "Granularidade desigual das grades de alpha: braço 2 (16 pontos, distância ao "
    "alvo de 0,018 p.p.) vs. braço 3 (5 pontos, 0,411 p.p.) -- braço 2 x braço 3 "
    "entre si é indicativo, não conclusivo; cada braço contra o baseline é sólido.",
    "Ausência de saldo de estoque no dado público (Favorita) -- premissa herdada de "
    "todo o projeto (CLAUDE.md secao 4), não específica desta etapa.",
    "Spearman 0,275 (decision_metric x %dias-com-venda) contraria a tese de cauda "
    "irregular do documento de negócio -- a vantagem medida é distribuída pelo "
    "portfólio, com leve viés a favor de itens MAIS regulares, não menos. O "
    "argumento de venda precisa mudar para o que foi de fato medido: mesmo serviço, "
    "menos capital parado -- revisar o documento de negócio depois deste notebook.",
    "review_period é GLOBAL, não por fornecedor (débito de arquitetura, Etapa "
    "3.16.2) -- o teto de cobertura só é uma guarda ativa quando a janela de risco "
    "(lead_time + review_period) é menor que a validade da família; em perecível "
    "fresco e giro rápido, review_period=14 já excede a validade sozinho, tornando o "
    "teto estruturalmente inoperante nessas famílias. Proteção real exigiria "
    "review_period por fornecedor, que o simulador não suporta -- não é bug, é "
    "escopo não coberto.",
    "Restrição de caixa não revalida pedido mínimo do fornecedor depois de cortar "
    "(Etapa 3.14/3.16) -- um item cortado pode deixar o pedido residual do fornecedor "
    "abaixo do mínimo, e isso não é recalculado; a lista sinaliza o corte, mas não "
    "fecha esse ciclo com `apply_supplier_constraints` de novo.",
    "Piso de 60% por categoria na restrição de caixa é ARBITRADO e declarado como "
    "tal (Etapa 3.16.4, critério: preservar presença de gôndola cortando fundo o "
    "suficiente para a regra ainda ter efeito real) -- não é resultado de otimização "
    "nem foi calibrado contra dado de ruptura real por ausência de produto.",
    "Duas guardas de `guardrails.py` (Sprint 3, seção 9) não foram implementadas: "
    "promoção prevista (o canônico só carrega on_promo HISTÓRICO, nunca planejado) e "
    "item âncora (Item.is_anchor é 100% nulo no canônico -- exigiria análise de "
    "cesta fora do escopo desta versão). Declaradas com motivo em "
    "`NOT_IMPLEMENTED_GUARDRAILS`, mesmo tratamento do gap de `GuardrailsParams`.",
)


def imprimir_limitacoes() -> None:
    print("\n" + "=" * 78)
    print("6. LIMITAÇÕES")
    print("=" * 78)
    for i, texto in enumerate(LIMITACOES, start=1):
        print(f"{i}. {texto}\n")


def main() -> None:
    imprimir_premissas()
    grafico_curvas_alpha()
    tabela_comparacao_iso_servico()
    grafico_decomposicao_item()
    imprimir_guardrails_sprint13()
    imprimir_limitacoes()


if __name__ == "__main__":
    main()

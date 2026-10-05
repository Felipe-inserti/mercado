"""Gráfico e tabela do relatório final da Sprint 15: comparação dos três
braços (erp_baseline, estatistico_basestock, quantile_gbm_basestock).

Lógica de negócio nenhuma vive aqui (CLAUDE.md, seção 2) -- só leitura dos
resultados já produzidos por `python -m motor.experiments.run --arm <nome>`
(um `results/<arm>/manifest.json` + `events.parquet` por braço) e a
montagem do gráfico/tabela do relatório. Rodar depois que os três braços já
tiverem sido executados.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import polars as pl

from motor.config import load_params
from motor.metrics.financial import build_item_economics, daily_net_margin

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "results"
ARMS = ["erp_baseline", "estatistico_basestock", "quantile_gbm_basestock"]
ARM_LABELS = {
    "erp_baseline": "Braço 1 -- ERP baseline",
    "estatistico_basestock": "Braço 2 -- estatístico + nível-alvo",
    "quantile_gbm_basestock": "Braço 3 -- LightGBM quantílico + nível-alvo",
}


def _load_manifest(arm: str) -> dict:
    return json.loads((RESULTS_DIR / arm / "manifest.json").read_text())


def main() -> None:
    params = load_params(REPO_ROOT / "config" / "params.yaml")
    items = pl.read_parquet(Path(params.data.canonical_dir) / "items.parquet")
    item_economics = build_item_economics(
        items.select("item_id", "category"),
        category_margin_pct=params.economics.category_margin_pct,
        default_margin_pct=params.economics.default_margin_pct,
        uniform_unit_price=params.economics.uniform_unit_price,
    )

    manifests = {arm: _load_manifest(arm) for arm in ARMS}
    evaluation_start = manifests[ARMS[0]]["simulation_window"]["evaluation_start"]

    fig, ax = plt.subplots(figsize=(10, 6))
    for arm in ARMS:
        events = pl.read_parquet(RESULTS_DIR / arm / "events.parquet")
        daily = daily_net_margin(
            events,
            item_economics,
            evaluation_start=date.fromisoformat(evaluation_start),
        ).sort("day")
        cumulative = daily.with_columns(pl.col("net_margin_rs").cum_sum().alias("cumulativo_rs"))
        ax.plot(
            cumulative["day"].to_list(),
            cumulative["cumulativo_rs"].to_list(),
            label=ARM_LABELS[arm],
            linewidth=2,
        )

    ax.set_title("R$ acumulado (margem realizada - perda), período pós-warmup")
    ax.set_xlabel("data")
    ax.set_ylabel("R$ acumulado (escala arbitrária -- ver motor.metrics.financial)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    out_path = RESULTS_DIR / "comparacao_bracos.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"gráfico salvo em {out_path}")

    print(
        "\nmétricas lado a lado, ordenadas por decision_metric "
        "(margem líquida de perda / capital médio):"
    )
    rows = []
    for arm in ARMS:
        portfolio = manifests[arm]["results"]["portfolio"]
        rows.append({"braco": arm, **portfolio})
    tabela = pl.DataFrame(rows).sort("decision_metric", descending=True)
    with pl.Config(tbl_cols=-1, tbl_width_chars=200):
        print(tabela)

    tabela.write_csv(RESULTS_DIR / "comparacao_bracos_metricas.csv")
    print(f"\ntabela salva em {RESULTS_DIR / 'comparacao_bracos_metricas.csv'}")


if __name__ == "__main__":
    main()

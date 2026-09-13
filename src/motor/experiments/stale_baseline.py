"""Sprint 18 (Fase 4, Etapa 4.1) -- o braço que representa o cliente.

O que existe num supermercado de verdade não é o baseline recalibrado que
`results/sensibilidade_dirigida/lt7_rp14/erp_baseline/` mede -- é um ERP
com `factor`/`min_order_units` fixos, calibrados uma vez (quando o
lead_time do fornecedor era outro) e nunca mais revisados. Este módulo
mede exatamente essa situação: calibra `ErpBaselinePolicy` numa célula
(lead_time CURTO, o que o fornecedor tinha quando alguém setou o
mínimo/máximo do ERP) e aplica esse `factor` SEM recalibrar na célula real
de hoje (`lead_time_days=7`, `review_period_days=14`).

NENHUM CAMINHO NOVO DE EXECUÇÃO -- reusa por inteiro a máquina de
`motor.experiments.sensitivity` (Sprint 16.5) e `motor.experiments.run`
(Sprint 9): `build_directed_cell_params`/`cell_suppliers` para montar a
célula-alvo com um `factor` que NÃO foi calibrado nela, e
`run_arm_and_save` para gravar o resultado com o mesmo manifesto
autossuficiente de sempre. A única escolha desta sprint é NÃO chamar
`calibrate_directed_cell` para a célula-alvo -- usar o `factor` de OUTRA
célula, já calibrado e já em disco.

DUAS MAGNITUDES DE DESCASAMENTO -- arbitradas, declaradas como tal
--------------------------------------------------------------------
Não existe UMA distância "certa" entre o lead time de quando o ERP foi
calibrado e o lead time de hoje -- é uma escolha de cenário, não uma
medição. Por isso duas magnitudes, não uma:

    - `calibrado_lt3_rp7`: factor calibrado em lead_time=3/review_period=7
      (`results/sensibilidade_dirigida/lt3_rp7/erp_baseline/`) -- o
      fornecedor entregava em 3 dias.
    - `calibrado_lt5_rp7`: factor calibrado em lead_time=5/review_period=7
      (`results/sensibilidade_dirigida/lt5_rp7/erp_baseline/`) -- descasamento
      menor, mesma direção.

Os dois já existem em disco (Sprint 16.5) -- REUSADOS, não recalculados
aqui (mesma economia de computação de `motor.experiments.iso_service`
reusando a calibração de lt7_rp14). `review_period_days=7` nas duas fontes
é deliberado: mantém UM eixo de descasamento (lead_time), não dois
simultâneos -- mais fácil de atribuir a queda de serviço à causa certa.

OS OUTROS DOIS PONTOS DA TABELA FINAL NÃO SÃO RECALCULADOS AQUI
------------------------------------------------------------------
    - baseline recalibrado em lt=7/rp=14:
      `results/sensibilidade_dirigida/lt7_rp14/erp_baseline/manifest.json`
    - motor (braço 2, alpha iso-serviço 0.66) em lt=7/rp=14:
      `results/iso_servico/arm2_alpha_grid.parquet` (Sprint 17)

ACHADO A OBSERVAR, NÃO A CORRIGIR AQUI (fora de escopo desta sprint):
`motor.experiments.run._BASELINE_COVERAGE_CONTEXT` é um texto module-level
CONSTANTE, embutido sem recálculo em `erp_baseline_calibration.coverage_context`
de TODO manifesto de TODA célula (achado ao investigar esta sprint: o texto
fala em "9.52 dos 10 dias da janela de risco", número que só bate para a
célula lt3/rp7 -- aparece idêntico, e por isso errado, nos manifestos de
lt5_rp7, lt7_rp14 e em qualquer manifesto novo gravado por este módulo).
`coverage_days_implied` (o número, não o texto) é recalculado corretamente
em toda célula -- é só o texto narrativo que está preso na primeira célula
em que foi escrito. Este módulo NUNCA cita `coverage_context` -- a razão de
cobertura da célula-alvo é recomputada aqui, do zero, contra o
`review_period_days` REAL da célula-alvo (`_coverage_ratio`).

CLI:
    python -m motor.experiments.stale_baseline --run-all
        roda as duas magnitudes (grava manifesto em
        results/baseline_desatualizado/<label>/erp_baseline/manifest.json)
        e imprime + grava a tabela comparativa.
    python -m motor.experiments.stale_baseline --report-only
        só remonta a tabela comparativa a partir dos manifestos já em disco
        (nenhuma execução nova) -- idempotente, útil pra reimprimir sem
        recustar nada.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import polars as pl

from motor.config import Params, load_params
from motor.experiments.iso_service import (
    ARM2_CHOSEN_ALPHA,
    CELL_LEAD_TIME_DAYS,
    CELL_REVIEW_PERIOD_DAYS,
    CanonicalTables,
    cell_suppliers,
    load_canonical_tables,
)
from motor.experiments.run import RunManifest, run_arm_and_save
from motor.experiments.sensitivity import build_directed_cell_params

RESULTS_DIR: Final[Path] = Path("results")
SENSITIVITY_DIR: Final[Path] = RESULTS_DIR / "sensibilidade_dirigida"
ISO_SERVICE_DIR: Final[Path] = RESULTS_DIR / "iso_servico"
STALE_BASELINE_DIR: Final[Path] = RESULTS_DIR / "baseline_desatualizado"

TARGET_SERVICE_LEVEL: Final[float] = 0.95
"""Meta de calibração do braço 1 em toda célula
(motor.experiments.sensitivity._ERP_TARGET_SERVICE_LEVEL) -- repetida aqui
como constante de referência, não lida em runtime."""

STALE_SOURCES: Final[dict[str, tuple[int, int]]] = {
    "calibrado_lt3_rp7": (3, 7),
    "calibrado_lt5_rp7": (5, 7),
}
"""label -> (lead_time_days, review_period_days) da célula ONDE o factor foi
calibrado -- não da célula onde é aplicado (sempre lt=7/rp=14, ver
CELL_LEAD_TIME_DAYS/CELL_REVIEW_PERIOD_DAYS)."""


@dataclass(frozen=True)
class StaleCalibrationSource:
    """O que foi lido da célula-fonte -- nunca recalculado, só citado."""

    label: str
    source_lead_time_days: int
    source_review_period_days: int
    source_manifest_path: Path
    factor: float
    min_order_units: float


def _source_manifest_path(lead_time_days: int, review_period_days: int) -> Path:
    return (
        SENSITIVITY_DIR
        / f"lt{lead_time_days}_rp{review_period_days}"
        / "erp_baseline"
        / "manifest.json"
    )


def load_stale_calibration(label: str) -> StaleCalibrationSource:
    """Lê `factor`/`min_order_units` já calibrados na célula-fonte de
    `label` (`STALE_SOURCES`) -- só os campos NUMÉRICOS de
    `erp_baseline_calibration`; nunca `coverage_context` (ver docstring do
    módulo, é texto preso na primeira célula em que foi escrito)."""
    source_lt, source_rp = STALE_SOURCES[label]
    path = _source_manifest_path(source_lt, source_rp)
    manifest = json.loads(path.read_text())
    calib = manifest["erp_baseline_calibration"]
    return StaleCalibrationSource(
        label=label,
        source_lead_time_days=source_lt,
        source_review_period_days=source_rp,
        source_manifest_path=path,
        factor=calib["factor"],
        min_order_units=calib["min_order_units"],
    )


def run_stale_baseline(
    label: str,
    *,
    base_params: Params,
    tables: CanonicalTables,
    force: bool = False,
) -> RunManifest:
    """Roda o braço `erp_baseline` em `CELL_LEAD_TIME_DAYS`/`CELL_REVIEW_PERIOD_DAYS`
    (lt=7/rp=14, a célula real de hoje) com o `factor`/`min_order_units`
    calibrados em OUTRA célula (`label`, `STALE_SOURCES`) -- sem recalibrar.

    Único ponto que difere de uma célula normal da varredura dirigida: o
    `factor` não vem de `calibrate_directed_cell` para ESTA célula, vem de
    `load_stale_calibration` para a célula-fonte."""
    source = load_stale_calibration(label)
    cell_params = build_directed_cell_params(
        base_params,
        lead_time_days=CELL_LEAD_TIME_DAYS,
        review_period_days=CELL_REVIEW_PERIOD_DAYS,
        erp_factor=source.factor,
        erp_min_order_units=source.min_order_units,
    )
    suppliers = cell_suppliers(tables.suppliers)
    results_dir = STALE_BASELINE_DIR / label
    return run_arm_and_save(
        "erp_baseline",
        cell_params,
        sales=tables.sales,
        items=tables.items,
        suppliers=suppliers,
        stock=tables.stock,
        subset_cache_path=tables.subset_cache_path,
        canonical_dir=Path(base_params.data.canonical_dir),
        results_dir=results_dir,
        force=force,
    )


# --------------------------------------------------------------------------
# Tabela comparativa
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioMetrics:
    cenario: str
    origem: str
    factor: float | None
    min_order_units: float | None
    nivel_servico: float
    decision_metric: float
    capital_medio_rs: float
    coverage_days_implied_na_celula_alvo: float | None
    """`factor x moving_average_days`, recomputado aqui contra a célula-alvo
    (lt=7/rp=14, janela de risco 21 dias) -- NUNCA o `coverage_context` do
    manifesto (preso na célula-fonte, ver docstring do módulo). `None` para
    o motor (braço 2): não usa `factor`, não tem coverage_days_implied."""


def _coverage_ratio(coverage_days_implied: float, *, review_period_days: int) -> float:
    risk_window_days = CELL_LEAD_TIME_DAYS + review_period_days
    return coverage_days_implied / risk_window_days


def load_baseline_recalibrado() -> ScenarioMetrics:
    path = _source_manifest_path(CELL_LEAD_TIME_DAYS, CELL_REVIEW_PERIOD_DAYS)
    manifest = json.loads(path.read_text())
    calib = manifest["erp_baseline_calibration"]
    portfolio = manifest["results"]["portfolio"]
    coverage_days_implied = calib["factor"] * calib["moving_average_weeks"] * 7
    return ScenarioMetrics(
        cenario="baseline recalibrado (lt=7/rp=14)",
        origem=str(path),
        factor=calib["factor"],
        min_order_units=calib["min_order_units"],
        nivel_servico=portfolio["nivel_servico"],
        decision_metric=portfolio["decision_metric"],
        capital_medio_rs=portfolio["capital_medio_rs"],
        coverage_days_implied_na_celula_alvo=coverage_days_implied,
    )


def load_motor_iso_servico() -> ScenarioMetrics:
    grid = pl.read_parquet(ISO_SERVICE_DIR / "arm2_alpha_grid.parquet")
    row = grid.filter(pl.col("alpha") == ARM2_CHOSEN_ALPHA).row(0, named=True)
    return ScenarioMetrics(
        cenario=f"motor (braço 2, alpha={ARM2_CHOSEN_ALPHA} iso-serviço)",
        origem=str(ISO_SERVICE_DIR / "arm2_alpha_grid.parquet"),
        factor=None,
        min_order_units=None,
        nivel_servico=row["nivel_servico"],
        decision_metric=row["decision_metric"],
        capital_medio_rs=row["capital_medio_rs"],
        coverage_days_implied_na_celula_alvo=None,
    )


def load_stale_scenario(label: str) -> ScenarioMetrics:
    source = load_stale_calibration(label)
    manifest_path = STALE_BASELINE_DIR / label / "erp_baseline" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    portfolio = manifest["results"]["portfolio"]
    coverage_days_implied = (
        source.factor * manifest["erp_baseline_calibration"]["moving_average_weeks"] * 7
    )
    return ScenarioMetrics(
        cenario=(
            f"baseline desatualizado ({label}: factor calibrado em "
            f"lt={source.source_lead_time_days}/rp={source.source_review_period_days}, "
            f"aplicado sem recalibrar em lt={CELL_LEAD_TIME_DAYS}/rp={CELL_REVIEW_PERIOD_DAYS})"
        ),
        origem=str(manifest_path),
        factor=source.factor,
        min_order_units=source.min_order_units,
        nivel_servico=portfolio["nivel_servico"],
        decision_metric=portfolio["decision_metric"],
        capital_medio_rs=portfolio["capital_medio_rs"],
        coverage_days_implied_na_celula_alvo=coverage_days_implied,
    )


def build_comparison_table(stale_labels: tuple[str, ...] = tuple(STALE_SOURCES)) -> pl.DataFrame:
    baseline = load_baseline_recalibrado()
    motor = load_motor_iso_servico()
    stale_scenarios = [load_stale_scenario(label) for label in stale_labels]

    rows = [*stale_scenarios, baseline, motor]

    def linha(s: ScenarioMetrics) -> dict[str, object]:
        return {
            "cenario": s.cenario,
            "factor": s.factor,
            "min_order_units": s.min_order_units,
            "cobertura_implicada_dias": s.coverage_days_implied_na_celula_alvo,
            "cobertura_vs_janela_de_risco": (
                round(
                    _coverage_ratio(
                        s.coverage_days_implied_na_celula_alvo,
                        review_period_days=CELL_REVIEW_PERIOD_DAYS,
                    ),
                    3,
                )
                if s.coverage_days_implied_na_celula_alvo is not None
                else None
            ),
            "nivel_servico": round(s.nivel_servico, 6),
            "gap_servico_vs_meta_pp": round((TARGET_SERVICE_LEVEL - s.nivel_servico) * 100, 3),
            "gap_servico_vs_baseline_recalibrado_pp": round(
                (baseline.nivel_servico - s.nivel_servico) * 100, 3
            ),
            "decision_metric": round(s.decision_metric, 6),
            "capital_medio_rs": round(s.capital_medio_rs, 2),
            "capital_vs_baseline_recalibrado_pct": round(
                (s.capital_medio_rs / baseline.capital_medio_rs - 1) * 100, 2
            ),
        }

    return pl.DataFrame([linha(s) for s in rows])


def decomposicao_bruta_decision_metric(stale_label: str) -> dict[str, float]:
    """Diferença sequencial de `decision_metric` `stale -> recalibrado -> motor`
    -- aritmética correta (os dois passos somam o total), mas NÃO É a
    resposta de "quanto do ganho vem do modelo" quando `stale` não alcança
    a meta de serviço (é sempre o caso medido: ver `decomposicao_gap_servico`).

    Por quê: `decision_metric` é margem realizada menos perda POR REAL DE
    CAPITAL EMPREGADO -- uma razão. Um baseline que sub-abastece severamente
    (nivel_servico ~60-66% medido nesta etapa, contra meta de 95%) reduz o
    CAPITAL empregado tanto que a razão sobe, mesmo perdendo ~R$2 milhões de
    margem em ruptura -- o denominador caiu mais rápido que o numerador. Um
    `decision_metric` MAIOR aqui não significa uma política melhor; significa
    uma política que não guarda estoque suficiente pra vender. Comparar
    `decision_metric` bruto entre pontos de serviço tão diferentes é
    exatamente o erro que a metodologia iso-serviço deste projeto
    (`motor.experiments.iso_service`) existe para evitar -- esta função
    devolve o número por transparência (ele está na tabela), não como
    argumento de negócio. Use `decomposicao_gap_servico` para a pergunta
    real."""
    stale = load_stale_scenario(stale_label)
    baseline = load_baseline_recalibrado()
    motor = load_motor_iso_servico()

    ganho_total = motor.decision_metric - stale.decision_metric
    ganho_recalibracao = baseline.decision_metric - stale.decision_metric
    ganho_modelo = motor.decision_metric - baseline.decision_metric
    return {
        "ganho_total": ganho_total,
        "ganho_recalibracao": ganho_recalibracao,
        "ganho_modelo": ganho_modelo,
    }


def decomposicao_gap_servico(stale_label: str) -> dict[str, float]:
    """A decomposição VÁLIDA de "quanto vem de recalibrar, quanto vem do
    modelo" quando o baseline desatualizado não alcança a meta de serviço:
    em pontos de PP de nível de serviço, não em `decision_metric`.

    `motor` roda em alpha iso-serviço -- por construção, ele é calibrado
    para bater o nível de serviço do BASELINE RECALIBRADO, não para fechar
    mais gap de serviço sozinho (Sprint 17). Logo o modelo fecha ~0 p.p. de
    gap de serviço adicional; TODO o resgate de serviço (de ~60-66% para
    ~94,85%) vem de recalibrar o `factor` na célula certa, sem tocar no
    modelo. A contribuição do modelo aparece DEPOIS disso, no MESMO nível
    de serviço: capital/decision_metric (Sprint 17, ver
    `capital_vs_baseline_recalibrado_pct` da linha do motor na tabela --
    -2,8% de capital, +2,9% de decision_metric)."""
    stale = load_stale_scenario(stale_label)
    baseline = load_baseline_recalibrado()
    motor = load_motor_iso_servico()

    gap_total_pp = (baseline.nivel_servico - stale.nivel_servico) * 100
    fechado_por_recalibracao_pp = gap_total_pp
    fechado_pelo_modelo_pp = (motor.nivel_servico - baseline.nivel_servico) * 100
    return {
        "gap_total_pp": gap_total_pp,
        "fechado_por_recalibracao_pp": fechado_por_recalibracao_pp,
        "fechado_pelo_modelo_pp": fechado_pelo_modelo_pp,
        "pct_fechado_por_recalibracao": (
            (fechado_por_recalibracao_pp / gap_total_pp * 100)
            if gap_total_pp != 0
            else float("nan")
        ),
    }


def imprimir_relatorio(stale_labels: tuple[str, ...] = tuple(STALE_SOURCES)) -> pl.DataFrame:
    table = build_comparison_table(stale_labels)
    print("=" * 100)
    print(
        "SPRINT 18 -- O BRAÇO QUE REPRESENTA O CLIENTE "
        "(baseline desatualizado x recalibrado x motor)"
    )
    print("=" * 100)
    with pl.Config(tbl_cols=-1, tbl_width_chars=240, fmt_str_lengths=200):
        print(table)

    baseline = load_baseline_recalibrado()
    for label in stale_labels:
        stale = load_stale_scenario(label)
        if stale.nivel_servico < TARGET_SERVICE_LEVEL:
            gap_vs_meta_pp = (TARGET_SERVICE_LEVEL - stale.nivel_servico) * 100
            gap_vs_baseline_pp = (baseline.nivel_servico - stale.nivel_servico) * 100
            print(
                f"\nGAP DE SERVIÇO -- {label}: nivel_servico={stale.nivel_servico:.4f}, "
                f"{gap_vs_meta_pp:.2f} p.p. abaixo da meta ({TARGET_SERVICE_LEVEL:.0%}) e "
                f"{gap_vs_baseline_pp:.2f} p.p. abaixo do baseline recalibrado NA MESMA CÉLULA "
                "-- o argumento aqui não é só 'menos capital', é 'mais serviço E menos capital'."
            )
        bruta = decomposicao_bruta_decision_metric(label)
        motor_decision_metric = load_motor_iso_servico().decision_metric
        if stale.nivel_servico < baseline.nivel_servico - 0.02:
            print(
                f"\nAVISO METODOLÓGICO ({label}): decision_metric do baseline desatualizado "
                f"({stale.decision_metric:.2f}) é MAIOR que o do baseline recalibrado "
                f"({baseline.decision_metric:.2f}) e o do motor ({motor_decision_metric:.2f}) "
                "-- isto NÃO é vantagem do baseline desatualizado. decision_metric é margem "
                "realizada por real de capital empregado: sub-abastecer na proporção medida "
                "aqui derruba o capital empregado mais rápido do que derruba a margem "
                "realizada, inflando a razão às custas de vender menos. Comparar decision_metric "
                "bruto entre pontos de serviço tão diferentes é o erro que a metodologia "
                "iso-serviço existe para evitar -- o número bruto "
                f"(diferença sequencial: {bruta}) fica registrado por transparência, não como "
                "argumento de negócio."
            )
        gap = decomposicao_gap_servico(label)
        print(
            f"\nDECOMPOSIÇÃO VÁLIDA ({label}) -- em pontos de nível de serviço, não em "
            f"decision_metric: dos {gap['gap_total_pp']:.2f} p.p. que separam o baseline "
            "desatualizado do baseline recalibrado, "
            f"{gap['pct_fechado_por_recalibracao']:.1f}% fecham SÓ COM RECALIBRAR (sem tocar "
            f"no modelo); o modelo (rodando em alpha iso-serviço, calibrado para bater o MESMO "
            f"nível do baseline recalibrado, não para fechar mais gap sozinho) fecha "
            f"{gap['fechado_pelo_modelo_pp']:.3f} p.p. adicionais -- essencialmente zero, por "
            "construção. A contribuição real do modelo aparece DEPOIS do resgate de serviço, "
            "no MESMO nível: ver capital_vs_baseline_recalibrado_pct da linha do motor na "
            "tabela acima (-2,8% de capital, decision_metric +2,9%, Sprint 17)."
        )

    out_csv = STALE_BASELINE_DIR / "comparacao.csv"
    out_json = STALE_BASELINE_DIR / "resumo.json"
    STALE_BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    table.write_csv(out_csv)
    resumo = {
        "premissa_arbitrada": (
            "A magnitude do descasamento entre a célula onde o ERP do cliente foi calibrado e a "
            "célula real de hoje (lt=7/rp=14) é ARBITRADA -- duas magnitudes rodadas "
            f"({', '.join(stale_labels)}) para mostrar sensibilidade, não um único número "
            "conveniente. Não existe medição do lead_time histórico real de nenhum fornecedor "
            "do cliente nesta etapa."
        ),
        "aviso_metodologico": (
            "decision_metric bruto do baseline desatualizado NÃO é comparável ao do baseline "
            "recalibrado/motor -- ver decomposicao_bruta_decision_metric: um baseline "
            "severamente sub-abastecido derruba o capital empregado (denominador) mais rápido "
            "do que derruba a margem realizada, inflando a razão às custas de vender menos. A "
            "decomposição de negócio válida é a de nível de serviço (decomposicao_gap_servico)."
        ),
        "meta_servico": TARGET_SERVICE_LEVEL,
        "celula_alvo": {
            "lead_time_days": CELL_LEAD_TIME_DAYS,
            "review_period_days": CELL_REVIEW_PERIOD_DAYS,
        },
        "decomposicao_gap_servico_pp": {
            label: decomposicao_gap_servico(label) for label in stale_labels
        },
        "decomposicao_bruta_decision_metric_nao_interpretavel_como_ganho": {
            label: decomposicao_bruta_decision_metric(label) for label in stale_labels
        },
        "fontes": {
            "baseline_recalibrado": str(
                _source_manifest_path(CELL_LEAD_TIME_DAYS, CELL_REVIEW_PERIOD_DAYS)
            ),
            "motor": str(ISO_SERVICE_DIR / "arm2_alpha_grid.parquet"),
            **{
                label: str(STALE_BASELINE_DIR / label / "erp_baseline" / "manifest.json")
                for label in stale_labels
            },
        },
    }
    out_json.write_text(json.dumps(resumo, indent=2, ensure_ascii=False, sort_keys=True))
    print(f"\ntabela salva em {out_csv}\nresumo salvo em {out_json}")
    return table


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--params", type=Path, default=Path("config/params.yaml"))
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-all", action="store_true", help="roda as duas magnitudes e reporta")
    group.add_argument("--report-only", action="store_true", help="só remonta a tabela, sem rodar")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    if args.run_all:
        base_params = load_params(args.params)
        tables = load_canonical_tables(base_params)
        for label in STALE_SOURCES:
            t0 = time.perf_counter()
            manifest = run_stale_baseline(
                label, base_params=base_params, tables=tables, force=args.force
            )
            dt = time.perf_counter() - t0
            print(
                f"[ok] {label}: decision_metric={manifest.results.portfolio.decision_metric} "
                f"nivel_servico={manifest.results.portfolio.nivel_servico} ({dt:.1f}s)"
            )

    imprimir_relatorio()


if __name__ == "__main__":
    main()

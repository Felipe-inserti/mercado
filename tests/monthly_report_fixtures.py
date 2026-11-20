"""Arquivos sintéticos mínimos para o relatório mensal, todos no diretório do teste."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import polars as pl
import pytest
import yaml

from motor.config import load_params
from motor.experiments import monthly_report as monthly
from motor.experiments import stale_baseline as stale
from tests.purchase_list_fixtures import PARAMS_PATH


@dataclass(frozen=True)
class MonthlyReportScenario:
    root: Path
    params_path: Path
    sensitivity_dir: Path
    iso_dir: Path
    stale_dir: Path


def _write_manifest(
    path: Path,
    *,
    factor: float,
    service: float,
    capital: float,
    decision_metric: float,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "erp_baseline_calibration": {
                    "factor": factor,
                    "min_order_units": 0.0,
                    "moving_average_weeks": 4,
                },
                "results": {
                    "portfolio": {
                        "nivel_servico": service,
                        "decision_metric": decision_metric,
                        "capital_medio_rs": capital,
                    }
                },
                "simulation_window": {
                    "start": "2016-08-14",
                    "evaluation_start": "2016-11-12",
                    "end": "2017-01-10",
                    "n_evaluation_days": 60,
                    "warmup_days": 90,
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _write_metrics(path: Path, margins: list[float], shortages: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # A ordem B,C,A é deliberada: o relatório deve ordenar por ruptura, não
    # repetir a ordem do parquet. Margem potencial por item é 400,200,500.
    pl.DataFrame(
        {
            "item_id": ["B", "C", "A"],
            "price": [10.0, 10.0, 10.0],
            "cost": [8.0, 5.0, 7.0],
            "margin_pct": [0.2, 0.5, 0.3],
            "nivel_servico": [0.8, 0.98, 0.75],
            "margem_realizada_rs": [margins[1], margins[2], margins[0]],
            "ruptura_rs": [shortages[1], shortages[2], shortages[0]],
            "perda_rs": [0.0, 0.0, 0.0],
        }
    ).write_parquet(path)


def build_monthly_report_scenario(root: Path) -> MonthlyReportScenario:
    """Cria os caminhos e formatos efetivamente lidos por monthly/stale_baseline."""
    sensitivity_dir = root / "results" / "sensibilidade_dirigida"
    iso_dir = root / "results" / "iso_servico"
    stale_dir = root / "results" / "baseline_desatualizado"
    for cell, factor in (("lt3_rp7", 0.34), ("lt5_rp7", 0.4), ("lt7_rp14", 0.8)):
        _write_manifest(
            sensitivity_dir / cell / "erp_baseline" / "manifest.json",
            factor=factor,
            service=0.95,
            capital=800.0,
            decision_metric=4.0,
        )
    _write_metrics(
        sensitivity_dir / "lt7_rp14" / "erp_baseline" / "item_metrics.parquet",
        [270.0, 140.0, 490.0],
        [130.0, 60.0, 10.0],
    )
    for label, factor, service, capital, margins, shortages in (
        ("calibrado_lt3_rp7", 0.34, 0.6, 300.0, [150.0, 100.0, 300.0], [250.0, 100.0, 200.0]),
        ("calibrado_lt5_rp7", 0.4, 0.7, 450.0, [200.0, 120.0, 330.0], [200.0, 80.0, 170.0]),
    ):
        directory = stale_dir / label / "erp_baseline"
        _write_manifest(
            directory / "manifest.json",
            factor=factor,
            service=service,
            capital=capital,
            decision_metric=3.0,
        )
        _write_metrics(directory / "item_metrics.parquet", margins, shortages)
    iso_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "alpha": [0.66],
            "nivel_servico": [0.95],
            "decision_metric": [4.5],
            "capital_medio_rs": [700.0],
        }
    ).write_parquet(iso_dir / "arm2_alpha_grid.parquet")
    _write_metrics(
        iso_dir / "item_decomposition_alpha066.parquet",
        [300.0, 160.0, 490.0],
        [100.0, 40.0, 10.0],
    )
    canonical_dir = root / "canonical"
    canonical_dir.mkdir()
    pl.DataFrame(
        {
            "item_id": ["A", "B", "C"],
            "category": ["GROCERY I", "PRODUCE", "BEVERAGES"],
            "unit_of_sale": ["unidade", "kg", "unidade"],
        }
    ).write_parquet(canonical_dir / "items.parquet")
    payload = load_params(PARAMS_PATH).model_dump(mode="json")
    payload["data"]["canonical_dir"] = str(canonical_dir)
    params_path = root / "config" / "params.yaml"
    params_path.parent.mkdir()
    params_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return MonthlyReportScenario(root, params_path, sensitivity_dir, iso_dir, stale_dir)


@contextmanager
def redirected_monthly_sources(case: MonthlyReportScenario) -> Iterator[None]:
    """Redireciona constantes existentes em memória; nenhum módulo protegido é editado."""
    with pytest.MonkeyPatch.context() as patch:
        for module in (monthly, stale):
            patch.setattr(module, "SENSITIVITY_DIR", case.sensitivity_dir)
            patch.setattr(module, "ISO_SERVICE_DIR", case.iso_dir)
            patch.setattr(module, "STALE_BASELINE_DIR", case.stale_dir)
        patch.setattr(monthly, "PARAMS_PATH", case.params_path)
        yield

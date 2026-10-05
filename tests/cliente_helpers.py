"""Apoio dos testes do loader/auditoria/perfil do cliente (Sprint 22).

`read_vendas` é uma leitura INDEPENDENTE do CSV (módulo `csv` da stdlib): os
valores esperados dos testes não podem sair do código que está sendo testado.
Os problemas plantados estão listados na docstring de
`tests/fixtures/make_fixtures.py`.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Final

from motor.config import ClientLoaderParams

FIXTURE_DIR: Final[Path] = Path(__file__).resolve().parent / "fixtures" / "cliente_exemplo"
STORE_ID: Final[str] = "LOJA-EXEMPLO"
STORE_CNPJ: Final[str] = "55566677000188"
S1: Final[str] = "12345678000101"
S2: Final[str] = "98765432000102"
S3: Final[str] = "11122233000103"
S4: Final[str] = "33344455000104"  # lead time 7 >= revisão 7, sem pedidos em aberto

PERIOD_START: Final[date] = date(2024, 1, 1)
PERIOD_END: Final[date] = date(2024, 4, 29)
CLOSED_DAY: Final[date] = date(2024, 3, 31)


def client_params(**overrides: object) -> ClientLoaderParams:
    """Parâmetros explícitos (não lidos do params.yaml): o teste não pode
    mudar de resultado porque alguém ajustou um limiar de produção."""
    values: dict[str, object] = {
        "principal_supplier_window_days": 90,
        "generic_codes": ["9999"],
        "generic_description_patterns": ["DIVERSOS"],
        "generic_revenue_share_warn": 0.05,
        "emergency_name_patterns": ["ATACAREJO", "ATACAD"],
        "emergency_cnae_prefixes": ["4639", "4691"],
        "emergency_warn_max_notes": 2,
        "cost_divergence_tolerance": 0.10,
        "idle_days_threshold": 90,
        "default_shelf_life_days": 365,
        "default_perishable_shelf_life_days": 7,
        "simulation_start_after_days": 84,
    }
    values.update(overrides)
    return ClientLoaderParams(**values)  # type: ignore[arg-type]


@dataclass(frozen=True)
class RawSale:
    day: date
    code: str
    quantity: float
    price: float
    kind: str


def read_vendas(path: Path | None = None) -> list[RawSale]:
    path = path or FIXTURE_DIR / "vendas.csv"
    with path.open(encoding="utf-8", newline="") as fh:
        return [
            RawSale(
                day=datetime.strptime(row["data"], "%d/%m/%Y").date(),
                code=row["codigo"],
                quantity=float(row["quantidade"].replace(",", ".")),
                price=float(row["preco_unit"].replace(",", ".")),
                kind=row["tipo"],
            )
            for row in csv.DictReader(fh, delimiter=";")
        ]

"""Testes de `motor.io.quality_report` (Sprint 24, etapa 24.6).

Fixture sintética com EXATAMENTE uma ocorrência de cada tipo. D0 = 2026-01-05;
40 dias de vendas (dias 0..39). Itens:

    A  vende 5/dia todo dia, exceto o dia 35 (zero)         -> verificação 3
    B  duas linhas no cadastro, descrições diferentes        -> verificação 1
    C  duas linhas no cadastro, unidades de venda diferentes -> verificação 4
    D  ativo, sem `pack_multiple`                            -> verificação 6
    E  vendeu só nos dias 0..2; devolução no dia 38          -> verificação 2
       (sem venda nos 28 dias anteriores; E não é "ativo", não entra na 6)

Entradas: uma recebida ANTES do pedido (verificação 5); a de A foi no dia 5,
longe do zero do dia 35, então não o protege.
"""

from __future__ import annotations

import zipfile
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from motor.config import Params, load_params
from motor.io.quality_report import (
    CHECK_TITLES,
    EVALUATED,
    NOT_EVALUATED,
    build_quality_report,
    export_quality_report_xlsx,
)

D0 = date(2026, 1, 5)
PARAMS_PATH = Path(__file__).resolve().parent.parent / "config" / "params.yaml"
ALL_TYPES = list(CHECK_TITLES)


@pytest.fixture(scope="module")
def params() -> Params:
    return load_params(PARAMS_PATH)


def _day(i: int) -> date:
    return D0 + timedelta(days=i)


def _sales(*, with_defects: bool = True) -> pl.DataFrame:
    rows: list[dict[str, object]] = []

    def add(item: str, i: int, sold: float, returned: float = 0.0) -> None:
        rows.append(
            {
                "store_id": "1",
                "item_id": item,
                "date": _day(i),
                "units_sold": sold,
                "units_returned": returned,
            }
        )

    for i in range(40):
        add("A", i, 0.0 if (with_defects and i == 35) else 5.0)
        add("B", i, 5.0)
        add("C", i, 5.0)
        add("D", i, 5.0)
    for i in range(3):
        add("E", i, 5.0)
    add("E", 38, 0.0, returned=2.0 if with_defects else 0.0)
    return pl.DataFrame(rows)


def _items(*, with_defects: bool = True) -> pl.DataFrame:
    def row(item: str, description: str, unit: str, pack: float | None) -> dict[str, object]:
        return {
            "item_id": item,
            "description": description,
            "unit_of_sale": unit,
            "pack_multiple": pack,
        }

    rows = [
        row("A", "Feijão", "unidade", 6.0),
        row("B", "Arroz 5kg", "unidade", 6.0),
        row("C", "Açúcar", "unidade", 6.0),
        row("D", "Sal", "unidade", None if with_defects else 6.0),
        row("E", "Café", "unidade", 6.0),
    ]
    if with_defects:
        rows.append(row("B", "Arroz 5 kg", "unidade", 6.0))
        rows.append(row("C", "Açúcar", "kg", 6.0))
    return pl.DataFrame(rows)


def _entries(*, with_defects: bool = True) -> pl.DataFrame:
    received = [_day(5), _day(20)]
    ordered = [_day(3), _day(18)]
    if with_defects:
        received.append(_day(10))
        ordered.append(_day(12))  # recebido (10) antes do pedido (12)
    return pl.DataFrame(
        {
            "store_id": ["1"] * len(received),
            "item_id": ["A"] * len(received),
            "received_date": received,
            "quantity": [10.0] * len(received),
            "order_date": ordered,
            "supplier_id": ["S1"] * len(received),
        }
    )


def test_fixture_com_uma_ocorrencia_de_cada_tipo_acha_as_seis_nem_mais_nem_menos(
    params: Params,
) -> None:
    report = build_quality_report(_sales(), _items(), entries=_entries(), params=params)

    assert [c.tipo for c in report.checks] == ALL_TYPES
    assert {c.tipo: c.count for c in report.checks} == dict.fromkeys(ALL_TYPES, 1)
    assert all(c.status == EVALUATED for c in report.checks)

    ocorrencias = {c.tipo: c.occurrences.to_dicts()[0] for c in report.checks}
    assert ocorrencias["descricao_divergente"]["item_id"] == "B"
    assert ocorrencias["devolucao_sem_venda"]["item_id"] == "E"
    assert ocorrencias["devolucao_sem_venda"]["date"] == _day(38)
    assert ocorrencias["dia_sem_venda_item_regular"]["item_id"] == "A"
    assert ocorrencias["dia_sem_venda_item_regular"]["date"] == _day(35)
    assert ocorrencias["unidade_divergente"]["item_id"] == "C"
    assert ocorrencias["recebimento_antes_do_pedido"]["date"] == _day(10)
    assert ocorrencias["cadastro_incompleto"]["item_id"] == "D"
    for occ in ocorrencias.values():
        assert set(occ) == {"tipo", "item_id", "date", "valor", "descricao"}


def test_fixture_limpa_tem_zero_ocorrencias_em_todas_as_verificacoes(params: Params) -> None:
    report = build_quality_report(
        _sales(with_defects=False),
        _items(with_defects=False),
        entries=_entries(with_defects=False),
        params=params,
    )
    assert all(c.status == EVALUATED for c in report.checks)
    assert [c.count for c in report.checks] == [0] * 6
    assert not any(c.critical for c in report.checks)


def test_sem_entries_a_verificacao_5_e_nao_avaliada_e_nao_zero(params: Params) -> None:
    report = build_quality_report(_sales(), _items(), params=params)
    check5 = report.check("recebimento_antes_do_pedido")
    assert check5.status == NOT_EVALUATED
    assert check5.count is None
    assert check5.pct is None
    assert check5.critical is False
    assert check5.reason is not None
    assert "recebimentos" in check5.reason
    # as outras cinco continuam avaliadas; a 3 roda sem a condição de entrada
    assert [c.status for c in report.checks if c.tipo != check5.tipo] == [EVALUATED] * 5
    assert "não informados" in report.check("dia_sem_venda_item_regular").examples["descricao"][0]


def test_entries_sem_order_date_deixa_a_verificacao_5_nao_avaliada(params: Params) -> None:
    entries = _entries().with_columns(pl.lit(None, dtype=pl.Date).alias("order_date"))
    check5 = build_quality_report(_sales(), _items(), entries=entries, params=params).check(
        "recebimento_antes_do_pedido"
    )
    assert check5.status == NOT_EVALUATED
    assert check5.count is None


def test_sem_coluna_de_devolucao_a_verificacao_2_e_nao_avaliada(params: Params) -> None:
    report = build_quality_report(
        _sales().drop("units_returned"), _items(), entries=_entries(), params=params
    )
    assert report.check("devolucao_sem_venda").status == NOT_EVALUATED


def test_entrada_recente_protege_o_dia_sem_venda_da_verificacao_3(params: Params) -> None:
    entries = pl.concat(
        [
            _entries(),
            pl.DataFrame(
                {
                    "store_id": ["1"],
                    "item_id": ["A"],
                    "received_date": [_day(33)],  # 2 dias antes do zero (dia 35)
                    "quantity": [10.0],
                    "order_date": [_day(31)],
                    "supplier_id": ["S1"],
                }
            ),
        ]
    )
    report = build_quality_report(_sales(), _items(), entries=entries, params=params)
    assert report.check("dia_sem_venda_item_regular").count == 0


def test_percentual_exemplos_e_marca_de_critico(params: Params) -> None:
    report = build_quality_report(_sales(), _items(), entries=_entries(), params=params)
    check1 = report.check("descricao_divergente")
    assert check1.base_rows == 7  # linhas do cadastro
    assert check1.pct == pytest.approx(1 / 7)
    assert check1.critical is True  # 14% > limite_percentual_critico (2%)
    assert check1.examples.height == 1

    check3 = report.check("dia_sem_venda_item_regular")
    assert check3.base_rows == _sales().height
    assert check3.pct == pytest.approx(1 / _sales().height)
    assert check3.critical is False  # ~0,4% < 2%


def test_cadastro_incompleto_abaixo_do_minimo_e_critico_e_diz_que_validade_nao_foi_avaliada(
    params: Params,
) -> None:
    # 4 itens ativos (A, B, C, D), 1 sem fardo -> 75% < cadastro_minimo_completo (90%)
    check6 = build_quality_report(_sales(), _items(), entries=_entries(), params=params).check(
        "cadastro_incompleto"
    )
    assert check6.critical is True
    assert check6.note is not None
    assert "75.0%" in check6.note
    assert "Validade: não avaliada" in check6.note


def test_muitas_ocorrencias_so_listam_cinco_exemplos(params: Params) -> None:
    items = pl.concat(
        [
            _items(with_defects=False),
            pl.DataFrame(
                {
                    "item_id": ["B"] * 7,
                    "description": [f"Arroz v{i}" for i in range(7)],
                    "unit_of_sale": ["unidade"] * 7,
                    "pack_multiple": [6.0] * 7,
                }
            ),
        ]
    )
    check1 = build_quality_report(
        _sales(with_defects=False), items, entries=_entries(with_defects=False), params=params
    ).check("descricao_divergente")
    assert check1.count == 1  # um item (B) com várias descrições é UMA ocorrência
    assert check1.examples.height == 1


def test_exporta_xlsx_com_resumo_em_portugues_e_uma_aba_por_tipo(
    params: Params, tmp_path: Path
) -> None:
    report = build_quality_report(_sales(), _items(), params=params)  # sem entries
    path = export_quality_report_xlsx(report, tmp_path / "quality" / "relatorio.xlsx")

    assert path.exists()
    with zipfile.ZipFile(path) as zf:
        workbook = zf.read("xl/workbook.xml").decode()
        strings = zf.read("xl/sharedStrings.xml").decode()
    assert workbook.count("<sheet ") == 1 + len(ALL_TYPES)
    assert 'name="Resumo"' in workbook
    for title in CHECK_TITLES.values():
        assert f'name="{title[:31]}"' in workbook
    for texto in ("Verificação", "Situação", "Quantidade", "Não avaliada", "CRÍTICO"):
        assert texto in strings
    assert "item_id" not in strings  # nenhum nome técnico de coluna na planilha

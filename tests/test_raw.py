"""Testes de motor.io.raw: conversão CSV -> parquet sem transformar nada.

Nenhum teste aqui lê os arquivos reais de data/raw/favorita/ -- todo CSV usado
é sintético, escrito no próprio teste em um tmp_path.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from motor.io.raw import (
    RAW_SCHEMAS,
    RawConversionError,
    _validate_generic,
    convert_raw_to_parquet,
    scan_raw,
)

_TRAIN_HEADER = "id,date,store_nbr,item_nbr,unit_sales,onpromotion\n"
_MINIMAL_ITEMS = "item_nbr,family,class,perishable\n1,GROCERY I,100,0\n2,BREAD/BAKERY,200,1\n"
_MINIMAL_STORES = "store_nbr,city,state,type,cluster\n1,Quito,Pichincha,D,13\n"
_MINIMAL_TRANSACTIONS = "date,store_nbr,transactions\n2013-01-01,1,100\n"
_MINIMAL_OIL = "date,dcoilwtico\n2013-01-01,\n2013-01-02,93.14\n"
_MINIMAL_HOLIDAYS = (
    "date,type,locale,locale_name,description,transferred\n"
    "2013-01-01,Holiday,National,Ecuador,Ano Novo,False\n"
)


def _write_minimal_raw_dir(raw_dir: Path, *, train_body: str) -> None:
    """Escreve os seis CSVs brutos mínimos exigidos por `convert_raw_to_parquet`.

    Só `train.csv` varia por teste (via `train_body`); os outros cinco são
    fixos, pequenos o bastante para caber num literal de string.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "train.csv").write_text(_TRAIN_HEADER + train_body, encoding="utf-8")
    (raw_dir / "items.csv").write_text(_MINIMAL_ITEMS, encoding="utf-8")
    (raw_dir / "stores.csv").write_text(_MINIMAL_STORES, encoding="utf-8")
    (raw_dir / "transactions.csv").write_text(_MINIMAL_TRANSACTIONS, encoding="utf-8")
    (raw_dir / "oil.csv").write_text(_MINIMAL_OIL, encoding="utf-8")
    (raw_dir / "holidays_events.csv").write_text(_MINIMAL_HOLIDAYS, encoding="utf-8")


def test_convert_preserva_contagem_de_linha_e_valores(tmp_path: Path) -> None:
    """CSV pequeno com valor negativo e fracionário dentro -- a conversão não
    pode perder linha nem alterar valor (Sprint 2, teste obrigatório)."""
    train_body = (
        "0,2013-01-01,1,100,7.0,\n"  # onpromotion vazio -> nulo
        "1,2013-01-01,1,101,-3.0,\n"  # negativo
        "2,2013-01-02,1,100,29.904,True\n"  # fracionário
        "3,2013-01-02,1,101,1.0,False\n"
    )
    raw_dir = tmp_path / "raw"
    out_dir = tmp_path / "parquet"
    _write_minimal_raw_dir(raw_dir, train_body=train_body)

    result = convert_raw_to_parquet(raw_dir, out_dir, check_known_totals=False)

    assert set(result) == set(RAW_SCHEMAS)
    train = pl.read_parquet(result["train"]).sort("id")
    assert train.height == 4
    assert train["unit_sales"].to_list() == [7.0, -3.0, 29.904, 1.0]
    assert train["onpromotion"].to_list() == [None, None, True, False]
    assert train.schema["date"] == pl.Date
    assert train.schema["onpromotion"] == pl.Boolean

    items = pl.read_parquet(result["items"])
    assert items.height == 2
    assert items["item_nbr"].to_list() == [1, 2]


def test_convert_e_idempotente(tmp_path: Path) -> None:
    """Rodar duas vezes com overwrite=False não reescreve, e o resultado é idêntico."""
    raw_dir = tmp_path / "raw"
    out_dir = tmp_path / "parquet"
    _write_minimal_raw_dir(raw_dir, train_body="0,2013-01-01,1,100,7.0,\n")

    first = convert_raw_to_parquet(raw_dir, out_dir, check_known_totals=False)
    mtimes_before = {name: path.stat().st_mtime_ns for name, path in first.items()}

    second = convert_raw_to_parquet(raw_dir, out_dir, check_known_totals=False)
    mtimes_after = {name: path.stat().st_mtime_ns for name, path in second.items()}

    assert first == second
    assert mtimes_before == mtimes_after


def test_convert_arquivo_bruto_ausente_levanta_erro(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "train.csv").write_text(_TRAIN_HEADER, encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        convert_raw_to_parquet(raw_dir, tmp_path / "parquet", check_known_totals=False)


def test_validate_generic_detecta_linha_perdida(tmp_path: Path) -> None:
    """Simula uma conversão corrompida (parquet com menos linhas que o csv) sem
    depender do pipeline de conversão real -- chama a checagem diretamente."""
    csv_path = tmp_path / "items.csv"
    csv_path.write_text(_MINIMAL_ITEMS, encoding="utf-8")  # 2 linhas de dado

    out_path = tmp_path / "items.parquet"
    pl.DataFrame(
        {"item_nbr": [1], "family": ["GROCERY I"], "class": [100], "perishable": [0]}
    ).write_parquet(out_path)

    with pytest.raises(RawConversionError, match="parquet tem 1"):
        _validate_generic("items", csv_path, out_path, RAW_SCHEMAS["items"])


def test_validate_generic_detecta_data_toda_nula(tmp_path: Path) -> None:
    """Simula o risco citado no enunciado: schema_overrides de data falhando em
    silêncio e produzindo coluna inteiramente nula, sem mudar a contagem de linha."""
    csv_path = tmp_path / "oil.csv"
    csv_path.write_text(_MINIMAL_OIL, encoding="utf-8")  # 2 linhas de dado

    out_path = tmp_path / "oil.parquet"
    pl.DataFrame(
        {"date": pl.Series([None, None], dtype=pl.Date), "dcoilwtico": [None, 93.14]}
    ).write_parquet(out_path)

    with pytest.raises(RawConversionError, match="coluna 'date'"):
        _validate_generic("oil", csv_path, out_path, RAW_SCHEMAS["oil"])


def test_scan_raw_le_parquet_convertido(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    out_dir = tmp_path / "parquet"
    _write_minimal_raw_dir(raw_dir, train_body="0,2013-01-01,1,100,7.0,\n")
    convert_raw_to_parquet(raw_dir, out_dir, check_known_totals=False)

    assert scan_raw("items", out_dir).collect().height == 2


def test_scan_raw_arquivo_ausente_levanta_erro(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        scan_raw("items", tmp_path)


def test_scan_raw_dataset_desconhecido_levanta_erro(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="não é um dataset bruto conhecido"):
        scan_raw("nao_existe", tmp_path)

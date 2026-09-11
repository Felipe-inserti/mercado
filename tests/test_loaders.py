"""Testes de motor.io.loaders -- normalização canônica do Favorita (Sprint 3).

Todo frame usado por `load_sales`/`load_items`/`load_suppliers`/`load_stock`
é sintético, construído à mão, com os nomes de coluna do BRUTO (`store_nbr`,
`item_nbr`, `unit_sales`, `onpromotion`, `family`, `class`, `perishable`) --
são esses os nomes que `loaders.py` recebe; a fronteira para os nomes
canônicos (`store_id`, `item_id`, `units_sold`, ...) é o próprio módulo sob
teste. Só os testes fim a fim (idempotência, chave única, vazamento,
manifesto) passam por CSV -> parquet real, via `convert_raw_to_parquet`
(`motor.io.raw`) num `tmp_path`, e nenhum lê `data/`.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from motor.config import (
    AnomalyPeriodParams,
    CanonicalParams,
    Params,
    SupplierAssumptionsParams,
    load_params,
)
from motor.io.contracts import (
    ITEMS_PRIMARY_KEY,
    STOCK_PRIMARY_KEY,
    Item,
    SchemaValidationError,
    Stock,
    Supplier,
    expected_polars_schema,
    validate_table,
)
from motor.io.loaders import (
    CanonicalManifest,
    _slugify_supplier_id,
    build_canonical_favorita,
    load_items,
    load_sales,
    load_stock,
    load_suppliers,
)
from motor.io.raw import convert_raw_to_parquet

PARAMS_PATH = Path(__file__).resolve().parent.parent / "config" / "params.yaml"

# --------------------------------------------------------------------------
# Construtores de frame sintético, nomes de coluna do BRUTO
# --------------------------------------------------------------------------


def _sales_raw(
    *,
    dates: list[date],
    store_nbr: list[int],
    item_nbr: list[int],
    unit_sales: list[float],
    onpromotion: list[bool | None] | None = None,
) -> pl.LazyFrame:
    n = len(dates)
    return pl.DataFrame(
        {
            "date": dates,
            "store_nbr": store_nbr,
            "item_nbr": item_nbr,
            "unit_sales": unit_sales,
            "onpromotion": onpromotion if onpromotion is not None else [None] * n,
        },
        schema={
            "date": pl.Date,
            "store_nbr": pl.Int64,
            "item_nbr": pl.Int64,
            "unit_sales": pl.Float64,
            "onpromotion": pl.Boolean,
        },
    ).lazy()


def _items_raw(
    *, item_nbr: list[int], family: list[str], item_class: list[int], perishable: list[int]
) -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "item_nbr": item_nbr,
            "family": family,
            "class": item_class,
            "perishable": perishable,
        },
        schema={
            "item_nbr": pl.Int64,
            "family": pl.String,
            "class": pl.Int64,
            "perishable": pl.Int64,
        },
    ).lazy()


# --------------------------------------------------------------------------
# 1. Reindex com buracos de calendário conhecidos -- linhas calculadas à mão
# --------------------------------------------------------------------------


def test_reindex_buracos_de_calendario_conhecidos() -> None:
    """Par único, loja já aberta bem antes da janela, vendas em 01/03/05, janela 01-10.

    Sem truncamento (delisting_gap_days folgado): saída deve ser exatamente
    os 10 dias corridos, com `units_sold` batendo com o bruto nos dias 1/3/5
    e zero nos demais, `on_promo` só preenchido onde havia linha bruta, e
    `is_operating_day` só True nos dias em que a loja teve alguma venda.
    """
    raw = _sales_raw(
        dates=[
            date(2020, 1, 1),  # abertura da loja, bem antes da janela
            date(2024, 1, 1),
            date(2024, 1, 3),
            date(2024, 1, 5),
        ],
        store_nbr=[1, 1, 1, 1],
        item_nbr=[999, 100, 100, 100],  # item 999 só existe em 2020, fora da janela
        unit_sales=[1.0, 5.0, 3.0, 2.0],
        onpromotion=[None, True, None, False],
    )
    result = load_sales(
        raw,
        window_start=date(2024, 1, 1),
        window_end=date(2024, 1, 10),
        delisting_gap_days=90,
        anomalies=[],
    ).collect()

    pair = result.filter(pl.col("item_id") == "100").sort("date")
    assert pair["date"].to_list() == [date(2024, 1, d) for d in range(1, 11)]
    assert pair["units_sold"].to_list() == [5.0, 0.0, 3.0, 0.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert pair["units_returned"].to_list() == [0.0] * 10
    assert pair["on_promo"].to_list() == [
        True,
        None,
        None,
        None,
        False,
        None,
        None,
        None,
        None,
        None,
    ]
    assert pair["is_operating_day"].to_list() == [
        True,
        False,
        True,
        False,
        True,
        False,
        False,
        False,
        False,
        False,
    ]
    # item 999 nunca vendeu dentro da janela -- não deve aparecer na saída.
    assert result.filter(pl.col("item_id") == "999").height == 0


# --------------------------------------------------------------------------
# 2. Conservação de units
# --------------------------------------------------------------------------


def test_conservacao_de_units() -> None:
    """Soma de `units_sold` antes/depois do reindex é idêntica -- só adiciona zeros."""
    raw = _sales_raw(
        dates=[date(2024, 1, d) for d in (1, 1, 2, 4, 6, 7)],
        store_nbr=[1, 1, 1, 1, 1, 1],
        item_nbr=[100, 200, 100, 200, 100, 200],
        unit_sales=[5.0, -2.0, 3.0, 7.0, 1.0, 4.0],
    )
    expected_total = raw.select(pl.col("unit_sales").clip(lower_bound=0.0).sum()).collect().item()

    result = load_sales(
        raw,
        window_start=date(2024, 1, 1),
        window_end=date(2024, 1, 7),
        delisting_gap_days=90,
        anomalies=[],
    ).collect()

    assert result["units_sold"].sum() == pytest.approx(expected_total)


# --------------------------------------------------------------------------
# 3. Contagem exata de linhas -- soma dos spans à mão
# --------------------------------------------------------------------------


def test_contagem_exata_de_linhas() -> None:
    """Duas linhas de lifespan distintas, span calculado à mão e comparado à contagem real."""
    raw = _sales_raw(
        dates=[date(2024, 1, 1), date(2024, 1, 10), date(2024, 1, 4), date(2024, 1, 10)],
        store_nbr=[1, 1, 1, 1],
        item_nbr=[100, 100, 200, 200],
        unit_sales=[5.0, 1.0, 3.0, 2.0],
    )
    result = load_sales(
        raw,
        window_start=date(2024, 1, 1),
        window_end=date(2024, 1, 10),
        delisting_gap_days=90,
        anomalies=[],
    ).collect()

    span_a = (date(2024, 1, 10) - date(2024, 1, 1)).days + 1  # 10
    span_b = (date(2024, 1, 10) - date(2024, 1, 4)).days + 1  # 7
    assert result.height == span_a + span_b


# --------------------------------------------------------------------------
# 4. Nenhuma linha antes da existência -- loja que abre no meio da janela
# --------------------------------------------------------------------------


def test_nenhuma_linha_antes_da_existencia() -> None:
    """Loja 2 só existe (1ª venda de qualquer item) a partir de 05/01 -- sem linha antes disso."""
    raw = _sales_raw(
        dates=[date(2024, 1, 5), date(2024, 1, 9)],
        store_nbr=[2, 2],
        item_nbr=[300, 300],
        unit_sales=[4.0, 1.0],
    )
    result = load_sales(
        raw,
        window_start=date(2024, 1, 1),
        window_end=date(2024, 1, 10),
        delisting_gap_days=90,
        anomalies=[],
    ).collect()

    assert result["date"].min() == date(2024, 1, 5)
    assert result.height == (date(2024, 1, 10) - date(2024, 1, 5)).days + 1


# --------------------------------------------------------------------------
# 5. Idempotência -- byte a byte nos quatro parquets de dado
# --------------------------------------------------------------------------


def _write_minimal_raw_dir(raw_dir: Path, *, train_body: str, items_body: str) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "train.csv").write_text(
        "id,date,store_nbr,item_nbr,unit_sales,onpromotion\n" + train_body, encoding="utf-8"
    )
    (raw_dir / "items.csv").write_text(
        "item_nbr,family,class,perishable\n" + items_body, encoding="utf-8"
    )
    (raw_dir / "stores.csv").write_text(
        "store_nbr,city,state,type,cluster\n1,Quito,Pichincha,D,13\n", encoding="utf-8"
    )
    (raw_dir / "transactions.csv").write_text(
        "date,store_nbr,transactions\n2024-01-01,1,100\n", encoding="utf-8"
    )
    (raw_dir / "oil.csv").write_text("date,dcoilwtico\n2024-01-01,80.0\n", encoding="utf-8")
    (raw_dir / "holidays_events.csv").write_text(
        "date,type,locale,locale_name,description,transferred\n"
        "2024-01-01,Holiday,National,Ecuador,Ano Novo,False\n",
        encoding="utf-8",
    )


def _tiny_params(*, canonical: CanonicalParams) -> Params:
    """`params.yaml` real do repositório, com `canonical` e `supplier_assumptions` trocados
    por versões pequenas/controladas para o teste -- evita reconstruir o `Params` inteiro."""
    base = load_params(PARAMS_PATH)
    return base.model_copy(
        update={
            "canonical": canonical,
            "supplier_assumptions": SupplierAssumptionsParams(
                default_pack_multiple=1.0,
                default_lead_time_days=3,
                default_review_period_days=7,
                default_min_order_value=0.0,
                default_min_order_units=0.0,
                default_order_weekdays=[1, 2, 3, 4, 5],
            ),
        }
    )


def test_idempotencia(tmp_path: Path) -> None:
    """`build_canonical_favorita` 2x com `overwrite=True`: parquets de dado byte a byte iguais."""
    train_body = (
        "0,2024-01-01,1,100,5.0,True\n1,2024-01-03,1,100,3.0,\n2,2024-01-05,1,100,-2.0,False\n"
    )
    items_body = "100,GROCERY I,100,0\n"
    raw_dir = tmp_path / "raw"
    parquet_dir = tmp_path / "raw_parquet"
    out_dir = tmp_path / "canonical"
    _write_minimal_raw_dir(raw_dir, train_body=train_body, items_body=items_body)
    convert_raw_to_parquet(raw_dir, parquet_dir, check_known_totals=False)

    canonical = CanonicalParams(
        window_start=date(2024, 1, 1),
        window_end=date(2024, 1, 7),
        delisting_gap_days=90,
        fractional_threshold=0.5,
        anomalies=[],
    )
    params = _tiny_params(canonical=canonical)

    manifest_1 = build_canonical_favorita(parquet_dir, out_dir, params, overwrite=True)
    tables = {
        name: (out_dir / f"{name}.parquet").read_bytes()
        for name in ("sales", "items", "suppliers", "stock")
    }
    manifest_2 = build_canonical_favorita(parquet_dir, out_dir, params, overwrite=True)
    tables_again = {
        name: (out_dir / f"{name}.parquet").read_bytes()
        for name in ("sales", "items", "suppliers", "stock")
    }

    assert tables == tables_again
    assert manifest_1.row_counts == manifest_2.row_counts
    assert manifest_1.params_hash == manifest_2.params_hash
    assert manifest_1.input_files == manifest_2.input_files
    # generated_at/execution_seconds são a exceção documentada -- não comparados.


# --------------------------------------------------------------------------
# 6. Atribuição de fornecedor determinística (D8)
# --------------------------------------------------------------------------


def test_atribuicao_de_fornecedor_deterministica() -> None:
    """Slug conhecido, e mesmo conjunto de families em ordem diferente -> mesmo mapeamento."""
    assert _slugify_supplier_id("BREAD/BAKERY") == "SUP-BREAD_BAKERY"
    assert _slugify_supplier_id("GROCERY I") == "SUP-GROCERY_I"

    assumptions = SupplierAssumptionsParams(
        default_pack_multiple=1.0,
        default_lead_time_days=3,
        default_review_period_days=7,
        default_min_order_value=0.0,
        default_min_order_units=0.0,
        default_order_weekdays=[1, 2, 3, 4, 5],
    )
    items_a = _items_raw(
        item_nbr=[1, 2, 3],
        family=["BREAD/BAKERY", "GROCERY I", "BREAD/BAKERY"],
        item_class=[1, 2, 1],
        perishable=[1, 0, 1],
    )
    items_b = _items_raw(
        item_nbr=[3, 2, 1],
        family=["BREAD/BAKERY", "GROCERY I", "BREAD/BAKERY"],
        item_class=[1, 2, 1],
        perishable=[1, 0, 1],
    )
    suppliers_a = load_suppliers(items_a, supplier_assumptions=assumptions)
    suppliers_b = load_suppliers(items_b, supplier_assumptions=assumptions)
    assert sorted(suppliers_a["supplier_id"].to_list()) == sorted(
        suppliers_b["supplier_id"].to_list()
    )
    assert set(suppliers_a["supplier_id"].to_list()) == {"SUP-BREAD_BAKERY", "SUP-GROCERY_I"}


def test_colisao_de_supplier_id_levanta_erro() -> None:
    """Duas families distintas que geram o mesmo slug: `ValueError` explícito, não silêncio (D8)."""
    assumptions = SupplierAssumptionsParams(
        default_pack_multiple=1.0,
        default_lead_time_days=3,
        default_review_period_days=7,
        default_min_order_value=0.0,
        default_min_order_units=0.0,
        default_order_weekdays=[1, 2, 3, 4, 5],
    )
    items = _items_raw(
        item_nbr=[1, 2],
        family=["BREAD/BAKERY", "BREAD BAKERY"],
        item_class=[1, 1],
        perishable=[1, 1],
    )
    with pytest.raises(ValueError, match="colisão de supplier_id"):
        load_suppliers(items, supplier_assumptions=assumptions)


# --------------------------------------------------------------------------
# 7. Chave única levanta erro claro
# --------------------------------------------------------------------------


def test_chave_unica_levanta_erro(tmp_path: Path) -> None:
    """Bruto malformado com duas linhas para o mesmo (date, store_nbr, item_nbr):
    `build_canonical_favorita` levanta `SchemaValidationError` claro."""
    train_body = (
        "0,2024-01-01,1,100,5.0,True\n1,2024-01-01,1,100,3.0,False\n"  # par/data duplicados
    )
    items_body = "100,GROCERY I,100,0\n"
    raw_dir = tmp_path / "raw"
    parquet_dir = tmp_path / "raw_parquet"
    out_dir = tmp_path / "canonical"
    _write_minimal_raw_dir(raw_dir, train_body=train_body, items_body=items_body)
    convert_raw_to_parquet(raw_dir, parquet_dir, check_known_totals=False)

    canonical = CanonicalParams(
        window_start=date(2024, 1, 1),
        window_end=date(2024, 1, 3),
        delisting_gap_days=90,
        fractional_threshold=0.5,
        anomalies=[],
    )
    params = _tiny_params(canonical=canonical)

    with pytest.raises(SchemaValidationError) as exc_info:
        build_canonical_favorita(parquet_dir, out_dir, params, overwrite=True)
    message = str(exc_info.value)
    assert "chave primária duplicada" in message


# --------------------------------------------------------------------------
# 8. Sem vazamento por agregado global
# --------------------------------------------------------------------------


def test_sem_vazamento_por_agregado_global(tmp_path: Path) -> None:
    """Linhas extras bem fora da janela (ano 2018, fracionárias, MUITO mais numerosas que as
    da janela): a classificação un/kg do item na janela não pode mudar."""
    window_start, window_end = date(2024, 1, 1), date(2024, 1, 10)
    # Dentro da janela: 5 vendas inteiras -> fractional_ratio = 0.0 -> "unidade".
    in_window_rows = "".join(f"{i},2024-01-0{i + 1},1,100,{float(i + 1)},False\n" for i in range(5))
    # Fora da janela (2018, bem antes): 20 vendas fracionárias -- se vazasse, o ratio global
    # (20 / 25 = 0.8) passaria do limiar de 0.5 e classificaria o item como "kg".
    out_of_window_rows = "".join(
        f"{5 + i},2018-01-{i + 1:02d},1,100,{i + 1}.5,False\n" for i in range(20)
    )
    items_body = "100,GROCERY I,100,0\n"

    canonical = CanonicalParams(
        window_start=window_start,
        window_end=window_end,
        delisting_gap_days=90,
        fractional_threshold=0.5,
        anomalies=[],
    )
    params = _tiny_params(canonical=canonical)

    raw_dir_a = tmp_path / "raw_a"
    parquet_dir_a = tmp_path / "parquet_a"
    out_dir_a = tmp_path / "canonical_a"
    _write_minimal_raw_dir(raw_dir_a, train_body=in_window_rows, items_body=items_body)
    convert_raw_to_parquet(raw_dir_a, parquet_dir_a, check_known_totals=False)
    build_canonical_favorita(parquet_dir_a, out_dir_a, params, overwrite=True)

    raw_dir_b = tmp_path / "raw_b"
    parquet_dir_b = tmp_path / "parquet_b"
    out_dir_b = tmp_path / "canonical_b"
    _write_minimal_raw_dir(
        raw_dir_b, train_body=in_window_rows + out_of_window_rows, items_body=items_body
    )
    convert_raw_to_parquet(raw_dir_b, parquet_dir_b, check_known_totals=False)
    build_canonical_favorita(parquet_dir_b, out_dir_b, params, overwrite=True)

    items_a = pl.read_parquet(out_dir_a / "items.parquet")
    items_b = pl.read_parquet(out_dir_b / "items.parquet")
    assert items_a.equals(items_b)
    assert items_a.filter(pl.col("item_id") == "100")["unit_of_sale"].item() == "unidade"

    sales_a = pl.read_parquet(out_dir_a / "sales.parquet")
    sales_b = pl.read_parquet(out_dir_b / "sales.parquet")
    assert sales_a.equals(sales_b)


# --------------------------------------------------------------------------
# 9. D1 -- anomalia marcada dentro e fora do período
# --------------------------------------------------------------------------


def test_d1_anomalia_marcada_dentro_e_fora_do_periodo() -> None:
    raw = _sales_raw(
        dates=[date(2024, 1, d) for d in (1, 4, 5, 6, 10)],
        store_nbr=[1] * 5,
        item_nbr=[100] * 5,
        unit_sales=[1.0, 2.0, 3.0, 4.0, 5.0],
    )
    anomaly = AnomalyPeriodParams(
        name="teste", start=date(2024, 1, 4), end=date(2024, 1, 6), reason="motivo de teste"
    )
    result = (
        load_sales(
            raw,
            window_start=date(2024, 1, 1),
            window_end=date(2024, 1, 10),
            delisting_gap_days=90,
            anomalies=[anomaly],
        )
        .collect()
        .sort("date")
    )

    inside = result.filter(pl.col("date").is_between(date(2024, 1, 4), date(2024, 1, 6)))
    outside = result.filter(~pl.col("date").is_between(date(2024, 1, 4), date(2024, 1, 6)))

    assert inside["is_anomaly"].to_list() == [True, True, True]
    assert inside["anomaly_reason"].to_list() == ["motivo de teste"] * 3
    assert not any(outside["is_anomaly"].to_list())
    assert all(r is None for r in outside["anomaly_reason"].to_list())


# --------------------------------------------------------------------------
# 10. D2 -- par descontinuado e truncado vs. par ativo e zerado
# --------------------------------------------------------------------------


def test_d2_par_descontinuado_e_truncado_vs_par_ativo_e_zerado() -> None:
    """Item 100: última venda a 30 dias do fim (> delisting_gap_days=10) -> truncado.
    Item 200: última venda a 2 dias do fim (<= 10) -> zerado até window_end."""
    window_start, window_end = date(2024, 1, 1), date(2024, 3, 1)  # 61 dias
    raw = _sales_raw(
        dates=[window_start, date(2024, 1, 30), window_start, date(2024, 2, 27)],
        store_nbr=[1, 1, 1, 1],
        item_nbr=[100, 100, 200, 200],
        unit_sales=[1.0, 1.0, 1.0, 1.0],
    )
    result = load_sales(
        raw, window_start=window_start, window_end=window_end, delisting_gap_days=10, anomalies=[]
    ).collect()

    item_100 = result.filter(pl.col("item_id") == "100")
    item_200 = result.filter(pl.col("item_id") == "200")

    # Truncado: última venda (30/01) + delisting_gap_days(10) = 09/02, não window_end.
    assert item_100["date"].max() == date(2024, 1, 30) + timedelta(days=10)
    assert item_100["date"].max() < window_end

    # Zerado normalmente: vai até window_end, mesmo com a última venda a 2 dias do fim.
    assert item_200["date"].max() == window_end
    tail = item_200.filter(pl.col("date") > date(2024, 2, 27))
    assert tail["units_sold"].to_list() == [0.0] * ((window_end - date(2024, 2, 27)).days)


# --------------------------------------------------------------------------
# 11. D3 -- dia sem nenhuma venda marca todos os pares da loja
# --------------------------------------------------------------------------


def test_d3_dia_sem_nenhuma_venda_marca_todos_os_pares_da_loja() -> None:
    """01-05: nenhum item vendeu -- ambos os pares ficam `is_operating_day=False` nesse dia.
    01-06: só item 100 vendeu, mas a loja operou -- item 200 também fica `True` nesse dia
    (o atributo é de loja, replicado por linha de item, não derivado por item)."""
    raw = _sales_raw(
        dates=[
            date(2024, 1, 1),
            date(2024, 1, 6),
            date(2024, 1, 10),
            date(2024, 1, 2),
            date(2024, 1, 10),
        ],
        store_nbr=[1, 1, 1, 1, 1],
        item_nbr=[100, 100, 100, 200, 200],
        unit_sales=[1.0, 1.0, 1.0, 1.0, 1.0],
    )
    result = load_sales(
        raw,
        window_start=date(2024, 1, 1),
        window_end=date(2024, 1, 10),
        delisting_gap_days=90,
        anomalies=[],
    ).collect()

    day_5 = result.filter(pl.col("date") == date(2024, 1, 5))
    assert set(day_5["is_operating_day"].to_list()) == {False}
    assert set(day_5["item_id"].to_list()) == {"100", "200"}

    day_6_item_200 = result.filter(
        (pl.col("date") == date(2024, 1, 6)) & (pl.col("item_id") == "200")
    )
    assert day_6_item_200["is_operating_day"].item() is True
    assert day_6_item_200["units_sold"].item() == 0.0  # não vendeu, mas a loja operou


# --------------------------------------------------------------------------
# 12. D4 -- negativo vira returns, positivo vira zero returns
# --------------------------------------------------------------------------


def test_d4_negativo_vira_returns_positivo_vira_zero_returns() -> None:
    raw = _sales_raw(
        dates=[date(2024, 1, 1), date(2024, 1, 2)],
        store_nbr=[1, 1],
        item_nbr=[100, 100],
        unit_sales=[-3.0, 7.0],
    )
    result = (
        load_sales(
            raw,
            window_start=date(2024, 1, 1),
            window_end=date(2024, 1, 2),
            delisting_gap_days=90,
            anomalies=[],
        )
        .collect()
        .sort("date")
    )

    assert result["units_sold"].to_list() == [0.0, 7.0]
    assert result["units_returned"].to_list() == [3.0, 0.0]


# --------------------------------------------------------------------------
# 13. D5 -- classificação un/kg e fronteira do limiar
# --------------------------------------------------------------------------


def test_d5_classificacao_un_kg_e_fronteira_do_limiar() -> None:
    items = _items_raw(
        item_nbr=[1, 2, 3, 4],
        family=["A", "B", "C", "D"],
        item_class=[1, 1, 1, 1],
        perishable=[0, 0, 0, 0],
    )
    sales = _sales_raw(
        dates=[date(2024, 1, d) for d in range(1, 11)],
        store_nbr=[1] * 10,
        item_nbr=[1, 1, 1, 2, 2, 2, 3, 3, 3, 4],
        unit_sales=[
            1.0,
            2.0,
            3.0,  # item 1: 0 de 3 fracionária -> ratio 0.0
            1.5,
            2.5,
            3.7,  # item 2: 3 de 3 fracionária -> ratio 1.0
            1.0,
            2.5,
            3.0,  # item 3: 1 de 3 fracionária -> ratio 0,333... < 0.5
            1.5,  # item 4: só uma venda, fracionária -- não serve sozinho para o limite exato
        ],
    )
    result = load_items(items, sales, fractional_threshold=0.5, default_pack_multiple=1.0)
    by_item = {row["item_id"]: row["unit_of_sale"] for row in result.to_dicts()}

    assert by_item["1"] == "unidade"  # ratio 0.0
    assert by_item["2"] == "kg"  # ratio 1.0
    assert by_item["3"] == "unidade"  # ratio 1/3 < 0.5

    # Fronteira exata: item 4 recebe uma segunda venda inteira -> 1 de 2 fracionária = 0.5 exato.
    boundary_sales = pl.concat(
        [
            sales,
            _sales_raw(dates=[date(2024, 1, 11)], store_nbr=[1], item_nbr=[4], unit_sales=[2.0]),
        ]
    )
    result_boundary = load_items(
        items, boundary_sales, fractional_threshold=0.5, default_pack_multiple=1.0
    )
    by_item_boundary = {row["item_id"]: row["unit_of_sale"] for row in result_boundary.to_dicts()}
    assert by_item_boundary["4"] == "kg"  # ratio exatamente 0.5 == limiar -> kg (>=, inclusivo)


# --------------------------------------------------------------------------
# 14. D6 -- onpromotion nulo só nas linhas sem dado bruto
# --------------------------------------------------------------------------


def test_d6_onpromotion_nulo_so_nas_linhas_sem_dado_bruto() -> None:
    raw = _sales_raw(
        dates=[date(2024, 1, 1), date(2024, 1, 2)],
        store_nbr=[1, 1],
        item_nbr=[100, 100],
        unit_sales=[5.0, 3.0],
        onpromotion=[True, None],  # dia 2: linha bruta existe, mas promoção é desconhecida
    )
    result = (
        load_sales(
            raw,
            window_start=date(2024, 1, 1),
            window_end=date(2024, 1, 4),
            delisting_gap_days=90,
            anomalies=[],
        )
        .collect()
        .sort("date")
    )

    assert result["on_promo"].to_list() == [True, None, None, None]
    # dia 2 é nulo mas TEM venda bruta (3.0); dia 3/4 são reindex puro, nulo e zero.
    assert result["units_sold"].to_list() == [5.0, 3.0, 0.0, 0.0]


# --------------------------------------------------------------------------
# 15. D7 -- items: campos inexistentes no Favorita ficam nulos
# --------------------------------------------------------------------------


def test_d7_items_campos_inexistentes_ficam_nulos() -> None:
    items = _items_raw(item_nbr=[1], family=["BREAD/BAKERY"], item_class=[2712], perishable=[1])
    sales = _sales_raw(dates=[date(2024, 1, 1)], store_nbr=[1], item_nbr=[1], unit_sales=[1.0])
    result = load_items(items, sales, fractional_threshold=0.5, default_pack_multiple=1.0)
    validate_table(result, Item, table_name="items", primary_key=ITEMS_PRIMARY_KEY)
    row = result.to_dicts()[0]

    assert row["ean"] is None
    assert row["description"] is None
    assert row["cost"] is None
    assert row["price_ref"] is None
    assert row["is_anchor"] is None
    assert row["category"] == "BREAD/BAKERY"
    assert row["item_class"] == "2712"
    assert row["is_perishable"] is True
    assert row["supplier_id"] == "SUP-BREAD_BAKERY"


# --------------------------------------------------------------------------
# 16. D8 -- suppliers: valores vêm de params, não hardcoded
# --------------------------------------------------------------------------


def test_d8_suppliers_valores_vem_de_params_nao_hardcoded() -> None:
    items = _items_raw(item_nbr=[1], family=["GROCERY I"], item_class=[1], perishable=[0])
    assumptions_a = SupplierAssumptionsParams(
        default_pack_multiple=1.0,
        default_lead_time_days=3,
        default_review_period_days=7,
        default_min_order_value=0.0,
        default_min_order_units=0.0,
        default_order_weekdays=[1, 2, 3, 4, 5],
    )
    assumptions_b = SupplierAssumptionsParams(
        default_pack_multiple=1.0,
        default_lead_time_days=15,
        default_review_period_days=14,
        default_min_order_value=500.0,
        default_min_order_units=0.0,
        default_order_weekdays=[2, 4],
    )
    result_a = load_suppliers(items, supplier_assumptions=assumptions_a).to_dicts()[0]
    result_b = load_suppliers(items, supplier_assumptions=assumptions_b).to_dicts()[0]

    assert result_a["lead_time_days"] == 3
    assert result_b["lead_time_days"] == 15
    assert result_a["review_period_days"] == 7
    assert result_b["review_period_days"] == 14
    assert result_a["min_order_value"] == 0.0
    assert result_b["min_order_value"] == 500.0
    assert result_a["order_days"] == [1, 2, 3, 4, 5]
    assert result_b["order_days"] == [2, 4]


# --------------------------------------------------------------------------
# 17. D9 -- stock vazio valida contra schema
# --------------------------------------------------------------------------


def test_d9_stock_vazio_valida_contra_schema() -> None:
    stock = load_stock()
    assert stock.height == 0
    assert stock.schema == expected_polars_schema(Stock)
    validate_table(stock, Stock, table_name="stock", primary_key=STOCK_PRIMARY_KEY)


# --------------------------------------------------------------------------
# 18. Pendência da Sprint 10 (Sprint 11, Parte A) -- contrato de min_order_units
# --------------------------------------------------------------------------
#
# `Supplier` (contracts.py) exige `min_order_units` desde a Sprint 10 e
# `load_suppliers` já a preenche a partir de `supplier_assumptions`. O que
# ficou defasado foi só o ARTEFATO em disco (`data/canonical/favorita/
# suppliers.parquet`), gerado antes dessa mudança -- exatamente a mina que a
# Sprint 12 pisaria ao compor `target_level.py` + `supplier.py` com dado
# real. Dois testes complementares, não um só: o primeiro roda sempre e
# prova que a FUNÇÃO está certa; o segundo roda condicionalmente e prova que
# o ARTEFATO já gerado não ficou pra trás -- são falhas de natureza
# diferente e cada uma pede o diagnóstico certo.

_SUPPLIERS_PARQUET_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "canonical" / "favorita" / "suppliers.parquet"
)


def test_load_suppliers_output_valida_contra_contrato_supplier() -> None:
    """Teste de contrato PURO: toda linha que `load_suppliers` promete
    devolver tem que construir um `Supplier` pydantic válido -- incluindo
    `min_order_units`. Roda inteiramente em memória, sem tocar `data/`: é o
    teste que teria pego a divergência entre `load_suppliers` e `Supplier`
    no instante em que uma das duas mudasse sem a outra, em vez de só
    estourar quando alguém compusesse com o dado real numa sprint futura.
    """
    items = _items_raw(
        item_nbr=[1, 2], family=["GROCERY I", "DAIRY"], item_class=[1, 2], perishable=[0, 1]
    )
    assumptions = SupplierAssumptionsParams(
        default_pack_multiple=1.0,
        default_lead_time_days=3,
        default_review_period_days=7,
        default_min_order_value=0.0,
        default_min_order_units=0.0,
        default_order_weekdays=[1, 2, 3, 4, 5],
    )
    suppliers_df = load_suppliers(items, supplier_assumptions=assumptions)
    assert suppliers_df.height > 0  # asserção abaixo não pode passar vazia por acidente

    for row in suppliers_df.to_dicts():
        Supplier(**row)  # não deve levantar -- é a checagem em si


@pytest.mark.skipif(
    not _SUPPLIERS_PARQUET_PATH.exists(),
    reason=(
        f"{_SUPPLIERS_PARQUET_PATH} não existe -- data/ está no .gitignore, não "
        "vem no clone. Regenere com build_canonical_favorita(raw_parquet_dir, "
        "canonical_dir, params, overwrite=True) (ver config/params.yaml, "
        "data.raw_parquet_dir/data.canonical_dir) antes de rodar este teste."
    ),
)
def test_artefato_real_suppliers_parquet_valida_contra_supplier() -> None:
    """Teste sobre o artefato REAL já gerado em `data/canonical/favorita/`.

    Skip condicional e EXPLÍCITO em vez de incondicional: `data/` está fora
    do git (`.gitignore`), então um teste incondicional quebraria em clone
    limpo por um motivo que nada tem a ver com o código. Skip silencioso
    seria o problema real (a defasagem que motivou esta seção passaria
    despercebida de novo); skip que ensina como regenerar não é.
    """
    df = pl.read_parquet(_SUPPLIERS_PARQUET_PATH)
    assert df.height > 0

    for row in df.to_dicts():
        Supplier(**row)


# --------------------------------------------------------------------------
# 19. build_canonical_favorita: manifesto tem os campos esperados
# --------------------------------------------------------------------------


def test_build_canonical_favorita_manifest_tem_campos_esperados(tmp_path: Path) -> None:
    train_body = "0,2024-01-01,1,100,5.0,True\n1,2024-01-05,1,100,2.0,False\n"
    items_body = "100,GROCERY I,100,0\n"
    raw_dir = tmp_path / "raw"
    parquet_dir = tmp_path / "raw_parquet"
    out_dir = tmp_path / "canonical"
    _write_minimal_raw_dir(raw_dir, train_body=train_body, items_body=items_body)
    convert_raw_to_parquet(raw_dir, parquet_dir, check_known_totals=False)

    canonical = CanonicalParams(
        window_start=date(2024, 1, 1),
        window_end=date(2024, 1, 5),
        delisting_gap_days=90,
        fractional_threshold=0.5,
        anomalies=[],
    )
    params = _tiny_params(canonical=canonical)

    manifest = build_canonical_favorita(parquet_dir, out_dir, params, overwrite=True)

    assert isinstance(manifest, CanonicalManifest)
    assert manifest.schema_version == 1
    assert manifest.window_start == date(2024, 1, 1)
    assert manifest.window_end == date(2024, 1, 5)
    assert manifest.execution_seconds >= 0.0
    assert manifest.git_commit_hash is None or isinstance(manifest.git_commit_hash, str)
    assert len(manifest.params_hash) == 64  # hex de sha256
    assert set(manifest.input_files) == {"train", "items"}
    assert set(manifest.row_counts) == {"sales", "items", "suppliers", "stock"}
    assert set(manifest.output_files) == {"sales", "items", "suppliers", "stock"}
    assert manifest.row_counts["sales"] == 5  # 01-01..01-05
    assert manifest.row_counts["items"] == 1
    assert manifest.row_counts["suppliers"] == 1
    assert manifest.row_counts["stock"] == 0
    assert "canonical" in manifest.active_params
    assert "supplier_assumptions" in manifest.active_params

    reread = CanonicalManifest.model_validate_json((out_dir / "manifest.json").read_text())
    assert reread == manifest
    for name in ("sales", "items", "suppliers", "stock"):
        assert (out_dir / f"{name}.parquet").exists()


# --------------------------------------------------------------------------
# 19. Buraco final >= delisting_gap_days E anomalia dentro da janela --
#     truncamento e marcação não podem se atropelar
# --------------------------------------------------------------------------


def test_par_com_buraco_final_e_anomalia_nao_se_atropelam() -> None:
    window_start = date(2024, 1, 1)
    window_end = date(2024, 6, 30)  # janela longa, span de 182 dias
    last_sale = date(2024, 3, 1)
    delisting_gap_days = 90
    expected_exit = last_sale + timedelta(days=delisting_gap_days)  # 2024-05-30, < window_end
    assert expected_exit < window_end

    anomaly_start, anomaly_end = date(2024, 2, 1), date(2024, 2, 5)  # antes do truncamento

    raw = _sales_raw(
        dates=[window_start, anomaly_start, last_sale],
        store_nbr=[1, 1, 1],
        item_nbr=[100, 100, 100],
        unit_sales=[1.0, 1.0, 1.0],
    )
    anomaly = AnomalyPeriodParams(
        name="teste", start=anomaly_start, end=anomaly_end, reason="motivo de teste"
    )
    result = load_sales(
        raw,
        window_start=window_start,
        window_end=window_end,
        delisting_gap_days=delisting_gap_days,
        anomalies=[anomaly],
    ).collect()

    # Truncamento: última data de saída é o corte de descontinuação, não window_end.
    assert result["date"].max() == expected_exit
    assert result.height == (expected_exit - window_start).days + 1

    # Marcação de anomalia intacta dentro do período, mesmo com o truncamento em vigor.
    anomaly_rows = result.filter(pl.col("date").is_between(anomaly_start, anomaly_end))
    assert anomaly_rows.height == (anomaly_end - anomaly_start).days + 1
    assert all(anomaly_rows["is_anomaly"].to_list())
    assert all(r == "motivo de teste" for r in anomaly_rows["anomaly_reason"].to_list())

    # Um dia depois da última venda, fora do período de anomalia: zero-fill normal, sem marca.
    post_sale_day = result.filter(pl.col("date") == last_sale + timedelta(days=1))
    assert post_sale_day["is_anomaly"].item() is False
    assert post_sale_day["units_sold"].item() == 0.0

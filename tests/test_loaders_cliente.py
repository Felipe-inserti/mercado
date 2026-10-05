"""Testes de `motor.io.loaders_cliente` (Sprint 22): exportação do cliente -> 4 tabelas canônicas.

Dado FICTÍCIO (`tests/fixtures/cliente_exemplo/`, gerado por
`tests/fixtures/make_fixtures.py`, com os problemas plantados listados na
docstring de lá). Os valores esperados saem de literais ou de uma leitura
INDEPENDENTE do CSV (`tests.cliente_helpers.read_vendas`), nunca do código
sob teste. Conjuntos são comparados por IGUALDADE, não por "contém": o
loader tem que achar exatamente o que foi plantado.

Decisões testadas (DC1-DC9, documentadas em `loaders_cliente.py`):
DC1 cancelamento, DC2 devolução, DC3 código genérico, DC4 item duplicado,
DC5 fardo, DC6 fornecedor principal, DC7 compra de emergência, DC8 custo,
DC9 saldo negativo.
"""

from __future__ import annotations

import shutil
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from motor.config import load_params
from motor.io.contracts import (
    ITEMS_PRIMARY_KEY,
    SALES_PRIMARY_KEY,
    STOCK_PRIMARY_KEY,
    SUPPLIERS_PRIMARY_KEY,
    Item,
    Sale,
    Stock,
    Supplier,
    validate_referential_integrity,
    validate_supplier_order_cadence,
    validate_table,
)
from motor.io.loaders_cliente import (
    ClientDataError,
    ClientLoadResult,
    CodeMerge,
    classify_supplier,
    client_params_for,
    load_client_tables,
    select_principal_suppliers,
)
from tests.cliente_helpers import (
    CLOSED_DAY,
    FIXTURE_DIR,
    PERIOD_END,
    PERIOD_START,
    S1,
    S2,
    S3,
    S4,
    STORE_CNPJ,
    STORE_ID,
    client_params,
    read_vendas,
)

PARAMS_PATH = Path(__file__).resolve().parent.parent / "config" / "params.yaml"


@pytest.fixture(scope="module")
def result() -> ClientLoadResult:
    return load_client_tables(
        FIXTURE_DIR, params=client_params(), store_id=STORE_ID, store_cnpj=STORE_CNPJ
    )


def _sale(result: ClientLoadResult, item_id: str, day: date) -> dict[str, object]:
    rows = result.sales.filter((pl.col("item_id") == item_id) & (pl.col("date") == day))
    assert rows.height == 1, f"esperava 1 linha de venda para {item_id} em {day}"
    return rows.row(0, named=True)


def _item(result: ClientLoadResult, item_id: str) -> dict[str, object]:
    rows = result.items.filter(pl.col("item_id") == item_id)
    assert rows.height == 1
    return rows.row(0, named=True)


# --------------------------------------------------------------------------
# contrato: as quatro tabelas passam na validação canônica
# --------------------------------------------------------------------------


def test_tabelas_passam_na_validacao_canonica(result: ClientLoadResult) -> None:
    validate_table(
        result.sales,
        Sale,
        table_name="sales",
        primary_key=SALES_PRIMARY_KEY,
        required_non_null=frozenset({"units_returned"}),
    )
    validate_table(
        result.items,
        Item,
        table_name="items",
        primary_key=ITEMS_PRIMARY_KEY,
        required_non_null=frozenset({"cost", "price_ref"}),
    )
    validate_table(
        result.suppliers, Supplier, table_name="suppliers", primary_key=SUPPLIERS_PRIMARY_KEY
    )
    validate_table(result.stock, Stock, table_name="stock", primary_key=STOCK_PRIMARY_KEY)
    validate_supplier_order_cadence(result.suppliers)
    validate_referential_integrity(
        items=result.items, suppliers=result.suppliers, sales=result.sales, stock=result.stock
    )


def test_conjunto_exato_de_itens(result: ClientLoadResult) -> None:
    esperado = {
        "1001", "1002", "1003", "1004", "1005", "1006", "1007", "1008",
        "1011", "1012", "1013", "1014", "1015", "1016", "1017",
    }  # fmt: skip
    assert set(result.items["item_id"]) == esperado
    # 1009 foi unido ao 1008 (DC4); 1018 não tem fornecedor em lugar nenhum (DC6)
    assert set(result.sales["item_id"]) == esperado


def test_determinismo(result: ClientLoadResult) -> None:
    again = load_client_tables(
        FIXTURE_DIR, params=client_params(), store_id=STORE_ID, store_cnpj=STORE_CNPJ
    )
    for name in ("sales", "items", "suppliers", "stock"):
        assert getattr(result, name).equals(getattr(again, name)), name
    assert result.report == again.report


# --------------------------------------------------------------------------
# DC1 cancelamento, DC2 devolução, vendas por dia
# --------------------------------------------------------------------------


def test_dc1_cancelamento_sai_das_vendas_e_e_contado(result: ClientLoadResult) -> None:
    row = _sale(result, "1001", date(2024, 3, 14))
    assert row["units_sold"] == 0.0  # só havia a linha cancelada naquele dia
    assert result.report.n_cancelled_rows == 1


def test_dc2_a_demanda_e_a_venda_bruta_a_devolucao_so_e_registrada(
    result: ClientLoadResult,
) -> None:
    """Devolução refere-se a uma compra de OUTRO dia e afeta o estoque, não a demanda:
    `units_sold` é a venda bruta (V), `units_returned` a devolução (D): uma não desconta a outra."""
    menor = _sale(result, "1001", date(2024, 3, 11))  # V 10 + D 3
    assert (menor["units_sold"], menor["units_returned"]) == (10.0, 3.0)
    maior = _sale(result, "1002", date(2024, 3, 12))  # V 2 + D 5
    assert (maior["units_sold"], maior["units_returned"]) == (2.0, 5.0)


def test_linhas_repetidas_do_pdv_no_mesmo_dia_somam(result: ClientLoadResult) -> None:
    assert _sale(result, "1002", date(2024, 3, 13))["units_sold"] == 5.0  # V 2 + V 3


def test_kg_com_virgula_decimal(result: ClientLoadResult) -> None:
    assert _sale(result, "1007", date(2024, 3, 15))["units_sold"] == pytest.approx(1.75)


def test_serie_diaria_densa_e_dia_fechado(result: ClientLoadResult) -> None:
    n_days = (PERIOD_END - PERIOD_START).days + 1  # 120
    um = result.sales.filter(pl.col("item_id") == "1001").sort("date")
    assert um.height == n_days
    assert um["date"].to_list() == [PERIOD_START + timedelta(days=i) for i in range(n_days)]
    fechado = result.sales.filter(pl.col("date") == CLOSED_DAY)
    assert fechado.height > 0
    assert fechado["is_operating_day"].to_list() == [False] * fechado.height
    assert fechado["units_sold"].sum() == 0.0
    aberto = result.sales.filter(pl.col("date") != CLOSED_DAY)
    assert aberto["is_operating_day"].all()
    assert not result.sales["is_anomaly"].any()
    assert set(result.sales["store_id"]) == {STORE_ID}


# --------------------------------------------------------------------------
# DC3 código genérico e código sem cadastro
# --------------------------------------------------------------------------


def test_dc3_codigo_generico_fica_fora_e_a_parcela_e_medida(result: ClientLoadResult) -> None:
    vendas = [r for r in read_vendas() if r.kind == "V"]
    total = sum(r.quantity * r.price for r in vendas)
    generico = sum(r.quantity * r.price for r in vendas if r.code == "9999")
    assert result.report.n_generic_rows == 11
    assert result.report.generic_revenue_share == pytest.approx(generico / total, rel=1e-12)
    assert "9999" not in set(result.sales["item_id"])


def test_codigo_sem_cadastro_e_listado(result: ClientLoadResult) -> None:
    assert result.report.orphan_codes == ("7777",)
    assert result.report.n_orphan_rows == 2
    assert "7777" not in set(result.sales["item_id"])


# --------------------------------------------------------------------------
# DC4 item duplicado
# --------------------------------------------------------------------------


def test_dc4_mesmo_ean_e_mesma_unidade_une_os_codigos(result: ClientLoadResult) -> None:
    assert result.report.merges == (CodeMerge(survivor="1008", merged="1009", ean="7891000000081"),)
    assert "1009" not in set(result.items["item_id"])
    soma: dict[date, float] = defaultdict(float)
    for r in read_vendas():
        if r.code in {"1008", "1009"} and r.kind == "V":
            soma[r.day] += r.quantity
    unido = result.sales.filter(pl.col("item_id") == "1008")
    for day, esperado in soma.items():
        assert _sale(result, "1008", day)["units_sold"] == esperado, day
    assert unido["units_sold"].sum() == pytest.approx(sum(soma.values()))


def test_dc4_mesmo_ean_com_unidade_diferente_nao_une(result: ClientLoadResult) -> None:
    ids = set(result.items["item_id"])
    assert {"1011", "1012"} <= ids
    assert all(m.survivor not in {"1011", "1012"} for m in result.report.merges)


def test_dc4_codigo_repetido_no_cadastro_a_ultima_linha_vence(result: ClientLoadResult) -> None:
    assert result.report.repeated_codes == ("1013",)
    assert _item(result, "1013")["description"] == "CAFE TORRADO 500G"
    linha = result.audit_inputs.filter(pl.col("item_id") == "1013").row(0, named=True)
    assert linha["cadastro_cost"] == pytest.approx(15.50)


# --------------------------------------------------------------------------
# DC6 fornecedor principal e DC7 compra de emergência
# --------------------------------------------------------------------------


def test_dc7_atacarejo_nao_vira_principal_mesmo_com_valor_maior(result: ClientLoadResult) -> None:
    # 1004: S1 comprou R$ 960 (nota antiga), o atacarejo S2 comprou R$ 1.800
    assert _item(result, "1004")["supplier_id"] == S1
    assert result.report.emergency_suppliers == (S2,)
    assert S2 not in set(result.suppliers["supplier_id"])


def test_dc6_fallback_para_o_fornecedor_do_cadastro(result: ClientLoadResult) -> None:
    for item_id, fornecedor in (("1007", S1), ("1013", S3)):  # nenhuma nota
        assert _item(result, item_id)["supplier_id"] == fornecedor
        linha = result.audit_inputs.filter(pl.col("item_id") == item_id).row(0, named=True)
        assert linha["supplier_source"] == "cadastro"
    linha = result.audit_inputs.filter(pl.col("item_id") == "1001").row(0, named=True)
    assert linha["supplier_source"] == "nota"


def test_dc6_item_sem_fornecedor_e_excluido_e_listado(result: ClientLoadResult) -> None:
    assert result.report.excluded_no_supplier == ("1018",)


def test_fornecedores_canonicos_vem_do_arquivo_da_entrevista(result: ClientLoadResult) -> None:
    sup = result.suppliers.sort("supplier_id")
    assert sup["supplier_id"].to_list() == [S3, S1, S4]  # lexicográfica; S2 (emergência) fora
    s1 = sup.filter(pl.col("supplier_id") == S1).row(0, named=True)
    assert s1["lead_time_days"] == 3
    assert s1["order_days"] == [1, 4]
    assert s1["review_period_days"] == 4
    assert s1["min_order_value"] == pytest.approx(500.0)
    assert s1["min_order_units"] == 0.0


def test_select_principal_exclui_emergencia_mesmo_com_valor_maior() -> None:
    d = date(2024, 4, 1)
    compras = pl.DataFrame(
        {
            "item_id": ["a", "a"],
            "supplier_id": ["S1", "S2"],
            "issued_on": [d, d],
            "value_rs": [100.0, 900.0],
            "is_emergency": [False, True],
        }
    )
    out = select_principal_suppliers(compras, window_days=90)
    assert out.to_dicts() == [{"item_id": "a", "supplier_id": "S1"}]


def test_select_principal_janela_ancorada_na_ultima_nota_dos_dados() -> None:
    compras = pl.DataFrame(
        {
            "item_id": ["a", "a", "b"],
            "supplier_id": ["S1", "S2", "S1"],
            "issued_on": [date(2024, 1, 1), date(2024, 4, 15), date(2024, 1, 1)],
            "value_rs": [5000.0, 100.0, 70.0],
            "is_emergency": [False, False, False],
        }
    )
    # âncora = 2024-04-15; janela de 90 dias começa em 2024-01-16: a compra grande
    # de S1 (2024-01-01) cai fora e S2 vence em "a"; "b" não tem nota na janela
    out = select_principal_suppliers(compras, window_days=90).sort("item_id")
    assert out.to_dicts() == [{"item_id": "a", "supplier_id": "S2"}]


def test_select_principal_desempate_compra_mais_recente_depois_menor_id() -> None:
    compras = pl.DataFrame(
        {
            "item_id": ["a", "a", "b", "b"],
            "supplier_id": ["S2", "S1", "S2", "S1"],
            "issued_on": [date(2024, 4, 10), date(2024, 4, 1), date(2024, 4, 1), date(2024, 4, 1)],
            "value_rs": [100.0, 100.0, 100.0, 100.0],
            "is_emergency": [False] * 4,
        }
    )
    out = select_principal_suppliers(compras, window_days=90).sort("item_id")
    assert out.to_dicts() == [
        {"item_id": "a", "supplier_id": "S2"},  # empate de valor: compra mais recente
        {"item_id": "b", "supplier_id": "S1"},  # empate total: menor supplier_id
    ]


@pytest.mark.parametrize(
    ("kind", "name", "cnae", "esperado"),
    [
        ("emergency", "DISTRIBUIDORA ALFA LTDA", None, True),  # explícito vence
        ("regular", "ATACADO DO ZE COMERCIO", None, False),  # explícito regular vence o padrão
        (None, "ATACADAO BETA ATACAREJO", None, True),  # padrão de nome
        ("", "atacarejo central", None, True),  # caixa baixa, tipo vazio
        (None, "DISTRIBUIDORA ALFA LTDA", "4639701", True),  # prefixo de CNAE
        (None, "DISTRIBUIDORA ALFA LTDA", "1011201", False),
        (None, "DISTRIBUIDORA ALFA LTDA", None, False),
    ],
)
def test_dc7_classificacao_de_emergencia(
    kind: str | None, name: str, cnae: str | None, esperado: bool
) -> None:
    assert classify_supplier(kind=kind, name=name, cnae=cnae, params=client_params()) is esperado


# --------------------------------------------------------------------------
# DC8 custo e DC5 fardo
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("item_id", "custo", "origem"),
    [
        ("1001", 18.00, "nfe_ultima_entrada"),
        # nota recente decide (não a antiga, 8,00): (1200 - 60 + 0 + 36) / 120
        ("1002", 9.80, "nfe_ultima_entrada"),
        # a nota do atacarejo (4,50) é mais nova, mas só vale a última nota REGULAR
        ("1004", 4.00, "nfe_ultima_entrada"),
        ("1006", 1.25, "nfe_ultima_entrada"),  # com IPI
        ("1007", 32.00, "cadastro"),  # sem nota
    ],
)
def test_dc8_custo_unitario_da_ultima_nota_regular(
    result: ClientLoadResult, item_id: str, custo: float, origem: str
) -> None:
    item = _item(result, item_id)
    assert item["cost"] == pytest.approx(custo)
    assert item["economics_origin"] == origem


def test_custo_da_ultima_nota_e_por_data_nao_por_ordem_de_arquivo(
    result: ClientLoadResult,
) -> None:
    # nota_1_recente.xml ordena ANTES de nota_3_antiga.xml, mas é a de 2024-04-08
    linha = result.audit_inputs.filter(pl.col("item_id") == "1002").row(0, named=True)
    assert linha["last_regular_nfe_date"] == date(2024, 4, 8)
    assert linha["last_regular_nfe_cost"] == pytest.approx(9.80)
    assert linha["cadastro_cost"] == pytest.approx(8.00)


@pytest.mark.parametrize(
    ("item_id", "fardo", "fonte"),
    [
        ("1001", 6.0, "nota"),
        ("1002", 12.0, "nota"),
        ("1004", 12.0, "nota"),  # caixa de 12 só na nota antiga, a única regular dele
        ("1005", 24.0, "cadastro"),  # uCom == uTrib: a nota não informa; cadastro vale
        ("1006", 10.0, "fornecedor"),  # nota não informa, cadastro vazio: fardo_padrao do S1
        ("1007", None, "desconhecido"),  # KG: fardo_padrao do fornecedor não se aplica
    ],
)
def test_dc5_fardo(result: ClientLoadResult, item_id: str, fardo: float | None, fonte: str) -> None:
    assert _item(result, item_id)["pack_multiple"] == fardo
    linha = result.audit_inputs.filter(pl.col("item_id") == item_id).row(0, named=True)
    assert linha["pack_source"] == fonte


def test_dc5_so_itens_com_nota_regular_que_nao_informa_o_fardo(
    result: ClientLoadResult,
) -> None:
    flagged = result.audit_inputs.filter(pl.col("nfe_pack_uninformative"))["item_id"]
    assert set(flagged) == {"1005", "1006"}


# --------------------------------------------------------------------------
# DC9 saldo e demais campos
# --------------------------------------------------------------------------


def test_dc9_saldo_negativo_vira_zero_e_e_contado(result: ClientLoadResult) -> None:
    saldos = dict(zip(result.stock["item_id"], result.stock["on_hand"], strict=True))
    assert saldos == {
        "1001": 30.0, "1002": 50.0, "1003": 80.0, "1004": 100.0, "1005": 40.0, "1006": 20.0,
        "1007": 12.5, "1008": 25.0, "1011": 3.0, "1012": 2.0, "1013": 60.0, "1014": 40.0,
        "1015": 5.0, "1016": 0.0, "1017": 0.0,
    }  # fmt: skip
    assert set(result.stock["date"]) == {PERIOD_END}  # fotografia na data do último dia de venda
    assert result.report.negative_stock_clamped == 1


def test_estoque_ausente_no_cadastro_gera_tabela_vazia(tmp_path: Path) -> None:
    shutil.copytree(FIXTURE_DIR, tmp_path / "c")
    cad = tmp_path / "c" / "cadastro.csv"
    header, *rows = [ln.split(";") for ln in cad.read_text(encoding="utf-8").splitlines()]
    col = header.index("saldo_estoque")
    for row in rows:
        row[col] = ""  # a coluna existe, mas nenhum item tem saldo informado
    linhas = [header, *rows]
    cad.write_text("\n".join(";".join(ln) for ln in linhas) + "\n", encoding="utf-8")
    out = load_client_tables(
        tmp_path / "c", params=client_params(), store_id=STORE_ID, store_cnpj=STORE_CNPJ
    )
    assert out.stock.height == 0
    assert set(out.stock.columns) == {"store_id", "item_id", "date", "on_hand", "in_transit"}


def test_campos_do_item(result: ClientLoadResult) -> None:
    arroz = _item(result, "1001")
    assert arroz["ean"] == "7891000000011"
    assert arroz["description"] == "ARROZ TIPO 1 5KG"
    assert arroz["category"] == "GROCERY"
    assert arroz["unit_of_sale"] == "unidade"
    assert arroz["is_perishable"] is False
    assert arroz["price_ref"] == pytest.approx(24.90)
    carne = _item(result, "1007")
    assert carne["unit_of_sale"] == "kg"
    assert carne["is_perishable"] is True


def test_nfe_de_outra_loja_e_ignorada_e_contada(tmp_path: Path, result: ClientLoadResult) -> None:
    shutil.copytree(FIXTURE_DIR, tmp_path / "c")
    nota = tmp_path / "c" / "nfe" / "nota_2_atacarejo.xml"
    nota.write_text(nota.read_text().replace(STORE_CNPJ, "99999999000199"), encoding="utf-8")
    out = load_client_tables(
        tmp_path / "c", params=client_params(), store_id=STORE_ID, store_cnpj=STORE_CNPJ
    )
    assert out.report.n_nfe_files == 3
    assert out.report.n_nfe_other_recipient == 1
    assert result.report.n_nfe_other_recipient == 0


def test_item_da_nota_sem_ean_no_cadastro_e_contado(tmp_path: Path) -> None:
    shutil.copytree(FIXTURE_DIR, tmp_path / "c")
    cad = tmp_path / "c" / "cadastro.csv"
    cad.write_text(cad.read_text().replace("7891000000016", "7891000009999"), encoding="utf-8")
    out = load_client_tables(
        tmp_path / "c", params=client_params(), store_id=STORE_ID, store_cnpj=STORE_CNPJ
    )
    assert out.report.n_nfe_items_unmatched == 1  # a esponja da nota B não casa mais


# --------------------------------------------------------------------------
# entrada suja de verdade falha alto, com mensagem útil
# --------------------------------------------------------------------------


def test_coluna_obrigatoria_ausente_levanta_erro_nomeando_arquivo_e_coluna(
    tmp_path: Path,
) -> None:
    shutil.copytree(FIXTURE_DIR, tmp_path / "c")
    cad = tmp_path / "c" / "cadastro.csv"
    cad.write_text(cad.read_text().replace("codigo;", "cod;", 1), encoding="utf-8")
    with pytest.raises(ClientDataError, match=r"cadastro\.csv.*codigo"):
        load_client_tables(
            tmp_path / "c", params=client_params(), store_id=STORE_ID, store_cnpj=STORE_CNPJ
        )


def test_tipo_de_movimento_desconhecido_levanta_erro(tmp_path: Path) -> None:
    shutil.copytree(FIXTURE_DIR, tmp_path / "c")
    vendas = tmp_path / "c" / "vendas.csv"
    vendas.write_text(vendas.read_text().replace(";C\n", ";X\n"), encoding="utf-8")
    with pytest.raises(ClientDataError, match=r"tipo.*X"):
        load_client_tables(
            tmp_path / "c", params=client_params(), store_id=STORE_ID, store_cnpj=STORE_CNPJ
        )


# --------------------------------------------------------------------------
# insumos do modo `canonical` da lista de compra (Sprint 22, fase 2)
# --------------------------------------------------------------------------


def test_pedidos_em_aberto_viram_tabela_e_codigo_desconhecido_e_contado(
    result: ClientLoadResult,
) -> None:
    assert result.open_orders is not None
    rows = {
        (r["item_id"], r["supplier_id"], r["quantity"], r["expected_date"])
        for r in result.open_orders.iter_rows(named=True)
    }
    d = date(2024, 5, 2)
    assert rows == {("1001", S1, 60.0, d), ("1002", S1, 120.0, d), ("1007", S1, 25.5, d)}
    assert result.report.n_open_orders_unmatched == 1  # o código 8888


def test_sem_arquivo_de_pedidos_a_tabela_e_none_nao_vazia(tmp_path: Path) -> None:
    """Ausência do arquivo (não sabemos o que está a caminho) é diferente de
    arquivo vazio (sabemos que nada está)."""
    shutil.copytree(FIXTURE_DIR, tmp_path / "c")
    (tmp_path / "c" / "pedidos_em_aberto.csv").unlink()
    out = load_client_tables(
        tmp_path / "c", params=client_params(), store_id=STORE_ID, store_cnpj=STORE_CNPJ
    )
    assert out.open_orders is None


def test_historico_real_de_compras_vem_das_notas(result: ClientLoadResult) -> None:
    arroz = result.purchases.filter(pl.col("item_id") == "1001").sort("date")
    assert arroz["date"].to_list() == [date(2024, 2, 5), date(2024, 4, 8)]
    assert arroz["units"].to_list() == [60.0, 30.0]
    # a compra de emergência também é compra real, e entra no histórico
    leite = result.purchases.filter(pl.col("item_id") == "1004").sort("date")
    assert leite["units"].to_list() == [240.0, 400.0]


def test_validade_dias_opcional_chega_na_auditoria_de_entrada(result: ClientLoadResult) -> None:
    vida = dict(
        zip(result.audit_inputs["item_id"], result.audit_inputs["shelf_life_days"], strict=True)
    )
    assert vida["1004"] == 180.0
    assert vida["1007"] == 5.0
    assert vida["1011"] is None
    assert vida["1001"] is None


def test_client_params_for_deriva_validade_loja_e_datas(result: ClientLoadResult) -> None:
    base = load_params(PARAMS_PATH)
    derived = client_params_for(base, result)
    vida = derived.guardrails.shelf_life_days_by_category
    assert vida["MEATS"] == 5  # validade informada
    # DAIRY: mínimo da categoria -- 1004 informa 180, mas 1011/1012 são perecíveis SEM
    # validade e caem no default perecível de config (7): vale o mais conservador
    assert vida["DAIRY"] == 7
    assert vida["GROCERY"] == 365  # não perecível, sem informação: default de config
    assert set(vida) >= {"MEATS", "DAIRY", "GROCERY", "BEVERAGES", "CLEANING"}
    assert derived.canonical.window_start == PERIOD_START
    assert derived.canonical.window_end == PERIOD_END
    assert derived.simulation.end_date == PERIOD_END
    assert derived.simulation.start_date == PERIOD_START + timedelta(
        days=base.client_loader.simulation_start_after_days
    )
    # nada além do necessário muda: o resto do Params é o do Favorita, intacto
    assert derived.economics == base.economics

"""Testes dos contratos das tabelas canônicas (motor.io.contracts).

Cada teste de erro afirma não só que a validação falhou, mas que a mensagem
nomeia a coluna e a regra certas -- `pytest.raises(SchemaValidationError)`
sozinho não vale, porque passaria mesmo com uma mensagem inútil.
"""

from datetime import date

import polars as pl
import pytest

from motor.io.contracts import (
    ITEMS_PRIMARY_KEY,
    SALES_PRIMARY_KEY,
    STOCK_PRIMARY_KEY,
    SUPPLIERS_PRIMARY_KEY,
    Item,
    Sale,
    SchemaValidationError,
    Stock,
    Supplier,
    max_cyclic_order_gap,
    validate_referential_integrity,
    validate_supplier_order_cadence,
    validate_table,
)

# --------------------------------------------------------------------------
# DataFrames válidos mínimos, escritos à mão
# --------------------------------------------------------------------------


def valid_sales() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "store_id": ["1", "1"],
            "item_id": ["A", "B"],
            "date": [date(2024, 1, 1), date(2024, 1, 1)],
            "units_sold": [10.0, 0.0],
            "units_returned": [None, 1.0],
            "on_promo": [False, True],
            "price": [None, 5.5],
            "is_operating_day": [True, True],
            "is_anomaly": [False, False],
            "anomaly_reason": [None, None],
        }
    )


def valid_items() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "item_id": ["A", "B"],
            "ean": [None, None],
            "description": ["Item A", "Item B"],
            "category": ["mercearia", "mercearia"],
            "item_class": [None, None],
            "supplier_id": ["S1", "S1"],
            "unit_of_sale": ["unidade", "kg"],
            "pack_multiple": [None, None],
            "is_perishable": [False, True],
            "is_anchor": [True, False],
            "cost": [None, None],
            "price_ref": [None, None],
            "economics_origin": ["arbitrado: teste", "arbitrado: teste"],
        }
    )


def valid_suppliers() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "supplier_id": ["S1"],
            "lead_time_days": [3],
            "order_days": [[1, 4]],
            "review_period_days": [4],
            "min_order_value": [100.0],
            "min_order_units": [0.0],
        }
    )


def valid_stock() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "store_id": ["1"],
            "item_id": ["A"],
            "date": [date(2024, 1, 1)],
            "on_hand": [10.0],
            "in_transit": [None],
        }
    )


class TestExemplosValidos:
    def test_sales_valido_passa(self) -> None:
        validate_table(valid_sales(), Sale, table_name="sales", primary_key=SALES_PRIMARY_KEY)

    def test_items_valido_passa(self) -> None:
        validate_table(valid_items(), Item, table_name="items", primary_key=ITEMS_PRIMARY_KEY)

    def test_suppliers_valido_passa(self) -> None:
        validate_table(
            valid_suppliers(), Supplier, table_name="suppliers", primary_key=SUPPLIERS_PRIMARY_KEY
        )

    def test_stock_valido_passa(self) -> None:
        validate_table(valid_stock(), Stock, table_name="stock", primary_key=STOCK_PRIMARY_KEY)


# --------------------------------------------------------------------------
# Violações estruturais: coluna faltando, coluna a mais, dtype errado
# --------------------------------------------------------------------------


class TestViolacoesEstruturais:
    def test_coluna_faltando(self) -> None:
        df = valid_sales().drop("price")
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_table(df, Sale, table_name="sales", primary_key=SALES_PRIMARY_KEY)
        message = str(exc_info.value)
        assert "price" in message
        assert "ausente" in message

    def test_coluna_a_mais(self) -> None:
        df = valid_sales().with_columns(pl.lit("x").alias("coluna_inesperada"))
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_table(df, Sale, table_name="sales", primary_key=SALES_PRIMARY_KEY)
        message = str(exc_info.value)
        assert "coluna_inesperada" in message
        assert "não declarada" in message

    def test_dtype_errado_string_onde_espera_float(self) -> None:
        df = valid_sales().with_columns(pl.Series("units_sold", ["dez", "cinco"]))
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_table(df, Sale, table_name="sales", primary_key=SALES_PRIMARY_KEY)
        message = str(exc_info.value)
        assert "units_sold" in message
        assert "tipo incompatível" in message

    def test_dtype_float_onde_espera_int_e_erro(self) -> None:
        """Tolerância de dtype é em uma direção só: int->float ok, float->int não."""
        df = valid_suppliers().with_columns(pl.Series("lead_time_days", [3.5]))
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_table(df, Supplier, table_name="suppliers", primary_key=SUPPLIERS_PRIMARY_KEY)
        message = str(exc_info.value)
        assert "lead_time_days" in message
        assert "tipo incompatível" in message

    def test_dtype_int_onde_espera_float_e_aceito(self) -> None:
        """Upcast seguro: coluna int satisfaz contrato float."""
        df = valid_sales().with_columns(pl.Series("units_sold", [10, 0]))
        validate_table(df, Sale, table_name="sales", primary_key=SALES_PRIMARY_KEY)


# --------------------------------------------------------------------------
# Nulo indevido, restrição numérica, enumeração, chave duplicada
# --------------------------------------------------------------------------


class TestViolacoesDeValor:
    def test_nulo_indevido_em_campo_obrigatorio(self) -> None:
        df = valid_sales().with_columns(pl.Series("units_sold", [10.0, None]))
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_table(df, Sale, table_name="sales", primary_key=SALES_PRIMARY_KEY)
        message = str(exc_info.value)
        assert "units_sold" in message
        assert "nulos não permitidos" in message

    def test_nao_negatividade_de_units_sold(self) -> None:
        df = valid_sales().with_columns(pl.Series("units_sold", [10.0, -1.0]))
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_table(df, Sale, table_name="sales", primary_key=SALES_PRIMARY_KEY)
        message = str(exc_info.value)
        assert "units_sold" in message
        assert "não-negatividade" in message
        assert "-1.0" in message  # amostra da linha ofensora

    def test_on_hand_negativo_e_rejeitado(self) -> None:
        df = valid_stock().with_columns(pl.Series("on_hand", [-5.0]))
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_table(df, Stock, table_name="stock", primary_key=STOCK_PRIMARY_KEY)
        message = str(exc_info.value)
        assert "on_hand" in message
        assert "não-negatividade" in message

    def test_enumeracao_fechada_de_unit_of_sale(self) -> None:
        df = valid_items().with_columns(pl.Series("unit_of_sale", ["litro", "kg"]))
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_table(df, Item, table_name="items", primary_key=ITEMS_PRIMARY_KEY)
        message = str(exc_info.value)
        assert "unit_of_sale" in message
        assert "unidade" in message and "kg" in message  # valores permitidos citados

    def test_chave_primaria_duplicada(self) -> None:
        df = valid_sales().with_columns(pl.Series("item_id", ["A", "A"]))
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_table(df, Sale, table_name="sales", primary_key=SALES_PRIMARY_KEY)
        message = str(exc_info.value)
        assert "chave primária duplicada" in message
        assert "store_id" in message

    def test_pack_multiple_deve_ser_positivo(self) -> None:
        df = valid_items().with_columns(pl.Series("pack_multiple", [0.0, 1.0]))
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_table(df, Item, table_name="items", primary_key=ITEMS_PRIMARY_KEY)
        message = str(exc_info.value)
        assert "pack_multiple" in message
        assert "> 0.0" in message

    def test_order_days_elemento_fora_do_intervalo_iso(self) -> None:
        df = valid_suppliers().with_columns(pl.Series("order_days", [[1, 9]]))
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_table(df, Supplier, table_name="suppliers", primary_key=SUPPLIERS_PRIMARY_KEY)
        message = str(exc_info.value)
        assert "order_days" in message
        assert "<= 7" in message

    def test_order_days_vazio_viola_tamanho_minimo(self) -> None:
        df = valid_suppliers().with_columns(pl.Series("order_days", [[]]))
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_table(df, Supplier, table_name="suppliers", primary_key=SUPPLIERS_PRIMARY_KEY)
        message = str(exc_info.value)
        assert "order_days" in message
        assert "ao menos 1" in message


# --------------------------------------------------------------------------
# Gancho required_non_null (ponto 5 da revisão da Sprint 1)
# --------------------------------------------------------------------------


class TestRequiredNonNullGancho:
    def test_campo_nulavel_permanece_opcional_por_padrao(self) -> None:
        validate_table(valid_items(), Item, table_name="items", primary_key=ITEMS_PRIMARY_KEY)

    def test_required_non_null_promove_campo_a_obrigatorio(self) -> None:
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_table(
                valid_items(),
                Item,
                table_name="items",
                primary_key=ITEMS_PRIMARY_KEY,
                required_non_null=frozenset({"cost"}),
            )
        message = str(exc_info.value)
        assert "cost" in message
        assert "nulos não permitidos" in message

    def test_required_non_null_com_coluna_desconhecida_falha_alto(self) -> None:
        with pytest.raises(ValueError, match="nao_existe"):
            validate_table(
                valid_items(),
                Item,
                table_name="items",
                primary_key=ITEMS_PRIMARY_KEY,
                required_non_null=frozenset({"nao_existe"}),
            )


# --------------------------------------------------------------------------
# Integridade referencial, nas duas direções
# --------------------------------------------------------------------------


class TestIntegridadeReferencial:
    def test_referencias_validas_passam(self) -> None:
        validate_referential_integrity(
            items=valid_items(),
            suppliers=valid_suppliers(),
            sales=valid_sales(),
            stock=valid_stock(),
        )

    def test_item_referencia_fornecedor_inexistente(self) -> None:
        items = valid_items().with_columns(pl.Series("supplier_id", ["S_FANTASMA", "S1"]))
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_referential_integrity(items=items, suppliers=valid_suppliers())
        message = str(exc_info.value)
        assert "supplier_id" in message
        assert "inexistente em suppliers" in message

    def test_venda_referencia_item_inexistente(self) -> None:
        sales = valid_sales().with_columns(pl.Series("item_id", ["ITEM_FANTASMA", "B"]))
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_referential_integrity(
                items=valid_items(), suppliers=valid_suppliers(), sales=sales
            )
        message = str(exc_info.value)
        assert "item_id" in message
        assert "inexistente em items" in message

    def test_estoque_referencia_item_inexistente(self) -> None:
        stock = valid_stock().with_columns(pl.Series("item_id", ["ITEM_FANTASMA"]))
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_referential_integrity(
                items=valid_items(), suppliers=valid_suppliers(), stock=stock
            )
        message = str(exc_info.value)
        assert "item_id" in message
        assert "inexistente em items" in message


# --------------------------------------------------------------------------
# Consistência order_days / review_period_days
# --------------------------------------------------------------------------


class TestConsistenciaCadenciaFornecedor:
    @pytest.mark.parametrize(
        ("order_days", "expected_gap"),
        [
            ([1, 4], 4),  # segunda e quinta: 3 dias até quinta, 4 dias de volta à segunda
            ([1, 2, 3, 4, 5, 6, 7], 1),  # todo dia: intervalo mínimo possível
            ([1], 7),  # um único dia por semana: o ciclo inteiro
        ],
    )
    def test_max_cyclic_order_gap(self, order_days: list[int], expected_gap: int) -> None:
        assert max_cyclic_order_gap(order_days) == expected_gap

    def test_cadencia_consistente_passa(self) -> None:
        validate_supplier_order_cadence(valid_suppliers())

    def test_cadencia_inviavel_e_rejeitada(self) -> None:
        df = valid_suppliers().with_columns(pl.Series("review_period_days", [3]))
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_supplier_order_cadence(df)
        message = str(exc_info.value)
        assert "review_period_days" in message
        assert "cadência de revisão inviável" in message

    def test_cadencia_no_limite_exato_passa(self) -> None:
        """review_period_days == max_gap é suficiente, não precisa sobrar folga."""
        df = valid_suppliers().with_columns(pl.Series("review_period_days", [4]))
        validate_supplier_order_cadence(df)

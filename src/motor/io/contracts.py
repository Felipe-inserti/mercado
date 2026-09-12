"""Schemas pydantic das quatro tabelas canônicas, e a validação vetorizada delas.

Todo dataset de entrada é normalizado para `sales`, `items`, `suppliers` e
`stock` antes de qualquer outra coisa (CLAUDE.md, seção 4). Este módulo define
o contrato de uma linha de cada tabela e uma função que verifica um
`pl.DataFrame` inteiro contra esse contrato, de forma vetorizada -- o volume
real do projeto não cabe em validação linha a linha.

O schema polars esperado é sempre derivado do modelo pydantic
(`expected_polars_schema`), nunca escrito à mão em paralelo: duas definições
da mesma coisa divergem, e sempre no pior momento.
"""

from __future__ import annotations

import itertools
import textwrap
import types
import typing
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Final

import polars as pl
from annotated_types import Ge, Gt, Le, Lt, MinLen
from polars.datatypes import DataType, DataTypeClass
from pydantic import BaseModel, ConfigDict

PolarsDtype = DataTypeClass | DataType
"""Um dtype polars, como classe (`pl.Int64`) ou instância parametrizada (`pl.List(pl.Int64)`)."""

# --------------------------------------------------------------------------
# Tipos de campo reutilizáveis
# --------------------------------------------------------------------------

NonNegativeFloat = Annotated[float, Ge(0.0)]
PositiveFloat = Annotated[float, Gt(0.0)]
PositiveInt = Annotated[int, Gt(0)]
IsoWeekday = Annotated[int, Ge(1), Le(7)]  # 1 = segunda .. 7 = domingo


class UnitOfSale(StrEnum):
    """Unidade de venda do item: por unidade discreta ou por peso.

    Esta é a distinção que decide se o arredondamento de fardo se aplica ao
    item (CLAUDE.md, seção 8: item vendido por peso é parte da narrativa da
    demo, não um caso de borda a esconder).
    """

    UNIDADE = "unidade"
    PESO = "kg"


class TableRow(BaseModel):
    """Classe-base das quatro tabelas canônicas.

    Imutável (`frozen`), sem colunas além do contrato (`extra="forbid"`:
    coluna inesperada é erro, não aviso -- é assim que cadastro sujo de
    cliente aparece cedo), e validação estrita de tipos.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


# --------------------------------------------------------------------------
# sales
# --------------------------------------------------------------------------


class Sale(TableRow):
    """Uma linha de venda no grão loja x item x dia.

    `units_returned` é uma coluna própria e nulável -- devolução não é venda
    negativa. A Sprint 3 (`motor.io.loaders`) decompõe o líquido diário do
    Favorita em `units_sold = max(0, x)` e `units_returned = -min(0, x)` e
    passa a popular `units_returned` sempre (0.0 nos dias sem devolução), via
    `required_non_null={"units_returned"}` em `validate_table` -- o campo
    continua nulável no contrato porque outra fonte de dado pode não ter essa
    decomposição. Limitação registrada para a Sprint 17: isto é decomposição
    do LÍQUIDO, não reconstrução do bruto -- um dia com `units_sold > 0` pode
    conter devolução embutida e invisível, se venda e devolução ocorreram no
    mesmo dia.

    `on_promo` é nulável: `null` significa "não se sabe" (linha criada pelo
    reindex da Sprint 3, ou dado bruto anterior a 2014-04, quando o Favorita
    ainda não registrava promoção) -- nunca inventar `False`, que significaria
    "sabidamente sem promoção".

    `is_operating_day`, `is_anomaly` e `anomaly_reason` nascem no reindex da
    Sprint 3:

    - `is_operating_day` é atributo de (`store_id`, `date`), replicado em toda
      linha de item daquela loja naquele dia -- não varia por item. `False`
      marca um dia em que nenhuma linha de nenhum item foi registrada para a
      loja no bruto (loja fechada), não um zero de demanda normal.
    - `is_anomaly`/`anomaly_reason` marcam período de distorção conhecida
      (ex.: terremoto do Equador em 2016-04-16) sem apagar a linha -- quem
      consome decide se exclui.

    `price` é nulável porque o dataset público (Favorita) não traz preço
    praticado. A ausência é uma premissa ativa a ser declarada no relatório
    do experimento, não escondida (CLAUDE.md, seção 4).
    """

    store_id: str
    item_id: str
    date: date
    units_sold: NonNegativeFloat
    units_returned: NonNegativeFloat | None = None
    on_promo: bool | None = None
    price: NonNegativeFloat | None = None
    is_operating_day: bool
    is_anomaly: bool
    anomaly_reason: str | None = None


SALES_PRIMARY_KEY: Final = ("store_id", "item_id", "date")


# --------------------------------------------------------------------------
# stock
# --------------------------------------------------------------------------


class Stock(TableRow):
    """Uma linha de saldo de estoque no grão loja x item x dia.

    Esta é a tabela que o dado público (Favorita) não tem. A ausência deve
    ser declarada explicitamente na saída do experimento, nunca assumida em
    silêncio (CLAUDE.md, seção 4).

    `on_hand` é forçado a ser >= 0 de propósito. Em ERP real, saldo negativo
    é comum (venda lançada sem entrada correspondente registrada) -- é o
    análogo de venda negativa em `sales`. O canônico não absorve esse ruído:
    força a camada de ingestão a decidir explicitamente o que fazer com ele.
    Essa decisão é de uma sprint futura; o dado público nem tem estoque.
    """

    store_id: str
    item_id: str
    date: date
    on_hand: NonNegativeFloat
    in_transit: NonNegativeFloat | None = None


STOCK_PRIMARY_KEY: Final = ("store_id", "item_id", "date")


# --------------------------------------------------------------------------
# items
# --------------------------------------------------------------------------


class Item(TableRow):
    """Uma linha de cadastro no grão item.

    `ean`, `pack_multiple` são nuláveis porque o dataset público não os tem.
    Depois da arbitragem (sprint futura), passam a ser obrigatórios: use
    `required_non_null` em `validate_table` para essa transição, sem reabrir
    este contrato -- é exatamente o que a Sprint 16.5 (Etapa 3.2) fez com
    `cost`/`price_ref` abaixo, o primeiro campo a fazer essa travessia.

    `pack_multiple` mora aqui, não em `suppliers`: é propriedade do SKU, não
    do fornecedor -- dois itens do mesmo fornecedor podem ter fardos
    diferentes (uma Coca de 2L em fardo de 6, um arroz de 5kg em fardo de
    10). Modelar como atributo único por fornecedor geraria arredondamento
    de fardo errado assim que houvesse mais de um item por fornecedor, que é
    o caso normal.

    `description` e `is_anchor` são nuláveis (Sprint 3, D7): o Favorita não
    tem descrição de produto nem conceito de item-âncora, e a decisão foi não
    inventar um proxy (por volume, por exemplo) que atribuiria significado de
    negócio que o dado não carrega. Ficam `null` até a arbitragem com dado
    real de um cliente.

    `cost`/`price_ref` (Sprint 16.5, Etapa 3.2): eram `null` pela mesma razão
    D7 acima -- Favorita não tem custo nem preço -- e agora são
    `required_non_null` em `validate_table(items_df, Item, ...)`, DERIVADOS
    da premissa de margem por categoria (`motor.io.loaders.load_items`).
    `economics_origin` é obrigatório e viaja com o valor: um leitor do
    parquet, sem abrir manifesto nenhum, vê ali mesmo que a coluna é
    arbitrada, não observada -- é a razão inteira de a Etapa 3.1
    (`motor.assumptions`) existir aplicada ao próprio dado, não só ao
    registro em separado.
    """

    item_id: str
    ean: str | None = None
    description: str | None = None
    category: str
    item_class: str | None = None
    supplier_id: str
    unit_of_sale: UnitOfSale
    pack_multiple: PositiveFloat | None = None
    is_perishable: bool
    is_anchor: bool | None = None
    cost: NonNegativeFloat | None = None
    price_ref: NonNegativeFloat | None = None
    economics_origin: str


ITEMS_PRIMARY_KEY: Final = ("item_id",)


# --------------------------------------------------------------------------
# suppliers
# --------------------------------------------------------------------------


class Supplier(TableRow):
    """Uma linha de cadastro no grão fornecedor.

    `order_days` e `review_period_days` são fontes de verdade
    independentes, de propósito -- não derive uma da outra:

    - `order_days`: restrição do fornecedor. Em que dias da semana (ISO,
      1=segunda .. 7=domingo) ele aceita pedido.
    - `review_period_days`: cadência de decisão nossa. De quanto em quanto
      tempo revisamos aquele fornecedor. Um fornecedor que aceita pedido
      todo dia pode ser revisado semanalmente; outro que só aceita segunda
      nos força a revisar de 7 em 7 dias.

    A janela de risco da previsão (Sprint 11) NÃO usa `review_period_days`
    diretamente -- usa lead_time + o intervalo real até a próxima entrega
    viável, que sai do cruzamento dos dois campos e varia com a data de
    decisão (um fornecedor que aceita pedido segunda e quinta tem intervalo
    de 3 dias a partir da segunda e de 4 dias a partir da quinta). Usar um
    escalar fixo nos dois casos cobre a menos em um deles -- ruptura
    estrutural por janela mal calculada é o erro mais comum deste tipo de
    sistema (CLAUDE.md, seção 8). Aqui só garantimos que o contrato carrega
    os dois campos separadamente e que eles são consistentes entre si -- ver
    `validate_supplier_order_cadence`. O cálculo do intervalo real é da
    Sprint 11.

    `min_order_value` e `min_order_units` (Sprint 10) são independentes: um
    fornecedor pode ter só um dos dois configurado, os dois, ou nenhum.
    `0.0` significa "sem restrição" nos dois casos -- não nulo, mesmo padrão
    dos dois campos, checados com semântica AND por
    `motor.policy.supplier.apply_supplier_constraints` (os dois, quando > 0,
    precisam ser atingidos).
    """

    supplier_id: str
    lead_time_days: PositiveInt
    order_days: Annotated[list[IsoWeekday], MinLen(1)]
    review_period_days: PositiveInt
    min_order_value: NonNegativeFloat
    min_order_units: NonNegativeFloat


SUPPLIERS_PRIMARY_KEY: Final = ("supplier_id",)


# --------------------------------------------------------------------------
# Relatório de violações
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    """Uma violação de contrato: coluna, regra, quantas linhas violam, e amostra das ofensoras.

    `count` e `sample` ficam `None` para violações estruturais (coluna
    ausente ou coluna extra), onde "quantas linhas" não faz sentido -- o
    problema é da tabela inteira, não de um subconjunto de linhas.
    """

    column: str
    rule: str
    count: int | None
    sample: pl.DataFrame | None


class SchemaValidationError(ValueError):
    """Erro de validação de uma tabela canônica.

    A mensagem lista todas as violações encontradas, não só a primeira: é
    isso que faz dela útil como auditoria de cadastro (a primeira entrega
    comercial do produto num cliente real, CLAUDE.md seção 6), e não só um
    sinal de "algo deu errado".
    """

    def __init__(self, table: str, violations: list[Violation]) -> None:
        self.table = table
        self.violations = violations
        super().__init__(self._render())

    def _render(self) -> str:
        header = (
            f"Validação da tabela '{self.table}' falhou com {len(self.violations)} problema(s):"
        )
        lines = [header]
        for v in self.violations:
            count_part = f" ({v.count} linha(s))" if v.count is not None else ""
            lines.append(f"- coluna '{v.column}': {v.rule}{count_part}")
            if v.sample is not None and v.sample.height > 0:
                lines.append(textwrap.indent(str(v.sample), "    "))
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Derivação de schema polars a partir do modelo pydantic
# --------------------------------------------------------------------------

_PRIMITIVE_DTYPES: dict[type, PolarsDtype] = {
    str: pl.String,
    int: pl.Int64,
    float: pl.Float64,
    bool: pl.Boolean,
    date: pl.Date,
}

_INT_DTYPES = frozenset(
    {pl.Int8, pl.Int16, pl.Int32, pl.Int64, pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64}
)
_FLOAT_DTYPES = frozenset({pl.Float32, pl.Float64})


def _unwrap_optional(annotation: Any) -> Any:
    """Remove o `| None` de uma anotação, se houver, retornando o tipo de dentro."""
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _strip_annotated(annotation: Any) -> tuple[Any, tuple[Any, ...]]:
    """Separa `Annotated[X, *metadata]` em `(X, metadata)`. Sem Annotated, metadata é vazia."""
    metadata = getattr(annotation, "__metadata__", None)
    if metadata is not None:
        return typing.get_args(annotation)[0], tuple(metadata)
    return annotation, ()


def _dtype_for_primitive(base_type: Any) -> PolarsDtype:
    if isinstance(base_type, type) and issubclass(base_type, StrEnum):
        return pl.String
    if base_type in _PRIMITIVE_DTYPES:
        return _PRIMITIVE_DTYPES[base_type]
    msg = f"tipo Python sem mapeamento polars conhecido: {base_type!r}"
    raise TypeError(msg)


def _polars_dtype_for_field(model: type[BaseModel], field_name: str) -> PolarsDtype:
    annotation = _unwrap_optional(model.model_fields[field_name].annotation)
    base_type, _ = _strip_annotated(annotation)

    if typing.get_origin(base_type) is list:
        (inner,) = typing.get_args(base_type)
        inner_base, _ = _strip_annotated(inner)
        return pl.List(_dtype_for_primitive(inner_base))

    return _dtype_for_primitive(base_type)


def expected_polars_schema(model: type[BaseModel]) -> dict[str, PolarsDtype]:
    """Deriva o schema polars esperado (coluna -> dtype) a partir do modelo pydantic.

    Não codifica nullability: toda coluna polars é nullable, e
    obrigatoriedade é uma verificação separada por contagem de nulos (ver
    `validate_table`), não uma propriedade de dtype.
    """
    return {name: _polars_dtype_for_field(model, name) for name in model.model_fields}


def _dtype_is_compatible(actual: PolarsDtype, expected: PolarsDtype) -> bool:
    """Compatibilidade em uma direção só.

    Int onde se espera float é aceito (upcast seguro). Float onde se espera
    int é erro: aceitar os dois lados deixaria passar truncamento
    silencioso, e num projeto de estoque isso vira quantidade errada sem
    nenhum sinal.

    Uma coluna inteiramente nula é inferida pelo polars como dtype `Null`
    (não carrega nenhum valor para tipar) -- compatível com qualquer dtype
    esperado, nunca um erro por si só.
    """
    if actual == pl.Null:
        return True
    if actual == expected:
        return True
    if isinstance(expected, pl.List) and isinstance(actual, pl.List):
        return _dtype_is_compatible(actual.inner, expected.inner)
    if expected in _FLOAT_DTYPES:
        return actual in _FLOAT_DTYPES or actual in _INT_DTYPES
    if expected in _INT_DTYPES:
        return actual in _INT_DTYPES
    return False


def _default_required_columns(model: type[BaseModel]) -> set[str]:
    """Colunas que o próprio modelo já declara como não-nuláveis (sem `| None`)."""
    required = set()
    for name, field in model.model_fields.items():
        annotation = field.annotation
        origin = typing.get_origin(annotation)
        args = typing.get_args(annotation)
        is_optional = origin in (typing.Union, types.UnionType) and type(None) in args
        if not is_optional:
            required.add(name)
    return required


# --------------------------------------------------------------------------
# Restrições numéricas (Ge/Gt/Le/Lt) extraídas do pydantic
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Bound:
    op: str  # "ge" | "gt" | "le" | "lt"
    value: float

    def violates(self, col: str) -> pl.Expr:
        if self.op == "ge":
            return pl.col(col) < self.value
        if self.op == "gt":
            return pl.col(col) <= self.value
        if self.op == "le":
            return pl.col(col) > self.value
        return pl.col(col) >= self.value  # "lt"

    def violates_list_element(self, col: str) -> pl.Expr:
        elem = pl.element()
        if self.op == "ge":
            cond = elem < self.value
        elif self.op == "gt":
            cond = elem <= self.value
        elif self.op == "le":
            cond = elem > self.value
        else:  # "lt"
            cond = elem >= self.value
        return pl.col(col).list.eval(cond).list.any()

    def describe(self) -> str:
        symbol = {"ge": ">=", "gt": ">", "le": "<=", "lt": "<"}[self.op]
        suffix = " (não-negatividade)" if self.op == "ge" and self.value == 0 else ""
        return f"deve ser {symbol} {self.value}{suffix}"


def _extract_bounds(metadata: Sequence[Any]) -> list[_Bound]:
    """Extrai restrições Ge/Gt/Le/Lt.

    O tipo de `annotated_types` é um protocolo genérico de comparação
    (`SupportsGe` etc., cobre até datas), mas neste projeto os únicos campos
    com esses metadados são numéricos -- daí o `cast` para `float`.
    """
    bounds = []
    for m in metadata:
        if isinstance(m, Ge):
            bounds.append(_Bound("ge", typing.cast("float", m.ge)))
        elif isinstance(m, Gt):
            bounds.append(_Bound("gt", typing.cast("float", m.gt)))
        elif isinstance(m, Le):
            bounds.append(_Bound("le", typing.cast("float", m.le)))
        elif isinstance(m, Lt):
            bounds.append(_Bound("lt", typing.cast("float", m.lt)))
    return bounds


def _min_len_for(metadata: Sequence[Any]) -> int | None:
    for m in metadata:
        if isinstance(m, MinLen):
            return m.min_length
    return None


def _field_base_and_metadata(
    model: type[BaseModel], field_name: str
) -> tuple[Any, tuple[Any, ...]]:
    """Resolve tipo base e metadados de um campo, combinando as duas fontes do pydantic.

    Para um campo obrigatório (`Annotated[X, *meta]`), o pydantic já promove
    `meta` para `field.metadata` e reduz `field.annotation` a `X`. Para um
    campo opcional (`Annotated[X, *meta] | None`), essa promoção não
    acontece: `meta` permanece dentro de `field.annotation`, e
    `field.metadata` fica vazio. Combinar as duas fontes cobre os dois casos
    sem duplicar restrição.
    """
    field = model.model_fields[field_name]
    annotation = _unwrap_optional(field.annotation)
    base_type, inline_metadata = _strip_annotated(annotation)
    return base_type, (*field.metadata, *inline_metadata)


# --------------------------------------------------------------------------
# Validação vetorizada de uma tabela -- uma função isolada por tipo de regra
# --------------------------------------------------------------------------


def _column_presence_violations(expected_cols: set[str], actual_cols: set[str]) -> list[Violation]:
    violations = []
    for col in sorted(expected_cols - actual_cols):
        violations.append(Violation(col, "coluna obrigatória ausente", None, None))
    for col in sorted(actual_cols - expected_cols):
        violations.append(
            Violation(col, 'coluna não declarada no contrato (extra="forbid")', None, None)
        )
    return violations


def _dtype_violations(
    df: pl.DataFrame, expected_schema: dict[str, PolarsDtype], present_cols: set[str]
) -> tuple[list[Violation], set[str]]:
    violations = []
    bad_cols: set[str] = set()
    for col in sorted(present_cols):
        actual_dtype = df.schema[col]
        expected_dtype = expected_schema[col]
        if not _dtype_is_compatible(actual_dtype, expected_dtype):
            bad_cols.add(col)
            rule = f"tipo incompatível: esperado {expected_dtype}, encontrado {actual_dtype}"
            violations.append(Violation(col, rule, None, None))
    return violations, bad_cols


def _null_violations(df: pl.DataFrame, non_null_cols: set[str]) -> list[Violation]:
    violations = []
    for col in sorted(non_null_cols):
        null_count = df.select(pl.col(col).is_null().sum()).item()
        if null_count > 0:
            sample = df.filter(pl.col(col).is_null()).head(5)
            violations.append(Violation(col, "valores nulos não permitidos", null_count, sample))
    return violations


def _list_column_violations(
    df: pl.DataFrame, col: str, metadata: tuple[Any, ...], inner: Any
) -> list[Violation]:
    violations = []
    _, inner_metadata = _strip_annotated(inner)

    min_len = _min_len_for(metadata)
    if min_len is not None:
        short = df.filter(pl.col(col).list.len() < min_len)
        if short.height > 0:
            rule = f"lista deve ter ao menos {min_len} elemento(s)"
            violations.append(Violation(col, rule, short.height, short.head(5)))

    for bound in _extract_bounds(inner_metadata):
        bad = df.filter(bound.violates_list_element(col))
        if bad.height > 0:
            rule = f"elementos da lista: {bound.describe()}"
            violations.append(Violation(col, rule, bad.height, bad.head(5)))

    return violations


def _enum_column_violations(
    df: pl.DataFrame, col: str, base_type: type[StrEnum]
) -> list[Violation]:
    allowed = [e.value for e in base_type]
    bad = df.filter(pl.col(col).is_not_null() & ~pl.col(col).is_in(allowed))
    if bad.height > 0:
        return [Violation(col, f"deve estar em {allowed}", bad.height, bad.head(5))]
    return []


def _scalar_bound_violations(
    df: pl.DataFrame, col: str, metadata: tuple[Any, ...]
) -> list[Violation]:
    violations = []
    for bound in _extract_bounds(metadata):
        bad = df.filter(pl.col(col).is_not_null() & bound.violates(col))
        if bad.height > 0:
            violations.append(Violation(col, bound.describe(), bad.height, bad.head(5)))
    return violations


def _constraint_violations(
    df: pl.DataFrame, model: type[BaseModel], checkable_cols: set[str]
) -> list[Violation]:
    violations = []
    for col in sorted(checkable_cols):
        base_type, metadata = _field_base_and_metadata(model, col)

        if typing.get_origin(base_type) is list:
            (inner,) = typing.get_args(base_type)
            violations.extend(_list_column_violations(df, col, metadata, inner))
        elif isinstance(base_type, type) and issubclass(base_type, StrEnum):
            violations.extend(_enum_column_violations(df, col, base_type))
        else:
            violations.extend(_scalar_bound_violations(df, col, metadata))
    return violations


def _primary_key_violation(
    df: pl.DataFrame, primary_key: Sequence[str], present_cols: set[str]
) -> Violation | None:
    if not set(primary_key) <= present_cols:
        return None
    dup_counts = df.group_by(list(primary_key)).len().filter(pl.col("len") > 1)
    if dup_counts.height == 0:
        return None
    dup_rows = df.join(dup_counts.select(primary_key), on=list(primary_key), how="inner")
    return Violation(
        ", ".join(primary_key), "chave primária duplicada", dup_rows.height, dup_rows.head(5)
    )


def validate_table(
    df: pl.DataFrame,
    model: type[BaseModel],
    *,
    table_name: str,
    primary_key: Sequence[str],
    required_non_null: frozenset[str] = frozenset(),
) -> None:
    """Valida um DataFrame contra um contrato pydantic, de forma vetorizada.

    Levanta uma única `SchemaValidationError` acumulando todas as violações
    encontradas -- coluna ausente, coluna extra, dtype incompatível, nulo
    indevido, restrição numérica violada, valor fora de enumeração fechada,
    elemento de lista fora do intervalo, e chave primária duplicada -- em vez
    de parar na primeira. A mensagem nomeia tabela, coluna, regra, contagem
    de linhas e mostra uma amostra das linhas ofensoras.

    `required_non_null` promove campos opcionais do modelo a obrigatórios
    nesta chamada, sem alterar o contrato. Pensado para depois que um campo
    hoje nulo (por ausência no dado público, ex.: `cost`, `price`,
    `price_ref`, `ean`, `pack_multiple`) for arbitrado e passar a ser
    exigido: sem isso, uma etapa posterior calcularia margem sobre coluna
    nula e devolveria um número plausível, porém errado. Nunca remove
    obrigatoriedade que já existe no modelo.
    """
    unknown = required_non_null - set(model.model_fields)
    if unknown:
        msg = (
            f"required_non_null contém coluna que não existe no modelo "
            f"{model.__name__}: {sorted(unknown)}"
        )
        raise ValueError(msg)

    expected_schema = expected_polars_schema(model)
    expected_cols = set(expected_schema)
    actual_cols = set(df.columns)
    present_cols = expected_cols & actual_cols

    violations = _column_presence_violations(expected_cols, actual_cols)

    dtype_violations, bad_dtype_cols = _dtype_violations(df, expected_schema, present_cols)
    violations.extend(dtype_violations)

    checkable_cols = present_cols - bad_dtype_cols
    non_null_cols = (_default_required_columns(model) | required_non_null) & checkable_cols
    violations.extend(_null_violations(df, non_null_cols))
    violations.extend(_constraint_violations(df, model, checkable_cols))

    pk_violation = _primary_key_violation(df, primary_key, present_cols)
    if pk_violation is not None:
        violations.append(pk_violation)

    if violations:
        raise SchemaValidationError(table_name, violations)


# --------------------------------------------------------------------------
# Integridade referencial entre tabelas
# --------------------------------------------------------------------------


def validate_referential_integrity(
    *,
    items: pl.DataFrame,
    suppliers: pl.DataFrame,
    sales: pl.DataFrame | None = None,
    stock: pl.DataFrame | None = None,
) -> None:
    """Verifica integridade referencial entre as tabelas canônicas.

    Todo `item_id` em `sales`/`stock` existe em `items`; todo `supplier_id`
    em `items` existe em `suppliers`. Assume que cada tabela já passou por
    `validate_table` -- unicidade de chave primária não é reverificada aqui.
    Não valida completude de calendário (isso é Sprint 3).
    """
    violations: list[Violation] = []

    supplier_ids = suppliers["supplier_id"].to_list()
    orphan_items = items.filter(~pl.col("supplier_id").is_in(supplier_ids))
    if orphan_items.height > 0:
        rule = "referencia supplier_id inexistente em suppliers"
        violations.append(Violation("supplier_id", rule, orphan_items.height, orphan_items.head(5)))

    item_ids = items["item_id"].to_list()
    if sales is not None:
        orphan_sales = sales.filter(~pl.col("item_id").is_in(item_ids))
        if orphan_sales.height > 0:
            rule = "referencia item_id inexistente em items (tabela sales)"
            violations.append(Violation("item_id", rule, orphan_sales.height, orphan_sales.head(5)))

    if stock is not None:
        orphan_stock = stock.filter(~pl.col("item_id").is_in(item_ids))
        if orphan_stock.height > 0:
            rule = "referencia item_id inexistente em items (tabela stock)"
            violations.append(Violation("item_id", rule, orphan_stock.height, orphan_stock.head(5)))

    if violations:
        raise SchemaValidationError("integridade referencial", violations)


# --------------------------------------------------------------------------
# Consistência order_days / review_period_days (suppliers)
# --------------------------------------------------------------------------


def max_cyclic_order_gap(order_days: Sequence[int]) -> int:
    """Maior intervalo, em dias, entre dois dias de pedido consecutivos de `order_days`.

    Considera o ciclo semanal (do último dia de volta ao primeiro). Função
    pura, usada por `validate_supplier_order_cadence`. Ex.: `[1, 4]`
    (segunda, quinta) tem intervalo 3 a partir da segunda e 4 a partir da
    quinta -- o maior é 4.
    """
    days = sorted(set(order_days))
    gaps = [b - a for a, b in itertools.pairwise(days)]
    gaps.append(days[0] + 7 - days[-1])
    return max(gaps)


def validate_supplier_order_cadence(suppliers: pl.DataFrame) -> None:
    """Verifica que `review_period_days` cobre o maior intervalo entre dias de pedido.

    `order_days` e `review_period_days` são fontes de verdade independentes
    (ver docstring de `Supplier`): se dentro de uma janela de
    `review_period_days` dias não existir nenhum dia de pedido, a cadência
    de revisão é inviável -- erro de cadastro, não detalhe. Não calcula o
    intervalo real até a próxima entrega viável (isso é Sprint 11); só
    garante que o contrato é internamente consistente.
    """
    order_days_lists = suppliers["order_days"].to_list()
    gaps = pl.Series("_max_order_gap", [max_cyclic_order_gap(days) for days in order_days_lists])
    checked = suppliers.with_columns(gaps)
    violating = checked.filter(pl.col("_max_order_gap") > pl.col("review_period_days"))
    if violating.height > 0:
        wanted_cols = ("supplier_id", "order_days", "review_period_days", "_max_order_gap")
        sample_cols = [c for c in wanted_cols if c in violating.columns]
        rule = (
            "review_period_days menor que o maior intervalo entre dias de pedido "
            "consecutivos (order_days): cadência de revisão inviável"
        )
        raise SchemaValidationError(
            "suppliers",
            [
                Violation(
                    "review_period_days",
                    rule,
                    violating.height,
                    violating.select(sample_cols).head(5),
                )
            ],
        )

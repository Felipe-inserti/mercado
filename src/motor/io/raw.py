"""Carregamento bruto do dataset Favorita: CSV -> parquet sem transformar nada.

Escopo desta sprint (Sprint 2): nenhuma linha some, nenhum valor muda. Nenhum
mapeamento para as tabelas canônicas de `motor.io.contracts` acontece aqui --
isso é Sprint 3. `RAW_SCHEMAS` fixa o dtype de cada coluna explicitamente:
inferência de schema do polars sobre um arquivo de 125M linhas é lenta e
arriscada -- uma amostra inicial com valores enganosos pode inferir tipo
errado para o arquivo inteiro.

`train.csv` não cabe confortavelmente em memória (~5GB, ~125M linhas). Toda
leitura aqui é `scan_csv`/`scan_parquet` (preguiçosa); a conversão usa
`sink_parquet` (streaming), nunca materializa o CSV inteiro.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Final

import polars as pl

from motor.io.contracts import PolarsDtype

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Schemas do dado bruto -- nomes e tipos exatamente como no arquivo original
# --------------------------------------------------------------------------

RAW_SCHEMAS: Final[dict[str, dict[str, PolarsDtype]]] = {
    "train": {
        "id": pl.Int64,
        "date": pl.Date,
        "store_nbr": pl.Int64,
        "item_nbr": pl.Int64,
        "unit_sales": pl.Float64,
        "onpromotion": pl.Boolean,
    },
    "items": {
        "item_nbr": pl.Int64,
        "family": pl.String,
        "class": pl.Int64,
        "perishable": pl.Int64,
    },
    "stores": {
        "store_nbr": pl.Int64,
        "city": pl.String,
        "state": pl.String,
        "type": pl.String,
        "cluster": pl.Int64,
    },
    "transactions": {
        "date": pl.Date,
        "store_nbr": pl.Int64,
        "transactions": pl.Int64,
    },
    "oil": {
        "date": pl.Date,
        "dcoilwtico": pl.Float64,
    },
    "holidays_events": {
        "date": pl.Date,
        "type": pl.String,
        "locale": pl.String,
        "locale_name": pl.String,
        "description": pl.String,
        "transferred": pl.Boolean,
    },
}


class RawConversionError(ValueError):
    """Uma checagem de integridade falhou depois da conversão CSV -> parquet.

    Nunca levantada por conteúdo "estranho mas verdadeiro" do dado -- só por
    sinal de que a própria conversão pode ter corrompido algo (linha perdida,
    parsing de data ou booleano que virou nulo em silêncio). Ver seção 8 do
    CLAUDE.md: "arredondar/tratar/limpar" o dado não é papel desta sprint,
    mas confirmar que a cópia é fiel, é.
    """


# --------------------------------------------------------------------------
# Conversão
# --------------------------------------------------------------------------

# Verdades externas documentadas publicamente para o dataset Favorita
# (https://www.kaggle.com/c/favorita-grocery-sales-forecasting), independentes
# do nosso código -- usadas para validar a conversão de `train.csv`, nunca
# como teste unitário (teste unitário não pode depender do arquivo real).
_TRAIN_EXPECTED_ROWS: Final = 125_497_040
_TRAIN_ONPROMOTION_NULL_RATIO_RANGE: Final = (0.10, 0.25)


def convert_raw_to_parquet(
    raw_dir: Path,
    out_dir: Path,
    *,
    overwrite: bool = False,
    check_known_totals: bool = True,
) -> dict[str, Path]:
    """Converte os seis CSVs brutos em parquet, preservando linha e valor.

    Idempotente: se `out_dir/{nome}.parquet` já existe e `overwrite=False`, a
    conversão daquele arquivo é pulada (sem reler o CSV, sem revalidar).

    Depois de escrever cada arquivo, roda checagens de integridade e levanta
    `RawConversionError` se alguma falhar (ver `_validate_generic` e
    `_validate_train_known_totals`). `check_known_totals` existe só para
    permitir testar a conversão com CSVs sintéticos pequenos, que não têm como
    satisfazer a contagem exata de `train.csv` documentada publicamente --
    continua `True` por padrão, inclusive na CLI.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Path] = {}

    for name, schema in RAW_SCHEMAS.items():
        csv_path = raw_dir / f"{name}.csv"
        if not csv_path.exists():
            msg = f"arquivo bruto esperado não encontrado: {csv_path}"
            raise FileNotFoundError(msg)

        out_path = out_dir / f"{name}.parquet"
        if out_path.exists() and not overwrite:
            logger.info("'%s': parquet já existe em %s, conversão pulada", name, out_path)
            result[name] = out_path
            continue

        pl.scan_csv(csv_path, schema_overrides=schema).sink_parquet(out_path)
        _validate_generic(name, csv_path, out_path, schema)
        if name == "train" and check_known_totals:
            _validate_train_known_totals(pl.scan_parquet(out_path))

        result[name] = out_path

    return result


def _validate_generic(
    name: str, csv_path: Path, out_path: Path, schema: dict[str, PolarsDtype]
) -> int:
    """Checagens que rodam para todo arquivo convertido, do maior ao menor.

    Contagem de linhas do parquet contra o csv bruto (lido sem
    `schema_overrides`, para não repetir o mesmo eventual erro de tipo duas
    vezes) e, se o arquivo tem coluna `date`, confirma que ela não virou nula
    por inteiro -- é o sintoma de um `schema_overrides` de data que falhou
    silenciosamente.
    """
    parquet_lf = pl.scan_parquet(out_path)
    parquet_rows: int = parquet_lf.select(pl.len()).collect().item()

    csv_rows: int = (
        pl.scan_csv(csv_path, infer_schema_length=0)
        .select(pl.len())
        .collect(engine="streaming")
        .item()
    )
    if parquet_rows != csv_rows:
        msg = (
            f"'{name}': parquet tem {parquet_rows} linha(s), csv bruto tem {csv_rows} -- "
            "conversão perdeu ou duplicou linha"
        )
        raise RawConversionError(msg)

    if "date" in schema:
        date_nulls = parquet_lf.select(pl.col("date").is_null().sum()).collect().item()
        if date_nulls > 0:
            msg = (
                f"'{name}': coluna 'date' tem {date_nulls} nulo(s) após conversão -- "
                "parsing de data para pl.Date pode ter falhado silenciosamente"
            )
            raise RawConversionError(msg)

    logger.info("'%s': %d linha(s), contagem bate com o csv bruto", name, parquet_rows)
    return parquet_rows


def _validate_train_known_totals(parquet_lf: pl.LazyFrame) -> None:
    """Confere `train.csv` contra as duas verdades externas documentadas.

    (1) contagem exata de linhas; (2) proporção de nulos em `onpromotion`
    dentro de [0.10, 0.25] -- a documentação cita ~16%, concentrado em
    2013-2014. De brinde, confirma que `id` é sequencial sem buraco
    (`id.max() - id.min() + 1 == linhas`), já que preservamos a coluna.
    """
    stats = parquet_lf.select(
        pl.len().alias("rows"),
        pl.col("id").min().alias("id_min"),
        pl.col("id").max().alias("id_max"),
        pl.col("onpromotion").is_null().mean().alias("promo_null_ratio"),
    ).collect()
    rows = stats["rows"].item()
    id_min = stats["id_min"].item()
    id_max = stats["id_max"].item()
    promo_null_ratio = stats["promo_null_ratio"].item()

    if rows != _TRAIN_EXPECTED_ROWS:
        msg = (
            f"'train': {rows} linha(s), esperado exatamente {_TRAIN_EXPECTED_ROWS} "
            "(documentação pública do dataset Favorita)"
        )
        raise RawConversionError(msg)

    if id_max - id_min + 1 != rows:
        msg = (
            f"'train': coluna 'id' não é sequencial sem buraco -- "
            f"max({id_max}) - min({id_min}) + 1 = {id_max - id_min + 1}, esperado {rows}"
        )
        raise RawConversionError(msg)

    lo, hi = _TRAIN_ONPROMOTION_NULL_RATIO_RANGE
    if not lo <= promo_null_ratio <= hi:
        msg = (
            f"'train': proporção de nulos em 'onpromotion' = {promo_null_ratio:.4f}, "
            f"fora do intervalo documentado [{lo}, {hi}] -- schema_overrides pl.Boolean "
            "pode ter interpretado a coluna errado"
        )
        raise RawConversionError(msg)

    logger.info(
        "'train': verdade externa ok -- %d linhas, id sequencial [%d, %d], onpromotion nulo=%.4f",
        rows,
        id_min,
        id_max,
        promo_null_ratio,
    )


def scan_raw(name: str, parquet_dir: Path) -> pl.LazyFrame:
    """Leitura preguiçosa de um arquivo bruto já convertido para parquet."""
    if name not in RAW_SCHEMAS:
        msg = f"'{name}' não é um dataset bruto conhecido: {sorted(RAW_SCHEMAS)}"
        raise ValueError(msg)
    path = parquet_dir / f"{name}.parquet"
    if not path.exists():
        msg = f"parquet de '{name}' não encontrado em {path} -- rode a conversão primeiro"
        raise FileNotFoundError(msg)
    return pl.scan_parquet(path)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Conversão do dataset Favorita bruto para parquet."
    )
    parser.add_argument("--convert", action="store_true", help="roda a conversão CSV -> parquet")
    parser.add_argument(
        "--raw-dir", type=Path, default=Path("data/raw/favorita"), help="diretório dos CSVs brutos"
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data/raw_parquet/favorita"),
        help="diretório de saída dos parquets",
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="reconverte mesmo se o parquet já existir"
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if not args.convert:
        parser.print_help()
        return

    result = convert_raw_to_parquet(args.raw_dir, args.out_dir, overwrite=args.overwrite)
    for name, path in result.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()

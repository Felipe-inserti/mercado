"""Testes de `motor.features.build` (Sprint 14).

Cobre os dois casos de borda pedidos no enunciado da sprint: um item com
BURACO de calendário (nasce no meio da janela -- nenhuma linha antes da
entrada, não zero) e um item de venda INTERMITENTE (linha existe todo dia,
mas a maioria é zero). O teste central (`test_features_nao_vazam_futuro_*`)
é a entrega da sprint: prova que nenhuma feature muda quando dado futuro
existe mas não deveria ser olhado.
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from motor.config import FeatureCalendarParams, FeatureHistoricoParams, FeaturesParams
from motor.features.build import build_features, build_training_matrix
from motor.features.calendar import StoreLocale, build_calendar_features

_STORE = "1"
_AS_OF = date(2020, 3, 1)
_LOCALE = StoreLocale(city="Quito", state="Pichincha")
_HOLIDAYS = pl.DataFrame(
    [],
    schema={
        "date": pl.Date,
        "type": pl.String,
        "locale": pl.String,
        "locale_name": pl.String,
        "description": pl.String,
        "transferred": pl.Boolean,
    },
)

_ALL_FEATURE_COLUMNS = [
    "weekday",
    "is_month_start",
    "quinzena",
    "days_to_payday",
    "is_holiday_national",
    "is_holiday_regional",
    "is_holiday_local",
    "lag_units_1",
    "lag_units_7",
    "lag_units_14",
    "lag_units_28",
    "rolling_mean_units_7d",
    "rolling_mean_units_14d",
    "rolling_mean_units_28d",
    "rolling_mean_units_56d",
    "rolling_sum_units_10d",
    "share_days_with_sale_7d",
    "share_days_with_sale_14d",
    "share_days_with_sale_28d",
    "share_days_with_sale_56d",
    "promo_share_7d",
    "promo_share_14d",
    "promo_share_28d",
    "promo_share_56d",
    "promo_known_share_7d",
    "promo_known_share_14d",
    "promo_known_share_28d",
    "promo_known_share_56d",
    "days_since_last_sale",
    "days_since_last_promo",
    "category",
    "item_class",
    "is_perishable",
]


def _params(*, active_features: list[str] | None = None) -> FeaturesParams:
    return FeaturesParams(
        calendar=FeatureCalendarParams(
            month_start_max_day=3, quinzena_split_day=15, payday_days_of_month=[15, -1]
        ),
        historico=FeatureHistoricoParams(
            lag_days=[1, 7, 14, 28],
            rolling_windows_days=[7, 14, 28, 56],
            risk_window_reference_days=10,
        ),
        active_features=active_features or _ALL_FEATURE_COLUMNS,
    )


def _sale_row(
    item_id: str,
    d: date,
    *,
    units_sold: float,
    on_promo: bool | None,
) -> dict[str, object]:
    return {
        "store_id": _STORE,
        "item_id": item_id,
        "date": d,
        "units_sold": units_sold,
        "units_returned": 0.0,
        "on_promo": on_promo,
        "price": None,
        "is_operating_day": True,
        "is_anomaly": False,
        "anomaly_reason": None,
    }


def _sales_schema() -> dict[str, object]:
    return {
        "store_id": pl.String,
        "item_id": pl.String,
        "date": pl.Date,
        "units_sold": pl.Float64,
        "units_returned": pl.Float64,
        "on_promo": pl.Boolean,
        "price": pl.Float64,
        "is_operating_day": pl.Boolean,
        "is_anomaly": pl.Boolean,
        "anomaly_reason": pl.String,
    }


def _build_synthetic_sales() -> pl.DataFrame:
    """Painel sintético com três itens, `date` de `_AS_OF - 80d` a `_AS_OF + 30d`:

    - `reg`: denso a vida toda, 10 unidades/dia, uma promoção de 5 dias bem
      ANTES de `as_of` (legítima) e outra de 5 dias logo DEPOIS de `as_of` --
      esta segunda é a isca de vazamento: se `promo_share_7d` olhasse o
      futuro, ela mudaria a feature de forma bem detectável.
    - `intermitente`: denso a vida toda, vende só 1 em cada 5 dias.
    - `novo`: SEM NENHUMA LINHA antes de `as_of - 5d` (buraco de calendário
      de verdade, não zero-fill) -- nasce 5 dias antes da decisão.
    """
    rows: list[dict[str, object]] = []
    start = _AS_OF - timedelta(days=80)
    end = _AS_OF + timedelta(days=30)

    d = start
    while d <= end:
        # `reg`: promoção legítima bem antes de as_of, e uma isca de vazamento depois.
        promo_reg = _AS_OF - timedelta(days=40) <= d < _AS_OF - timedelta(days=35)
        promo_reg_futura = _AS_OF <= d < _AS_OF + timedelta(days=5)
        rows.append(
            _sale_row("reg", d, units_sold=10.0, on_promo=bool(promo_reg or promo_reg_futura))
        )

        dias_desde_start = (d - start).days
        vende_hoje = dias_desde_start % 5 == 0
        rows.append(
            _sale_row("intermitente", d, units_sold=5.0 if vende_hoje else 0.0, on_promo=False)
        )

        if d >= _AS_OF - timedelta(days=5):
            rows.append(_sale_row("novo", d, units_sold=8.0, on_promo=False))

        d += timedelta(days=1)

    return pl.DataFrame(rows, schema=_sales_schema()).sort("store_id", "item_id", "date")


def _items() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "item_id": ["reg", "intermitente", "novo"],
            "category": ["GROCERY I", "DAIRY", "PRODUCE"],
            "item_class": ["1010", "2020", "3030"],
            "is_perishable": [False, True, True],
        }
    )


def _calendar_for(as_of: date) -> pl.DataFrame:
    return build_calendar_features(
        [as_of], locale=_LOCALE, holidays=_HOLIDAYS, params=_params().calendar
    )


def _build(sales: pl.DataFrame, as_of: date, *, item_ids: list[str] | None = None) -> pl.DataFrame:
    return build_features(
        sales,
        _items(),
        as_of,
        store_id=_STORE,
        calendar=_calendar_for(as_of),
        params=_params(),
        item_ids=item_ids,
    )


# -- anti-vazamento: a entrega da sprint -------------------------------------


def test_features_nao_vazam_futuro_build_features() -> None:
    sales_completo = _build_synthetic_sales()
    com_futuro = _build(sales_completo, _AS_OF)

    sales_truncado = sales_completo.filter(pl.col("date") < _AS_OF)
    sem_futuro = _build(sales_truncado, _AS_OF)

    assert_frame_equal(com_futuro, sem_futuro, check_exact=True)


def test_isca_de_promocao_futura_de_fato_mudaria_a_feature_se_vazasse() -> None:
    """Confirma que a isca de vazamento em `_build_synthetic_sales` tem dentes:
    sem o corte `date < as_of`, `promo_share_7d` do item `reg` mudaria. Isso
    prova que `test_features_nao_vazam_futuro_build_features` não passaria
    por acidente (features que já ignoram tudo, vazamento ou não)."""
    sales_completo = _build_synthetic_sales()
    # cenário incorreto de propósito -- inclui a semana FUTURA à janela de 7d
    janela_com_futuro = sales_completo.filter(
        (pl.col("item_id") == "reg")
        & (pl.col("date") >= _AS_OF - timedelta(days=7))
        & (pl.col("date") < _AS_OF + timedelta(days=7))
    )
    promo_share_com_futuro = janela_com_futuro["on_promo"].mean()

    correto = _build(sales_completo, _AS_OF).filter(pl.col("item_id") == "reg")
    promo_share_correto = correto["promo_share_7d"][0]

    assert promo_share_correto == 0.0  # nenhuma promoção nos 7 dias ANTES de as_of
    assert promo_share_com_futuro is not None
    assert promo_share_com_futuro > promo_share_correto  # a isca, se vazasse, mudaria o número


def test_features_nao_vazam_futuro_para_cada_as_of_da_matriz() -> None:
    """Mesmo teste de truncamento, mas aplicado a CADA data de uma lista de
    `as_of` passada a `build_training_matrix` -- não só à última data."""
    sales_completo = _build_synthetic_sales()
    as_of_dates = [
        _AS_OF - timedelta(days=3),  # dentro da vida curta do item `novo`
        _AS_OF,
        _AS_OF + timedelta(days=10),
    ]

    matriz = build_training_matrix(
        sales_completo,
        _items(),
        as_of_dates,
        store_id=_STORE,
        locale=_LOCALE,
        holidays=_HOLIDAYS,
        params=_params(),
    )

    for as_of in as_of_dates:
        truncado = sales_completo.filter(pl.col("date") < as_of)
        esperado = build_features(
            truncado,
            _items(),
            as_of,
            store_id=_STORE,
            calendar=_calendar_for(as_of),
            params=_params(),
        )
        obtido = matriz.filter(pl.col("as_of") == as_of)
        assert_frame_equal(obtido.sort("item_id"), esperado.sort("item_id"), check_exact=True)


# -- buraco de calendário: item `novo` ---------------------------------------


def test_item_novo_sem_historico_antes_da_entrada_fica_nulo_nao_zero() -> None:
    sales = _build_synthetic_sales()
    out = _build(sales, _AS_OF).filter(pl.col("item_id") == "novo").to_dicts()[0]

    # só tem 5 dias de vida -- lags de 7/14/28 dias não existem, não são zero
    assert out["lag_units_1"] == 8.0
    assert out["lag_units_7"] is None
    assert out["lag_units_14"] is None
    assert out["lag_units_28"] is None

    # janela de 7d cabe inteira nos 5 dias de vida (n_rows=5 < 7): média sobre
    # o que existe, não sobre 7 dias fingidos
    assert out["rolling_mean_units_7d"] == pytest.approx(8.0)
    assert out["share_days_with_sale_7d"] == pytest.approx(1.0)  # vendeu nos 5 dias que existiu


def test_item_sem_nenhum_historico_no_as_of_fica_com_historico_nulo_mas_aparece() -> None:
    """Item pedido explicitamente que ainda não tem NENHUMA linha antes de
    `as_of` ainda ganha uma linha na saída -- calendário/atributo preenchidos,
    histórico nulo (decisão explícita do desenho, não removida)."""
    sales = _build_synthetic_sales().filter(pl.col("item_id") != "novo")
    as_of_antes_do_nascimento = _AS_OF - timedelta(days=10)
    out = build_features(
        sales,
        _items(),
        as_of_antes_do_nascimento,
        store_id=_STORE,
        calendar=_calendar_for(as_of_antes_do_nascimento),
        params=_params(),
        item_ids=["novo"],
    ).to_dicts()[0]

    assert out["days_since_last_sale"] is None
    assert out["rolling_mean_units_7d"] is None
    assert out["promo_share_7d"] is None
    assert out["promo_known_share_7d"] is None
    assert out["category"] == "PRODUCE"  # atributo estático continua presente


# -- item intermitente: dias_desde_ultima_venda e proporção ------------------


def test_item_intermitente_dias_desde_ultima_venda_e_proporcao() -> None:
    sales = _build_synthetic_sales()
    out = _build(sales, _AS_OF).filter(pl.col("item_id") == "intermitente").to_dicts()[0]

    # padrão: vende em dias_desde_start % 5 == 0; achar o último dia de venda
    # antes de as_of "na unha" a partir do mesmo gerador do fixture
    start = _AS_OF - timedelta(days=80)
    last_sale_date = max(
        start + timedelta(days=k) for k in range((_AS_OF - start).days) if k % 5 == 0
    )
    assert out["days_since_last_sale"] == (_AS_OF - last_sale_date).days

    # 28 não é múltiplo de 5: conta os dias de venda que caem de fato na
    # janela em vez de assumir a proporção nominal 1/5.
    janela_28 = [_AS_OF - timedelta(days=i) for i in range(1, 29)]
    n_venda_na_janela = sum(1 for d in janela_28 if ((d - start).days % 5 == 0))
    assert out["share_days_with_sale_28d"] == pytest.approx(n_venda_na_janela / 28, rel=1e-9)


# -- promo_known_share: não é redundante com share_days_with_sale -----------


def test_promo_known_share_nao_e_pura_funcao_de_venda() -> None:
    """`on_promo` nulo (reindex) coincide MUITO, mas não 100%, com venda zero
    no dado real (medido antes de implementar: 143 de 251.211 linhas de venda
    zero, na loja 44, tinham `on_promo` conhecido). Reproduz essa folga aqui:
    um dia de venda zero com `on_promo` conhecido -- confirma que a coluna
    carrega informação própria, não é colinear com `share_days_with_sale`."""
    rows = []
    start = _AS_OF - timedelta(days=7)  # exatamente a janela de 7d ([as_of-7, as_of))
    d = start
    while d < _AS_OF:
        if d == start:
            # venda zero, promo CONHECIDO
            rows.append(_sale_row("x", d, units_sold=0.0, on_promo=False))
        else:
            # venda zero, promo desconhecido
            rows.append(_sale_row("x", d, units_sold=0.0, on_promo=None))
        d += timedelta(days=1)
    sales = pl.DataFrame(rows, schema=_sales_schema())
    items = pl.DataFrame(
        {"item_id": ["x"], "category": ["GROCERY I"], "item_class": ["1"], "is_perishable": [False]}
    )

    out = build_features(
        sales,
        items,
        _AS_OF,
        store_id=_STORE,
        calendar=_calendar_for(_AS_OF),
        params=_params(),
        item_ids=["x"],
    ).to_dicts()[0]

    assert out["share_days_with_sale_7d"] == 0.0  # nenhuma venda
    # só 1 dos 7 dias tem status de promoção conhecido
    assert out["promo_known_share_7d"] == pytest.approx(1 / 7)


# -- forma e determinismo ------------------------------------------------


def test_forma_sem_nulo_inesperado_apos_warmup() -> None:
    """Sobre um painel denso, sem itens novos, todas as colunas calculadas
    (exceto as legitimamente nuláveis por atributo) vêm preenchidas."""
    sales = _build_synthetic_sales().filter(pl.col("item_id") != "novo")
    out = build_features(
        sales,
        _items().filter(pl.col("item_id") != "novo"),
        _AS_OF,
        store_id=_STORE,
        calendar=_calendar_for(_AS_OF),
        params=_params(),
    )
    colunas_sempre_preenchidas = [
        c
        for c in _ALL_FEATURE_COLUMNS
        if c
        not in {
            "item_class",  # nulável por contrato de `Item`, não por falta de histórico
            # legitimamente nulo quando o item nunca esteve em promoção no histórico
            # visível (`intermitente`, no fixture, nunca é promovido) -- mesma
            # semântica de `days_since_last_sale` ser nulo pra item sem venda: não é
            # falta de dado, é ausência real do evento.
            "days_since_last_promo",
        }
    ]
    for coluna in colunas_sempre_preenchidas:
        assert out[coluna].null_count() == 0, f"{coluna} tem nulo inesperado"


def test_determinismo_duas_execucoes_identicas() -> None:
    sales = _build_synthetic_sales()
    primeira = _build(sales, _AS_OF)
    segunda = _build(sales, _AS_OF)
    assert_frame_equal(primeira, segunda, check_exact=True)


# -- active_features: seleção e validação -------------------------------


def test_active_features_desliga_coluna_sem_mexer_no_codigo() -> None:
    sales = _build_synthetic_sales()
    params = _params(active_features=["weekday", "category"])
    out = build_features(
        sales,
        _items(),
        _AS_OF,
        store_id=_STORE,
        calendar=_calendar_for(_AS_OF),
        params=params,
        item_ids=["reg"],
    )
    assert set(out.columns) == {"store_id", "item_id", "as_of", "weekday", "category"}


def test_active_features_com_nome_desconhecido_levanta_erro_claro() -> None:
    sales = _build_synthetic_sales()
    params = _params(active_features=["coluna_que_nao_existe"])
    with pytest.raises(ValueError, match="coluna_que_nao_existe"):
        build_features(
            sales,
            _items(),
            _AS_OF,
            store_id=_STORE,
            calendar=_calendar_for(_AS_OF),
            params=params,
            item_ids=["reg"],
        )

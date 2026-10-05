"""Testes obrigatórios da Sprint 15 para `motor.forecast.quantile_gbm`:
embaralhamento (vazamento), cobertura empírica por quantil, cache, e
vazamento no caminho completo até o fit (a extensão do teste anti-vazamento
da Sprint 14 até `train_quantile_models`).
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl
import pytest

import motor.forecast.quantile_gbm as qgbm_module
from motor.config import (
    FeatureCalendarParams,
    FeatureHistoricoParams,
    FeaturesParams,
    QuantileGbmParams,
)
from motor.features.build import build_features, build_training_matrix
from motor.features.calendar import StoreLocale, build_calendar_features
from motor.forecast.quantile_gbm import (
    InsufficientTrainingHistoryError,
    QuantileGbmForecaster,
    QuantileModelRegistry,
    build_categorical_encoding,
    compute_config_hash,
    precompute_predictions,
    target_for_origin,
    train_quantile_models,
)

_STORE = "1"
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
_LGBM_FIXED = {
    "objective": "quantile",
    "deterministic": True,
    "force_row_wise": True,
    "verbosity": -1,
}


def _features_params() -> FeaturesParams:
    return FeaturesParams(
        calendar=FeatureCalendarParams(
            month_start_max_day=3, quinzena_split_day=15, payday_days_of_month=[15, -1]
        ),
        historico=FeatureHistoricoParams(
            lag_days=[1], rolling_windows_days=[7], risk_window_reference_days=1
        ),
        active_features=[
            "weekday",
            "lag_units_1",
            "rolling_mean_units_7d",
            "share_days_with_sale_7d",
            "category",
            "item_class",
            "is_perishable",
        ],
    )


def _hyperparams(cache_dir: Path, **overrides: object) -> QuantileGbmParams:
    base: dict[str, object] = {
        "learning_rate": 0.1,
        "num_leaves": 15,
        "num_boost_round": 100,
        "num_threads": 1,
        "min_training_origins": 5,
        "decay_half_life_days": None,
        "seed": 42,
        "model_cache_dir": cache_dir,
    }
    base.update(overrides)
    return QuantileGbmParams(**base)  # type: ignore[arg-type]


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


def _synthetic_sales(item_ids: list[str], *, start: date, n_days: int, seed: int) -> pl.DataFrame:
    """`units_sold = 20 + 80*(fim de semana) + ruído(0, 5)` -- sinal forte e de
    baixo ruído, aprendível via `weekday`, para os testes de embaralhamento e
    cobertura terem uma distinção nítida entre "aprendeu" e "não aprendeu"."""
    rng = np.random.default_rng(seed)
    rows = []
    for item_id in item_ids:
        for i in range(n_days):
            d = start + timedelta(days=i)
            bonus = 80.0 if d.isoweekday() in (6, 7) else 0.0
            noise = float(rng.normal(0.0, 5.0))
            rows.append(
                {
                    "store_id": _STORE,
                    "item_id": item_id,
                    "date": d,
                    "units_sold": max(0.0, 20.0 + bonus + noise),
                    "units_returned": 0.0,
                    "on_promo": False,
                    "price": None,
                    "is_operating_day": True,
                    "is_anomaly": False,
                    "anomaly_reason": None,
                }
            )
    return pl.DataFrame(rows, schema=_sales_schema())


def _items(item_ids: list[str]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "item_id": item_ids,
            "category": ["GROCERY I"] * len(item_ids),
            "item_class": ["1"] * len(item_ids),
            "is_perishable": [False] * len(item_ids),
        }
    )


def _weekly(start: date, end_inclusive: date, cadence: int) -> list[date]:
    out = []
    d = start
    while d <= end_inclusive:
        out.append(d)
        d += timedelta(days=cadence)
    return out


def _pinball_loss(y_true: np.ndarray, y_pred: np.ndarray, q: float) -> float:
    diff = y_true - y_pred
    return float(np.mean(np.maximum(q * diff, (q - 1.0) * diff)))


# --------------------------------------------------------------------------
# infraestrutura mínima replicada de train_quantile_models, com um ponto de
# embaralhamento explícito -- não altera o módulo de produção só para expor
# um gancho de teste.
# --------------------------------------------------------------------------


def _fit_snapshot(
    sales: pl.DataFrame,
    items: pl.DataFrame,
    item_ids: list[str],
    horizon_by_item: dict[str, int],
    origins: list[date],
    *,
    features_params: FeaturesParams,
    hyperparams: QuantileGbmParams,
    quantiles: list[float],
    shuffle_target: bool,
) -> tuple[dict[float, lgb.Booster], qgbm_module.CategoricalEncoding, list[str], np.ndarray]:
    categorical_cols = [
        c
        for c in ("category", "item_class", "is_perishable")
        if c in features_params.active_features
    ]
    encoding = build_categorical_encoding(items, categorical_cols)
    feature_cols = [*features_params.active_features, qgbm_module.RISK_WINDOW_FEATURE]
    categorical_idx = [feature_cols.index(c) for c in categorical_cols]

    panel = build_training_matrix(
        sales,
        items,
        origins,
        store_id=_STORE,
        locale=_LOCALE,
        holidays=_HOLIDAYS,
        params=features_params,
    )
    targets = pl.concat(
        [
            target_for_origin(
                sales, item_ids=item_ids, horizon_by_item=horizon_by_item, as_of=o
            ).with_columns(pl.lit(o).alias("as_of"))
            for o in origins
        ]
    )
    training = panel.join(targets, on=["item_id", "as_of"], how="inner").with_columns(
        pl.col("item_id")
        .replace_strict(horizon_by_item, return_dtype=pl.Int64)
        .alias(qgbm_module.RISK_WINDOW_FEATURE)
    )
    encoded = encoding.encode(training.select(*feature_cols))
    x = encoded.to_numpy()
    y = training["target"].to_numpy()
    if shuffle_target:
        y = np.random.default_rng(0).permutation(y)

    boosters = {}
    for q in quantiles:
        params = {
            **_LGBM_FIXED,
            "alpha": q,
            "seed": hyperparams.seed,
            "learning_rate": hyperparams.learning_rate,
            "num_leaves": hyperparams.num_leaves,
            "num_threads": hyperparams.num_threads,
        }
        ds = lgb.Dataset(
            x,
            label=y,
            feature_name=feature_cols,
            categorical_feature=categorical_idx,
            free_raw_data=False,
        )
        boosters[q] = lgb.train(params, ds, num_boost_round=hyperparams.num_boost_round)
    return boosters, encoding, feature_cols, y


def _predict_row(
    boosters: dict[float, lgb.Booster],
    encoding: qgbm_module.CategoricalEncoding,
    feature_cols: list[str],
    sales: pl.DataFrame,
    items: pl.DataFrame,
    *,
    item_id: str,
    horizon: int,
    as_of: date,
    features_params: FeaturesParams,
) -> dict[float, float]:
    calendar = build_calendar_features(
        [as_of], locale=_LOCALE, holidays=_HOLIDAYS, params=features_params.calendar
    )
    row = build_features(
        sales,
        items,
        as_of,
        store_id=_STORE,
        calendar=calendar,
        params=features_params,
        item_ids=[item_id],
    ).with_columns(pl.lit(horizon).alias(qgbm_module.RISK_WINDOW_FEATURE))
    encoded = encoding.encode(row.select(*feature_cols))
    x = encoded.to_numpy()
    return {q: float(b.predict(x)[0]) for q, b in boosters.items()}


# --------------------------------------------------------------------------
# 1) embaralhamento
# --------------------------------------------------------------------------


def test_embaralhamento_desempenho_cai_ao_nivel_trivial() -> None:
    item_ids = [f"i{k}" for k in range(10)]
    start = date(2021, 1, 4)  # segunda-feira
    sales = _synthetic_sales(item_ids, start=start, n_days=230, seed=1)
    items = _items(item_ids)
    horizon_by_item = dict.fromkeys(item_ids, 1)
    features_params = _features_params()
    hyperparams = _hyperparams(Path("unused"))
    quantiles = [0.1, 0.5, 0.9]

    # cadência de 3 dias (não 7): origens semanais cairiam sempre no mesmo dia
    # da semana, e a feature `weekday` -- exatamente a que carrega o sinal
    # sintético -- sairia CONSTANTE no treino, sem variância nenhuma para
    # aprender. Cadência de produção é semanal (`model.retrain_cadence_days`);
    # aqui o objetivo é só validar o mecanismo de embaralhamento, não espelhar
    # a cadência real.
    train_origins = _weekly(start + timedelta(days=14), start + timedelta(days=150), 3)
    oos_origins = _weekly(start + timedelta(days=157), start + timedelta(days=220), 3)

    boosters_real, encoding, feature_cols, y_train = _fit_snapshot(
        sales,
        items,
        item_ids,
        horizon_by_item,
        train_origins,
        features_params=features_params,
        hyperparams=hyperparams,
        quantiles=quantiles,
        shuffle_target=False,
    )
    boosters_shuf, _, _, _ = _fit_snapshot(
        sales,
        items,
        item_ids,
        horizon_by_item,
        train_origins,
        features_params=features_params,
        hyperparams=hyperparams,
        quantiles=quantiles,
        shuffle_target=True,
    )
    trivial_pred = {q: float(np.quantile(y_train, q)) for q in quantiles}

    losses_real = {q: [] for q in quantiles}
    losses_shuf = {q: [] for q in quantiles}
    losses_trivial = {q: [] for q in quantiles}
    for as_of in oos_origins:
        actuals = target_for_origin(
            sales, item_ids=item_ids, horizon_by_item=horizon_by_item, as_of=as_of
        )
        actual_by_item = dict(zip(actuals["item_id"], actuals["target"], strict=True))
        for item_id in item_ids:
            y_true = actual_by_item[item_id]
            pred_real = _predict_row(
                boosters_real,
                encoding,
                feature_cols,
                sales,
                items,
                item_id=item_id,
                horizon=1,
                as_of=as_of,
                features_params=features_params,
            )
            pred_shuf = _predict_row(
                boosters_shuf,
                encoding,
                feature_cols,
                sales,
                items,
                item_id=item_id,
                horizon=1,
                as_of=as_of,
                features_params=features_params,
            )
            for q in quantiles:
                losses_real[q].append(
                    _pinball_loss(np.array([y_true]), np.array([pred_real[q]]), q)
                )
                losses_shuf[q].append(
                    _pinball_loss(np.array([y_true]), np.array([pred_shuf[q]]), q)
                )
                losses_trivial[q].append(
                    _pinball_loss(np.array([y_true]), np.array([trivial_pred[q]]), q)
                )

    loss_real = float(np.mean([v for vs in losses_real.values() for v in vs]))
    loss_shuf = float(np.mean([v for vs in losses_shuf.values() for v in vs]))
    loss_trivial = float(np.mean([v for vs in losses_trivial.values() for v in vs]))

    assert loss_real < 0.5 * loss_trivial, (
        f"modelo com alvo real deveria bater o trivial com folga: real={loss_real:.2f} "
        f"trivial={loss_trivial:.2f}"
    )
    assert loss_shuf > 0.7 * loss_trivial, (
        "SE NÃO DESABOU: o modelo com alvo embaralhado bateu o trivial por uma margem grande "
        f"demais (shuffled={loss_shuf:.2f}, trivial={loss_trivial:.2f}) -- isso é sintoma de "
        "vazamento (o modelo está vendo, de algum jeito, informação correlacionada ao alvo "
        "mesmo depois do embaralhamento). Pare e ache o vazamento antes de prosseguir."
    )


# --------------------------------------------------------------------------
# 2) cobertura empírica por quantil
# --------------------------------------------------------------------------


def test_cobertura_empirica_por_quantil_no_periodo_simulado(tmp_path: Path) -> None:
    item_ids = [f"i{k}" for k in range(12)]
    start = date(2021, 1, 4)
    sales = _synthetic_sales(item_ids, start=start, n_days=260, seed=2)
    items = _items(item_ids)
    horizon_by_item = dict.fromkeys(item_ids, 1)
    features_params = _features_params()
    quantiles = [0.5, 0.9]
    hyperparams = _hyperparams(tmp_path / "cache", num_boost_round=150)

    retrain_dates = [start + timedelta(days=150)]
    registry = train_quantile_models(
        sales,
        items,
        horizon_by_item,
        store_id=_STORE,
        item_ids=item_ids,
        retrain_dates=retrain_dates,
        earliest_training_origin=start + timedelta(days=14),
        origin_cadence_days=3,  # mesmo motivo do teste de embaralhamento: variar dia da semana
        quantiles=quantiles,
        features_params=features_params,
        calendar_locale=_LOCALE,
        holidays=_HOLIDAYS,
        hyperparams=hyperparams,
        cache_dir=tmp_path / "cache",
        config_hash="teste-cobertura",
    )

    eval_origins = _weekly(start + timedelta(days=157), start + timedelta(days=250), 3)
    covered = dict.fromkeys(quantiles, 0)
    total = 0
    for as_of in eval_origins:
        actuals = target_for_origin(
            sales, item_ids=item_ids, horizon_by_item=horizon_by_item, as_of=as_of
        )
        actual_by_item = dict(zip(actuals["item_id"], actuals["target"], strict=True))
        booster_set = registry.for_as_of(as_of)
        for item_id in item_ids:
            calendar = build_calendar_features(
                [as_of], locale=_LOCALE, holidays=_HOLIDAYS, params=features_params.calendar
            )
            row = build_features(
                sales,
                items,
                as_of,
                store_id=_STORE,
                calendar=calendar,
                params=features_params,
                item_ids=[item_id],
            ).with_columns(pl.lit(1).alias(qgbm_module.RISK_WINDOW_FEATURE))
            x = registry.categorical_encoding.encode(
                row.select(*booster_set.feature_cols)
            ).to_numpy()
            y_true = actual_by_item[item_id]
            total += 1
            for q in quantiles:
                pred = float(booster_set.boosters[q].predict(x)[0])
                if y_true <= pred:
                    covered[q] += 1

    for q in quantiles:
        empirical = covered[q] / total
        assert abs(empirical - q) < 0.15, (
            f"cobertura empírica de q={q} foi {empirical:.2%}, esperado perto de {q:.0%} "
            "(desvio grande e sistemático é sinal de alvo mal construído, não de modelo ruim)"
        )


# --------------------------------------------------------------------------
# 3) cache
# --------------------------------------------------------------------------


def test_cache_mesmo_estado_com_cache_quente(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item_ids = [f"i{k}" for k in range(6)]
    start = date(2021, 1, 4)
    sales = _synthetic_sales(item_ids, start=start, n_days=120, seed=3)
    items = _items(item_ids)
    horizon_by_item = dict.fromkeys(item_ids, 1)
    features_params = _features_params()
    quantiles = [0.5, 0.9]
    cache_dir = tmp_path / "cache"
    hyperparams = _hyperparams(cache_dir, num_boost_round=30)
    retrain_dates = [start + timedelta(days=100)]

    n_calls = {"count": 0}
    original_train = lgb.train

    def _counting_train(*args: object, **kwargs: object) -> lgb.Booster:
        n_calls["count"] += 1
        return original_train(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(qgbm_module.lgb, "train", _counting_train)

    common_kwargs = {
        "sales": sales,
        "items": items,
        "horizon_by_item": horizon_by_item,
        "store_id": _STORE,
        "item_ids": item_ids,
        "retrain_dates": retrain_dates,
        "earliest_training_origin": start + timedelta(days=7),
        "origin_cadence_days": 7,
        "quantiles": quantiles,
        "features_params": features_params,
        "calendar_locale": _LOCALE,
        "holidays": _HOLIDAYS,
        "hyperparams": hyperparams,
        "cache_dir": cache_dir,
    }

    registry_a = train_quantile_models(config_hash="config-a", **common_kwargs)  # type: ignore[arg-type]
    assert n_calls["count"] == len(quantiles)  # 1 fit por quantil, cache frio

    registry_b = train_quantile_models(config_hash="config-a", **common_kwargs)  # type: ignore[arg-type]
    assert n_calls["count"] == len(quantiles)  # cache QUENTE: nenhum fit novo

    as_of = retrain_dates[0]
    x = build_features(
        sales,
        items,
        as_of,
        store_id=_STORE,
        calendar=build_calendar_features(
            [as_of], locale=_LOCALE, holidays=_HOLIDAYS, params=features_params.calendar
        ),
        params=features_params,
        item_ids=[item_ids[0]],
    ).with_columns(pl.lit(1).alias(qgbm_module.RISK_WINDOW_FEATURE))
    feature_cols = list(registry_a.for_as_of(as_of).feature_cols)
    x_np = registry_a.categorical_encoding.encode(x.select(*feature_cols)).to_numpy()
    pred_a = {q: registry_a.for_as_of(as_of).boosters[q].predict(x_np)[0] for q in quantiles}
    pred_b = {q: registry_b.for_as_of(as_of).boosters[q].predict(x_np)[0] for q in quantiles}
    assert pred_a == pred_b  # mesmo estado, com e sem cache quente

    # config DIFERENTE não reusa -- novo hash, novos fits
    registry_c = train_quantile_models(config_hash="config-b-diferente", **common_kwargs)  # type: ignore[arg-type]
    assert n_calls["count"] == 2 * len(quantiles)
    assert registry_c is not registry_a


def test_compute_config_hash_muda_com_horizonte(tmp_path: Path) -> None:
    """Achado na revisão da Sprint 16: `horizon_by_item` (= lead_time +
    review_period, por item) entra no ALVO de treino e na feature
    `RISK_WINDOW_FEATURE` dentro de `train_quantile_models`, mas não estava
    na chave de cache -- dois treinos com `lead_time` diferente (portanto
    horizonte diferente) e tudo mais igual colidiam no mesmo diretório de
    cache. Este teste prova a correção nos dois sentidos: horizonte
    diferente muda o hash; horizonte igual (mesmo com dicionários construídos
    separadamente) produz o mesmo hash.
    """
    item_ids = ["i0", "i1"]
    common_kwargs = {
        "hyperparams": _hyperparams(tmp_path / "cache"),
        "features_params": _features_params(),
        "quantiles": [0.5, 0.9],
        "store_id": _STORE,
        "item_ids": item_ids,
    }

    hash_horizonte_10 = compute_config_hash(horizon_by_item={"i0": 10, "i1": 10}, **common_kwargs)
    hash_horizonte_17 = compute_config_hash(horizon_by_item={"i0": 17, "i1": 17}, **common_kwargs)
    hash_horizonte_10_de_novo = compute_config_hash(
        horizon_by_item={"i1": 10, "i0": 10},
        **common_kwargs,  # ordem de inserção trocada
    )
    hash_horizonte_misto = compute_config_hash(
        horizon_by_item={"i0": 10, "i1": 17}, **common_kwargs
    )

    assert hash_horizonte_10 != hash_horizonte_17  # horizonte uniforme diferente -> hash diferente
    assert hash_horizonte_10 == hash_horizonte_10_de_novo  # mesmo horizonte, ordem irrelevante
    # hash por item, não só pelo máximo do painel
    assert hash_horizonte_misto not in {hash_horizonte_10, hash_horizonte_17}


# --------------------------------------------------------------------------
# 4) vazamento no caminho completo até o fit (Sprint 14 -> train_quantile_models)
# --------------------------------------------------------------------------


def test_nenhuma_linha_de_treino_usa_informacao_futura_ate_o_fit(tmp_path: Path) -> None:
    item_ids = [f"i{k}" for k in range(6)]
    start = date(2021, 1, 4)
    sales_completo = _synthetic_sales(item_ids, start=start, n_days=200, seed=4)
    items = _items(item_ids)
    horizon_by_item = dict.fromkeys(item_ids, 1)
    features_params = _features_params()
    quantiles = [0.5, 0.9]
    retrain_date = start + timedelta(days=150)

    kwargs = {
        "items": items,
        "horizon_by_item": horizon_by_item,
        "store_id": _STORE,
        "item_ids": item_ids,
        "retrain_dates": [retrain_date],
        "earliest_training_origin": start + timedelta(days=7),
        "origin_cadence_days": 7,
        "quantiles": quantiles,
        "features_params": features_params,
        "calendar_locale": _LOCALE,
        "holidays": _HOLIDAYS,
    }

    registry_com_futuro = train_quantile_models(
        sales=sales_completo,
        hyperparams=_hyperparams(tmp_path / "cache_com_futuro", num_boost_round=30),
        cache_dir=tmp_path / "cache_com_futuro",
        config_hash="x",
        **kwargs,  # type: ignore[arg-type]
    )
    sales_truncado = sales_completo.filter(pl.col("date") < retrain_date)
    registry_sem_futuro = train_quantile_models(
        sales=sales_truncado,
        hyperparams=_hyperparams(tmp_path / "cache_sem_futuro", num_boost_round=30),
        cache_dir=tmp_path / "cache_sem_futuro",
        config_hash="x",
        **kwargs,  # type: ignore[arg-type]
    )

    bs_com = registry_com_futuro.for_as_of(retrain_date)
    bs_sem = registry_sem_futuro.for_as_of(retrain_date)
    assert bs_com.n_training_rows == bs_sem.n_training_rows
    for q in quantiles:
        assert bs_com.boosters[q].model_to_string() == bs_sem.boosters[q].model_to_string()


# --------------------------------------------------------------------------
# piso mínimo de origens
# --------------------------------------------------------------------------


def test_piso_minimo_de_origens_levanta_erro_claro(tmp_path: Path) -> None:
    item_ids = ["i0"]
    start = date(2021, 1, 4)
    sales = _synthetic_sales(item_ids, start=start, n_days=40, seed=5)
    items = _items(item_ids)
    horizon_by_item = {"i0": 1}
    features_params = _features_params()
    hyperparams = _hyperparams(
        tmp_path / "cache", min_training_origins=50
    )  # piso inatingível de propósito

    with pytest.raises(InsufficientTrainingHistoryError, match="min_training_origins"):
        train_quantile_models(
            sales,
            items,
            horizon_by_item,
            store_id=_STORE,
            item_ids=item_ids,
            retrain_dates=[start + timedelta(days=35)],
            earliest_training_origin=start,
            origin_cadence_days=7,
            quantiles=[0.5],
            features_params=features_params,
            calendar_locale=_LOCALE,
            holidays=_HOLIDAYS,
            hyperparams=hyperparams,
            cache_dir=tmp_path / "cache",
            config_hash="piso",
        )


# --------------------------------------------------------------------------
# 5) previsão em lote (Sprint 16: batching de booster.predict())
# --------------------------------------------------------------------------


def _predicao_item_a_item(
    *,
    registry: QuantileModelRegistry,
    item_sales: pl.DataFrame,
    items: pl.DataFrame,
    store_id: str,
    item_id: str,
    as_of: date,
    horizon: int,
    quantiles: list[float],
    features_params: FeaturesParams,
    calendar_locale: StoreLocale,
    holidays: pl.DataFrame,
) -> dict[float, float]:
    """Réplica FIEL do caminho de `predict_quantiles` de ANTES da Sprint 16
    -- uma linha por vez, sem lote. Existe só para provar equivalência exata
    contra `precompute_predictions` (o caminho de produção agora); não é
    código de produção, não reflete nenhuma otimização."""
    booster_set = registry.for_as_of(as_of)
    calendar = build_calendar_features(
        [as_of], locale=calendar_locale, holidays=holidays, params=features_params.calendar
    )
    row = build_features(
        item_sales,
        items,
        as_of,
        store_id=store_id,
        calendar=calendar,
        params=features_params,
        item_ids=[item_id],
    ).with_columns(pl.lit(horizon).alias(qgbm_module.RISK_WINDOW_FEATURE))
    feature_cols = list(booster_set.feature_cols)
    encoded = registry.categorical_encoding.encode(row.select(*feature_cols))
    x = encoded.to_numpy()
    raw = {q: float(booster_set.boosters[q].predict(x)[0]) for q in quantiles}
    corrected = registry.correction.apply(raw)
    return {q: max(0.0, corrected[q]) for q in quantiles}


def test_precompute_predictions_bate_exato_com_calculo_item_a_item(tmp_path: Path) -> None:
    """Requisito explícito da aprovação condicional do batching (Sprint 16):
    loop vs. lote tem que bater BIT A BIT (`==` em float, não `pytest.approx`
    nem `allclose`) -- LightGBM não reduz nada entre linhas na predição (só
    no treino, ver docstring de `precompute_predictions`), então empilhar
    itens antes de `booster.predict()` não pode mudar nenhum valor
    individual. Compara a função de PRODUÇÃO (`precompute_predictions`,
    usada por `run_arm`) contra uma réplica independente do cálculo linha a
    linha (`_predicao_item_a_item`, acima) -- inclusive depois da
    `NonCrossingCorrection`, não só o valor bruto do booster."""
    item_ids = [f"i{k}" for k in range(5)]
    start = date(2021, 1, 4)
    sales = _synthetic_sales(item_ids, start=start, n_days=120, seed=7)
    items = _items(item_ids)
    horizon_by_item = dict.fromkeys(item_ids, 1)
    review_period_by_item = dict.fromkeys(item_ids, 7)
    features_params = _features_params()
    quantiles = [0.5, 0.8, 0.9]
    hyperparams = _hyperparams(tmp_path / "cache", num_boost_round=30)
    as_of = start + timedelta(days=100)

    registry = train_quantile_models(
        sales,
        items,
        horizon_by_item,
        store_id=_STORE,
        item_ids=item_ids,
        retrain_dates=[as_of],
        earliest_training_origin=start + timedelta(days=7),
        origin_cadence_days=7,
        quantiles=quantiles,
        features_params=features_params,
        calendar_locale=_LOCALE,
        holidays=_HOLIDAYS,
        hyperparams=hyperparams,
        cache_dir=tmp_path / "cache",
        config_hash="teste-batching",
    )

    em_lote = precompute_predictions(
        sales,
        items,
        store_id=_STORE,
        item_ids=item_ids,
        horizon_by_item=horizon_by_item,
        review_period_by_item=review_period_by_item,
        decision_dates=[as_of],
        quantiles=quantiles,
        features_params=features_params,
        calendar_locale=_LOCALE,
        holidays=_HOLIDAYS,
        registry=registry,
    )

    assert set(em_lote) == set(item_ids)
    for item_id in item_ids:
        item_sales = sales.filter(pl.col("item_id") == item_id)
        item_a_item = _predicao_item_a_item(
            registry=registry,
            item_sales=item_sales,
            items=items,
            store_id=_STORE,
            item_id=item_id,
            as_of=as_of,
            horizon=horizon_by_item[item_id],
            quantiles=quantiles,
            features_params=features_params,
            calendar_locale=_LOCALE,
            holidays=_HOLIDAYS,
        )
        obtido = em_lote[item_id][as_of]
        for q in quantiles:
            assert obtido[q] == item_a_item[q], (
                f"item={item_id} quantile={q}: lote={obtido[q]!r} != item_a_item={item_a_item[q]!r}"
            )


def test_precompute_predictions_review_period_nao_uniforme_levanta_erro_claro(
    tmp_path: Path,
) -> None:
    """Achado da revisão da Sprint 16: `precompute_predictions` assume UMA
    grade de `decision_dates` compartilhada por todos os itens -- se
    `review_period_by_item` não for uniforme, isso é falso, e o erro tem que
    ser explícito na hora do precompute, nunca um `as_of` faltando
    silenciosamente na hora da decisão."""
    item_ids = ["i0", "i1"]
    start = date(2021, 1, 4)
    sales = _synthetic_sales(item_ids, start=start, n_days=60, seed=1)
    items = _items(item_ids)
    horizon_by_item = dict.fromkeys(item_ids, 1)
    features_params = _features_params()
    hyperparams = _hyperparams(tmp_path / "cache", num_boost_round=10)
    as_of = start + timedelta(days=50)

    registry = train_quantile_models(
        sales,
        items,
        horizon_by_item,
        store_id=_STORE,
        item_ids=item_ids,
        retrain_dates=[as_of],
        earliest_training_origin=start + timedelta(days=7),
        origin_cadence_days=7,
        quantiles=[0.5],
        features_params=features_params,
        calendar_locale=_LOCALE,
        holidays=_HOLIDAYS,
        hyperparams=hyperparams,
        cache_dir=tmp_path / "cache",
        config_hash="teste-review-nao-uniforme",
    )

    with pytest.raises(ValueError, match="review_period_by_item não é uniforme"):
        precompute_predictions(
            sales,
            items,
            store_id=_STORE,
            item_ids=item_ids,
            horizon_by_item=horizon_by_item,
            review_period_by_item={"i0": 7, "i1": 14},  # não uniforme, de propósito
            decision_dates=[as_of],
            quantiles=[0.5],
            features_params=features_params,
            calendar_locale=_LOCALE,
            holidays=_HOLIDAYS,
            registry=registry,
        )


def test_quantile_gbm_forecaster_so_consulta_o_precomputado_nunca_calcula() -> None:
    """`QuantileGbmForecaster` (Sprint 16) não guarda mais `item_sales`,
    `registry`, `calendar_locale` nem nada que permita calcular algo na hora
    -- só um dicionário já pronto. `predict_quantiles` fora do `as_of`
    pré-computado tem que recusar alto e claro, nunca recalcular por baixo
    dos panos."""
    as_of = date(2021, 1, 1)
    quantiles = [0.5, 0.9]
    precomputed = {as_of: {0.5: 10.0, 0.9: 20.0}}
    fc = QuantileGbmForecaster(item_id="i0", expected_horizon=7, precomputed=precomputed)
    historico_vazio = pl.DataFrame(
        {"date": [], "units_sold": []}, schema={"date": pl.Date, "units_sold": pl.Float64}
    )
    fc.fit(historico_vazio, as_of)

    resultado = fc.predict_quantiles(as_of, 7, quantiles)
    assert resultado["value"].to_list() == [10.0, 20.0]

    outro_as_of = as_of + timedelta(days=7)  # fora de `precomputed`, de propósito
    # satisfaz a guarda de fit()/as_of -- o que falta é o lookup em precomputed
    fc.fit(historico_vazio, outro_as_of)
    with pytest.raises(ValueError, match="nenhuma previsão pré-computada"):
        fc.predict_quantiles(outro_as_of, 7, quantiles)

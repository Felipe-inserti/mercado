"""Previsão quantílica por LightGBM (`QuantileGbmForecaster`, Sprint 15):
braço 3. Um LightGBM por quantil de `model.quantiles` (grade compartilhada,
nunca uma lista nova -- ver `motor.config.QuantileGbmParams`), modelo GLOBAL
sobre o painel inteiro do subconjunto -- nunca um modelo por SKU.

ARQUITETURA -- por que o treino não acontece dentro de `fit()`: o protocolo
`Forecaster` reduzido (`motor.forecast.base`, grão de um par loja-item) só
entrega a `fit()` o histórico DESTE item. Um modelo global, por definição,
precisa ver todos os itens ao mesmo tempo para treinar -- não cabe dentro da
chamada de um único par. A solução, sem alterar `Simulator`/`DecisionContext`/
`Policy` (contratos que CLAUDE.md, seção 5, pede para não tocar sem avisar):
o treino pesado acontece UMA VEZ, fora do loop por item
(`train_quantile_models`, chamado por `motor.experiments.run.run_arm` antes
de montar os `Simulator`s), produzindo um `QuantileModelRegistry`
compartilhado. Cada par recebe um `QuantileGbmForecaster` leve, que só
CONSULTA o registro -- `fit()` não treina nada, só guarda `as_of` (mesmo
padrão defensivo de `NaiveForecaster.fit`).

ALVO -- `target_for_origin` usa `motor.forecast.base.risk_window_bounds`, a
MESMA janela que `NaiveForecaster`/`StatisticalForecaster` já usam nos seus
backtests de resíduos (`[as_of, as_of+horizon-1]`, incluindo o próprio
`as_of`). Os três consumidores delegam nessa função única de propósito --
ver `tests/test_risk_window_consistency.py`.

JANELA DE TREINO -- EXPANSIVA com piso mínimo (`min_training_origins`),
decisão aprovada explicitamente, não deslizante. A tensão "regime antigo
mistura com recente" é resolvida por dentro via peso de amostra por idade
(`decay_half_life_days`, default `None` = neutro, sem decaimento) -- não por
uma janela mais curta. Ver `motor.config.QuantileGbmParams`.

NÃO-CRUZAMENTO -- correção por reordenação (`NonCrossingCorrection`): ordena
os valores previstos em ordem crescente e reatribui aos quantis (já
ascendentes por construção). Medido antes de implementar (não in-sample, não
subtreinado -- ver o relatório da sprint): ~35% das previsões têm alguma
inversão adjacente, concentrada nos quantis altos (q0.8/q0.9 ~15%, q0.9/q0.95
~19%) e ESTÁVEL entre in-sample, fora da amostra e com 15x mais rounds -- é
estrutura do problema (dois modelos independentes por linha, sem restrição de
monotonicidade entre eles), não artefato de medição. A correção não é
cosmética: o log de quantas vezes ela atua (`NonCrossingCorrection.n_corrected`)
é registrado no manifesto do braço, e o número esperado é grande, não raro.

CATEGÓRICAS -- mapeamento FIXO valor->código (`build_categorical_encoding`),
construído sobre o CADASTRO inteiro de `items` do subconjunto, nunca sobre as
linhas de treino de uma origem específica -- um item sem histórico numa
origem inicial recebe o mesmo código mais tarde (`astype('category')`
recalculado por fatia reordenaria os códigos entre origens).

`stock` FORA -- decisão explícita (Sprint 15, não revisitada sem conversa
nova): o dataset público não tem saldo, uma feature derivada dele só
existiria dentro da simulação. Ver CLAUDE.md, seção 4.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Final

import lightgbm as lgb
import numpy as np
import polars as pl

from motor.config import FeaturesParams, QuantileGbmParams
from motor.features.build import build_features, build_training_matrix
from motor.features.calendar import StoreLocale, build_calendar_features
from motor.forecast.base import risk_window_bounds

RISK_WINDOW_FEATURE: Final = "risk_window_days"
"""Feature extra, adicionada por este módulo -- FORA da lista
`features.active_features` (Sprint 14), porque não é uma feature geral de
previsão: é o comprimento da própria janela de alvo, necessária para que um
modelo GLOBAL saiba, linha a linha, para qual horizonte está prevendo (hoje
uniforme em 10 dias no subconjunto real, mas a coluna existe para que um
fornecedor com lead_time/review_period diferente não vire ambiguidade
silenciosa: duas linhas com o mesmo vetor de features e alvos de janelas de
tamanhos diferentes, sem nenhum jeito de o modelo distinguir uma da outra)."""

_LGBM_FIXED_PARAMS: Final = {
    "objective": "quantile",
    "deterministic": True,
    "force_row_wise": True,
    "verbosity": -1,
}
"""Invariantes de determinismo (CLAUDE.md, seção 2) -- não configuráveis."""

_CATEGORICAL_CANDIDATES: Final = ("category", "item_class", "is_perishable")


class InsufficientTrainingHistoryError(RuntimeError):
    """A primeira origem do backtest não atinge `min_training_origins` -- ver
    docstring de `motor.config.QuantileGbmParams`. Nunca deixe passar como
    fit silencioso com poucas origens."""


# --------------------------------------------------------------------------
# alvo
# --------------------------------------------------------------------------


def target_for_origin(
    sales: pl.DataFrame,
    *,
    item_ids: Sequence[str],
    horizon_by_item: dict[str, int],
    as_of: date,
) -> pl.DataFrame:
    """`target(item_id)` = soma de `units_sold` na janela de risco DESTE item
    (`risk_window_bounds(as_of, horizon_by_item[item_id])`) -- uma linha por
    item em `item_ids`, na mesma ordem. Item sem nenhuma linha na janela
    recebe `target=0.0`: aqui o alvo é um período já ocorrido (treino), a
    ausência de venda registrada É zero, não "não sei" (diferente do
    tratamento de histórico em `motor.features.build`, que olha para trás a
    partir de `as_of` e pode genuinamente não ter dado).
    """
    bounds = [
        (item_id, *risk_window_bounds(as_of, horizon_by_item[item_id])) for item_id in item_ids
    ]
    windows = pl.DataFrame(bounds, schema=["item_id", "_start", "_end"], orient="row")

    joined = sales.join(windows, on="item_id", how="inner").filter(
        (pl.col("date") >= pl.col("_start")) & (pl.col("date") < pl.col("_end"))
    )
    agg = joined.group_by("item_id").agg(pl.col("units_sold").sum().alias("target"))
    return (
        pl.DataFrame({"item_id": list(item_ids)})
        .join(agg, on="item_id", how="left")
        .with_columns(pl.col("target").fill_null(0.0))
    )


# --------------------------------------------------------------------------
# categóricas: mapeamento fixo
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CategoricalEncoding:
    """Mapeamento FIXO valor -> código inteiro, por coluna. Ver docstring do
    módulo -- construído uma vez sobre `items`, nunca recalculado por fatia."""

    columns: tuple[str, ...]
    maps: dict[str, dict[object, int]]

    def encode(self, frame: pl.DataFrame) -> pl.DataFrame:
        if not self.columns:
            return frame
        return frame.with_columns(
            [
                pl.col(c).replace_strict(self.maps[c], default=None, return_dtype=pl.Int32)
                for c in self.columns
            ]
        )


def build_categorical_encoding(items: pl.DataFrame, columns: Sequence[str]) -> CategoricalEncoding:
    maps = {
        c: {v: i for i, v in enumerate(sorted(items[c].unique().drop_nulls().to_list(), key=str))}
        for c in columns
    }
    return CategoricalEncoding(columns=tuple(columns), maps=maps)


# --------------------------------------------------------------------------
# não-cruzamento
# --------------------------------------------------------------------------


@dataclass
class NonCrossingCorrection:
    """Correção por reordenação: ordena os valores previstos em ordem
    crescente e reatribui aos quantis (já ascendentes por construção).
    `n_calls`/`n_corrected` acumulam ao longo de TODAS as chamadas de um
    braço -- é o log de higiene (ou de alarme) do "pronto quando" da sprint."""

    quantiles: tuple[float, ...]
    n_calls: int = 0
    n_corrected: int = 0

    def apply(self, raw_by_quantile: dict[float, float]) -> dict[float, float]:
        self.n_calls += 1
        raw_values = [raw_by_quantile[q] for q in self.quantiles]
        sorted_values = sorted(raw_values)
        if sorted_values != raw_values:
            self.n_corrected += 1
        return dict(zip(self.quantiles, sorted_values, strict=True))


# --------------------------------------------------------------------------
# grade de origens
# --------------------------------------------------------------------------


def _weekly_origins(start: date, end_inclusive: date, cadence_days: int) -> list[date]:
    origins = []
    d = start
    while d <= end_inclusive:
        origins.append(d)
        d += timedelta(days=cadence_days)
    return origins


def _sample_weight(age_days: np.ndarray, half_life_days: float | None) -> np.ndarray:
    """`weight = 0.5 ** (idade / half_life)` -- `None` é neutro (peso 1.0 pra
    tudo, byte a byte igual a uma janela expansiva sem ponderação)."""
    if half_life_days is None:
        return np.ones_like(age_days, dtype=np.float64)
    return np.power(0.5, age_days / half_life_days)


# --------------------------------------------------------------------------
# cache
# --------------------------------------------------------------------------


def compute_config_hash(
    *,
    hyperparams: QuantileGbmParams,
    features_params: FeaturesParams,
    quantiles: Sequence[float],
    store_id: str,
    item_ids: Sequence[str],
    horizon_by_item: Mapping[str, int],
) -> str:
    """Hash determinístico de TUDO que afeta o resultado do treino -- a chave
    de cache inclui isto, não só a data de retreino (a forma mais fácil de
    produzir resultado falso e reprodutível é reusar um modelo treinado com
    outra config).

    `horizon_by_item` (achado na revisão da Sprint 16: faltava aqui) entra
    duas vezes dentro de `train_quantile_models` -- no ALVO de treino
    (`target_for_origin`, demanda acumulada na janela de risco) e na feature
    `RISK_WINDOW_FEATURE` -- então muda o resultado do treino tanto quanto
    `hyperparams`/`features_params`. Sem isto na chave, dois treinos com
    `lead_time` diferente (portanto horizonte diferente) mas mesmo
    `store_id`/`item_ids`/`quantiles`/hiperparâmetros colidiam no mesmo
    diretório de cache -- exatamente o cenário de uma varredura de
    sensibilidade em `lead_time` (Sprint 16)."""
    payload = {
        "quantile_gbm": hyperparams.model_dump(mode="json", exclude={"model_cache_dir"}),
        "features": features_params.model_dump(mode="json"),
        "quantiles": list(quantiles),
        "store_id": store_id,
        "item_ids": sorted(item_ids),
        "horizon_by_item": dict(sorted(horizon_by_item.items())),
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _cache_dir_for(cache_root: Path, config_hash: str, retrain_date: date) -> Path:
    return cache_root / config_hash / retrain_date.isoformat()


def _cache_is_valid(cache_dir: Path, quantiles: Sequence[float]) -> bool:
    metadata_path = cache_dir / "metadata.json"
    if not metadata_path.exists():
        return False
    metadata = json.loads(metadata_path.read_text())
    if metadata.get("quantiles") != list(quantiles):
        return False
    return all((cache_dir / f"q_{q}.txt").exists() for q in quantiles)


def _load_boosters(cache_dir: Path, quantiles: Sequence[float]) -> dict[float, lgb.Booster]:
    return {q: lgb.Booster(model_file=str(cache_dir / f"q_{q}.txt")) for q in quantiles}


def _save_cache(
    cache_dir: Path,
    boosters: dict[float, lgb.Booster],
    *,
    quantiles: Sequence[float],
    config_hash: str,
    retrain_date: date,
    n_training_rows: int,
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    for q, booster in boosters.items():
        booster.save_model(str(cache_dir / f"q_{q}.txt"))
    metadata = {
        "quantiles": list(quantiles),
        "config_hash": config_hash,
        "retrain_date": retrain_date.isoformat(),
        "n_training_rows": n_training_rows,
    }
    (cache_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True))


# --------------------------------------------------------------------------
# registro de modelos
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class QuantileBoosterSet:
    retrain_date: date
    boosters: dict[float, lgb.Booster]
    feature_cols: tuple[str, ...]
    n_training_rows: int


class QuantileModelRegistry:
    """Um `QuantileBoosterSet` por data de retreino, mais a correção de
    não-cruzamento COMPARTILHADA entre todos os pares e todas as datas (o
    contador de `NonCrossingCorrection` é do braço inteiro, não por item)."""

    def __init__(
        self,
        booster_sets: Sequence[QuantileBoosterSet],
        correction: NonCrossingCorrection,
        categorical_encoding: CategoricalEncoding,
    ) -> None:
        if not booster_sets:
            msg = "QuantileModelRegistry precisa de pelo menos um QuantileBoosterSet"
            raise ValueError(msg)
        self._by_date = {bs.retrain_date: bs for bs in booster_sets}
        self._sorted_dates = sorted(self._by_date)
        self.correction = correction
        self.categorical_encoding = categorical_encoding

    def for_as_of(self, as_of: date) -> QuantileBoosterSet:
        candidatos = [d for d in self._sorted_dates if d <= as_of]
        if not candidatos:
            msg = (
                f"nenhum retreino disponível em ou antes de as_of={as_of!r} -- "
                f"primeiro retreino é {self._sorted_dates[0]!r}"
            )
            raise ValueError(msg)
        return self._by_date[max(candidatos)]


# --------------------------------------------------------------------------
# treino (compartilhado, fora do loop por item)
# --------------------------------------------------------------------------


def _feature_columns(features_params: FeaturesParams) -> list[str]:
    return [*features_params.active_features, RISK_WINDOW_FEATURE]


def train_quantile_models(
    sales: pl.DataFrame,
    items: pl.DataFrame,
    horizon_by_item: dict[str, int],
    *,
    store_id: str,
    item_ids: Sequence[str],
    retrain_dates: Sequence[date],
    earliest_training_origin: date,
    origin_cadence_days: int,
    quantiles: Sequence[float],
    features_params: FeaturesParams,
    calendar_locale: StoreLocale,
    holidays: pl.DataFrame,
    hyperparams: QuantileGbmParams,
    cache_dir: Path,
    config_hash: str,
) -> QuantileModelRegistry:
    """Treina (ou carrega do cache) um `QuantileBoosterSet` por data em
    `retrain_dates`. Janela de treino EXPANSIVA: a cada retreino, usa toda
    origem semanal desde `earliest_training_origin` cujo alvo de TODOS os
    itens já é conhecido (`origin + max(horizon) <= retrain_date` -- conservador
    de propósito: com horizontes diferentes por item, uma origem só entra se
    for segura para o item de maior horizonte, nunca por item individualmente
    dentro do mesmo painel compartilhado).
    """
    categorical_cols = [c for c in _CATEGORICAL_CANDIDATES if c in features_params.active_features]
    encoding = build_categorical_encoding(items, categorical_cols)
    feature_cols = _feature_columns(features_params)
    categorical_idx = [feature_cols.index(c) for c in categorical_cols]

    max_horizon = max(horizon_by_item[i] for i in item_ids)
    all_origins = _weekly_origins(earliest_training_origin, max(retrain_dates), origin_cadence_days)

    booster_sets: list[QuantileBoosterSet] = []
    for retrain_date in sorted(retrain_dates):
        usable = [o for o in all_origins if o + timedelta(days=max_horizon) <= retrain_date]
        if len(usable) < hyperparams.min_training_origins:
            msg = (
                f"retreino em {retrain_date}: só {len(usable)} origem(ns) de treino disponível(is) "
                "(mínimo configurado, quantile_gbm.min_training_origins="
                f"{hyperparams.min_training_origins}). Primeira origem viável configurada: "
                f"{earliest_training_origin}. Aumente o histórico disponível ou reduza o piso -- "
                "nunca deixe passar como fit silencioso com poucas origens."
            )
            raise InsufficientTrainingHistoryError(msg)

        this_cache_dir = _cache_dir_for(cache_dir, config_hash, retrain_date)
        if _cache_is_valid(this_cache_dir, quantiles):
            boosters = _load_boosters(this_cache_dir, quantiles)
            n_rows = json.loads((this_cache_dir / "metadata.json").read_text())["n_training_rows"]
        else:
            panel = build_training_matrix(
                sales,
                items,
                usable,
                store_id=store_id,
                locale=calendar_locale,
                holidays=holidays,
                params=features_params,
                item_ids=item_ids,
            )
            targets = pl.concat(
                [
                    target_for_origin(
                        sales, item_ids=item_ids, horizon_by_item=horizon_by_item, as_of=o
                    ).with_columns(pl.lit(o).alias("as_of"))
                    for o in usable
                ]
            )
            training = panel.join(targets, on=["item_id", "as_of"], how="inner").with_columns(
                pl.col("item_id")
                .replace_strict(horizon_by_item, return_dtype=pl.Int64)
                .alias(RISK_WINDOW_FEATURE),
                (pl.lit(retrain_date) - pl.col("as_of")).dt.total_days().alias("_age_days"),
            )

            encoded = encoding.encode(training.select(*feature_cols))
            x = encoded.to_numpy()
            y = training["target"].to_numpy()
            weight = _sample_weight(
                training["_age_days"].to_numpy(), hyperparams.decay_half_life_days
            )

            boosters = {}
            for q in quantiles:
                lgb_params = {
                    **_LGBM_FIXED_PARAMS,
                    "alpha": q,
                    "seed": hyperparams.seed,
                    "learning_rate": hyperparams.learning_rate,
                    "num_leaves": hyperparams.num_leaves,
                    "num_threads": hyperparams.num_threads,
                }
                dataset = lgb.Dataset(
                    x,
                    label=y,
                    weight=weight,
                    feature_name=feature_cols,
                    categorical_feature=categorical_idx,
                    free_raw_data=False,
                )
                boosters[q] = lgb.train(
                    lgb_params, dataset, num_boost_round=hyperparams.num_boost_round
                )
            n_rows = training.height
            _save_cache(
                this_cache_dir,
                boosters,
                quantiles=quantiles,
                config_hash=config_hash,
                retrain_date=retrain_date,
                n_training_rows=n_rows,
            )

        booster_sets.append(
            QuantileBoosterSet(
                retrain_date=retrain_date,
                boosters=boosters,
                feature_cols=tuple(feature_cols),
                n_training_rows=n_rows,
            )
        )

    correction = NonCrossingCorrection(quantiles=tuple(sorted(quantiles)))
    return QuantileModelRegistry(booster_sets, correction, encoding)


# --------------------------------------------------------------------------
# previsão em lote (Sprint 16: batching de `booster.predict()`)
# --------------------------------------------------------------------------


def precompute_predictions(
    sales: pl.DataFrame,
    items: pl.DataFrame,
    *,
    store_id: str,
    item_ids: Sequence[str],
    horizon_by_item: Mapping[str, int],
    review_period_by_item: Mapping[str, int],
    decision_dates: Sequence[date],
    quantiles: Sequence[float],
    features_params: FeaturesParams,
    calendar_locale: StoreLocale,
    holidays: pl.DataFrame,
    registry: QuantileModelRegistry,
) -> dict[str, dict[date, dict[float, float]]]:
    """Pré-computa TODA previsão que o braço 3 vai pedir durante a simulação
    -- uma por (item_id, as_of) em `item_ids` x `decision_dates` -- ANTES do
    loop por item de `run_arm`, mesmo padrão arquitetural de
    `train_quantile_models` (treino também acontece uma vez, fora do loop
    por item -- ver docstring do módulo). `QuantileGbmForecaster` não
    computa mais nada em `predict_quantiles`: só consulta este dicionário.

    ACHADO da revisão da Sprint 16 (perfil de uma data de decisão real, 275
    itens): o custo de `booster.predict()` é dominado por overhead FIXO por
    chamada (atravessar a fronteira Python/C++, validar o array), não por
    travessia de árvore -- uma previsão em lote (N itens de uma vez) é até
    270x mais rápida que N chamadas de uma linha, com saída IDÊNTICA bit a
    bit (`np.array_equal`, não só `allclose`; LightGBM não reduz nada entre
    linhas na predição, só no treino -- provado em
    `tests/test_quantile_gbm.py::test_predict_em_lote_bate_bit_a_bit_com_loop`).
    Por isso este código constrói as features EXATAMENTE como antes -- item
    por item, mesmo `build_features`/`build_calendar_features`, mesmo custo
    de `.collect()` do polars (~63% do tempo de uma data, medido; é dívida
    técnica REGISTRADA, não atacada aqui -- mudar isso é mudar a lógica de
    `motor.features.build`, fora do escopo desta sprint) -- e só empilha as
    linhas resultantes ANTES de chamar `booster.predict()`, uma vez por
    quantil em vez de uma vez por item.

    `decision_dates` PRECISA ser exatamente a grade de dias em que o
    `Simulator` de cada item vai pedir previsão
    (`motor.simulator.engine.review_every_n_days(reference=simulation.start_date,
    period_days=review_period_days)`) -- hoje isso coincide com
    `model.retrain_cadence_days` porque as duas grades têm o mesmo período e
    a mesma referência (`review_period_by_item` uniforme e igual a
    `retrain_cadence_days` no subconjunto real, confirmado abaixo, não
    assumido). Se algum item tiver `review_period_days` diferente dos
    demais, este código recusa rodar -- silenciosamente supor uma grade
    única quando ela não é mais única produziria `as_of` sem previsão
    pré-computada para alguns itens, e `QuantileGbmForecaster.predict_quantiles`
    percorreria a decisão errada sem avisar."""
    valores_review = {review_period_by_item[i] for i in item_ids}
    if len(valores_review) > 1:
        msg = (
            f"review_period_by_item não é uniforme ({sorted(valores_review)!r}) -- "
            "precompute_predictions assume UMA grade de decision_dates compartilhada "
            "por todos os itens (ver docstring). Itens com review_period diferente "
            "pedem previsão em dias diferentes; pré-computar com uma grade única "
            "deixaria alguns sem previsão pronta na hora certa."
        )
        raise ValueError(msg)

    item_sales_by_item = {i: sales.filter(pl.col("item_id") == i) for i in item_ids}
    predictions: dict[str, dict[date, dict[float, float]]] = {i: {} for i in item_ids}

    for as_of in sorted(decision_dates):
        booster_set = registry.for_as_of(as_of)
        disponiveis = set(booster_set.boosters)
        faltando = [q for q in quantiles if q not in disponiveis]
        if faltando:
            msg = (
                f"quantil(is) {faltando} fora da grade treinada ({sorted(disponiveis)}) -- "
                "sem interpolação silenciosa: ajuste model.quantiles ou o alpha pedido."
            )
            raise ValueError(msg)
        feature_cols = list(booster_set.feature_cols)

        rows = []
        for item_id in item_ids:
            calendar = build_calendar_features(
                [as_of], locale=calendar_locale, holidays=holidays, params=features_params.calendar
            )
            row = build_features(
                item_sales_by_item[item_id],
                items,
                as_of,
                store_id=store_id,
                calendar=calendar,
                params=features_params,
                item_ids=[item_id],
            ).with_columns(pl.lit(horizon_by_item[item_id]).alias(RISK_WINDOW_FEATURE))
            rows.append(row)
        stacked = pl.concat(rows)
        encoded = registry.categorical_encoding.encode(stacked.select(*feature_cols))
        x = encoded.to_numpy()

        raw_by_quantile = {q: booster_set.boosters[q].predict(x) for q in quantiles}
        for i, item_id in enumerate(item_ids):
            raw = {q: float(raw_by_quantile[q][i]) for q in quantiles}
            corrected = registry.correction.apply(raw)
            predictions[item_id][as_of] = {q: max(0.0, corrected[q]) for q in quantiles}

    return predictions


# --------------------------------------------------------------------------
# adaptador por par loja-item (protocolo `Forecaster` reduzido)
# --------------------------------------------------------------------------


class QuantileGbmForecaster:
    """`Forecaster` (protocolo reduzido, grão de um par loja-item) que
    CONSULTA previsões já pré-computadas em lote (`precompute_predictions`,
    Sprint 16) -- não treina nem prevê nada em `fit()`/`predict_quantiles()`,
    só faz `lookup`. Ver docstring do módulo (arquitetura) e de
    `precompute_predictions` (por que o lote existe) para o porquê.
    """

    def __init__(
        self,
        *,
        item_id: str,
        expected_horizon: int,
        precomputed: Mapping[date, dict[float, float]],
    ) -> None:
        self._item_id = item_id
        self._expected_horizon = expected_horizon
        self._precomputed = precomputed
        self._as_of: date | None = None

    def fit(self, history: pl.DataFrame, as_of: date) -> None:
        """Não treina nada -- só guarda `as_of` e confere vazamento no
        argumento recebido (mesma defesa própria de `NaiveForecaster.fit`,
        redundante com o corte do simulador mas não dependente só dele)."""
        dates: list[date] = history["date"].to_list()
        if dates and max(dates) >= as_of:
            msg = f"history contém data >= as_of: {max(dates)} >= {as_of}"
            raise AssertionError(msg)
        self._as_of = as_of

    def predict_quantiles(self, as_of: date, horizon: int, quantiles: list[float]) -> pl.DataFrame:
        if self._as_of != as_of:
            msg = (
                f"predict_quantiles(as_of={as_of!r}) chamado sem fit() correspondente "
                f"(último fit foi as_of={self._as_of!r}) -- mesma garantia de "
                "BasestockPolicy/compute_order_quantity: os dois lados precisam concordar."
            )
            raise AssertionError(msg)
        if horizon != self._expected_horizon:
            msg = (
                f"horizon={horizon} não bate com o horizonte usado no treino deste item "
                f"({self._expected_horizon}) -- previsão treinada para outra janela de risco "
                "não pode ser consumida aqui."
            )
            raise ValueError(msg)
        if as_of not in self._precomputed:
            msg = (
                f"item {self._item_id!r}: nenhuma previsão pré-computada para as_of={as_of!r} "
                f"(datas disponíveis: {sorted(self._precomputed)!r}). "
                "predict_quantiles não calcula mais nada na hora (Sprint 16, batching) -- "
                "isto significa que decision_dates passado a precompute_predictions não "
                "cobriu todo dia em que o Simulator pede decisão para este item. Não "
                "interpolar/recalcular aqui: corrija a grade de decision_dates."
            )
            raise ValueError(msg)

        corrected = self._precomputed[as_of]
        faltando = [q for q in quantiles if q not in corrected]
        if faltando:
            msg = (
                f"quantil(is) {faltando} fora da grade treinada ({sorted(corrected)}) -- "
                "sem interpolação silenciosa: ajuste model.quantiles ou o alpha pedido."
            )
            raise ValueError(msg)
        values = [corrected[q] for q in quantiles]
        return pl.DataFrame({"quantile": quantiles, "value": values})

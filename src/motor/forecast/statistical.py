"""Previsão estatística (`StatisticalForecaster`, Sprint 12): nível recente
deseasonalizado x índice de sazonalidade semanal, escalado para a demanda
ACUMULADA na janela de risco, com quantis empíricos dos resíduos do próprio
backtest.

Contrato: `motor.forecast.base.Forecaster`, grão de um par loja-item (Sprint 6).
É a previsão que sustenta o braço 2 (nível-alvo, `motor.policy.basestock`):
diferente de `motor.forecast.naive.NaiveForecaster`, reage à FORMA da demanda
dentro da semana (ex.: fim de semana mais forte que dia útil) em vez de tratar
todo dia como intercambiável -- é exatamente o ponto cego do baseline ERP
documentado em `config/params.yaml` (`erp_baseline`, CHECK 2 da revisão).

MODELO -- dois componentes, ambos recalculados a partir de janelas móveis que
terminam ESTRITAMENTE antes de um `cutoff`, nunca do histórico inteiro de uma
vez (ver o alerta abaixo sobre vazamento por feature global):

1. Índice sazonal semanal (`_seasonal_indices`): para cada dia ISO da semana
   (1=segunda .. 7=domingo), a razão entre a média de `units_sold` naquele dia
   da semana e a média geral, ambas medidas numa janela de `seasonal_window_weeks`
   semanas terminando em `cutoff`. Dia da semana sem nenhuma ocorrência na
   janela (ou janela sem nenhum dado) recebe índice neutro 1.0 -- comportamento
   definido, não exceção.
2. Nível recente (`_recent_level`): média dos valores DESEASONALIZADOS
   (`valor / índice_do_dia_da_semana`) numa janela mais curta,
   `level_window_weeks`, também terminando em `cutoff`. Deseasonalizar antes de
   tirar a média evita que a composição de dias-da-semana que calhou de cair
   dentro da janela recente enviese o nível (ex.: uma janela de 4 semanas com
   mais sábados que domingos).

Previsão diária de um dia `d` (dia da semana `w`) = `nível x índice[w]`.
Ponto central da demanda ACUMULADA no horizonte = soma dessa previsão diária
para os `horizon` dias a partir de `as_of` -- é uma soma de PONTOS, não de
quantis (a regra que a soma de quantis diários viola não se aplica à soma de
pontos centrais, que é uma estatística linear).

VAZAMENTO POR FEATURE GLOBAL (CLAUDE.md, seção 8) -- o motivo de recalcular os
dois componentes a cada `cutoff`, em vez de calcular o índice sazonal UMA VEZ
sobre o histórico inteiro visível e reaproveitá-lo: um índice global misturaria
dias de depois de um candidato de backtest `t` na previsão feita EM `t`,
inflando a informação disponível naquele ponto e produzindo resíduos otimistas
demais (sazonalidade "de brinde" que não estaria disponível na decisão real).
Isso é o mesmo tipo de vazamento que médias móveis e encodings de categoria
calculados sobre o histórico inteiro, só que aplicado à sazonalidade -- não
menos grave por ser menos óbvio. `_backtest_residuals` chama `_point_forecast`
com `cutoff=t` para cada candidato, e `_point_forecast` só olha janelas que
terminam em `cutoff` -- a garantia de "sem vazamento" nasce da própria forma
das janelas, não de um filtro adicional. Ver
`tests/test_statistical.py::test_indice_sazonal_de_um_periodo_nao_vaza_para_previsoes_de_periodo_anterior`
para o teste que pega especificamente essa classe de bug (distinto do teste
genérico de `history` sem `date >= as_of`, que só cobre o `as_of` real).
"""

from __future__ import annotations

from datetime import date, timedelta
from statistics import mean

import polars as pl

_ISO_WEEKDAYS = range(1, 8)


def _empirical_quantile(sorted_values: list[float], q: float) -> float:
    """Quantil empírico por interpolação linear sobre uma lista JÁ ordenada
    (tipo 7 de Hyndman & Fan, o default de `numpy`/`polars`).

    Mesma lógica de `motor.forecast.naive._empirical_quantile`, duplicada
    aqui de propósito: cada `Forecaster` é um componente autossuficiente e
    substituível (CLAUDE.md, seção 1) -- não há hoje um módulo de utilitários
    compartilhado entre eles, e criar um só para esta função de 15 linhas
    estaria fora do escopo desta sprint.
    """
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    position = q * (n - 1)
    lower = int(position)
    upper = min(lower + 1, n - 1)
    frac = position - lower
    return sorted_values[lower] + frac * (sorted_values[upper] - sorted_values[lower])


class StatisticalForecaster:
    """Nível recente deseasonalizado x índice de sazonalidade semanal, com
    quantis empíricos dos resíduos de um backtest que recalcula os dois
    componentes a cada candidato -- ver docstring do módulo para o porquê.

    Sem nenhum dia disponível em alguma janela, o componente correspondente
    cai para seu valor neutro (nível 0.0, índice 1.0) -- comportamento
    definido, não exceção, mesma convenção de `NaiveForecaster`. Sem
    `min_residual_samples` resíduos, os quantis colapsam no ponto central.
    """

    def __init__(
        self,
        *,
        level_window_weeks: int,
        seasonal_window_weeks: int,
        min_residual_samples: int,
    ) -> None:
        if level_window_weeks <= 0:
            msg = f"level_window_weeks deve ser positivo, recebeu {level_window_weeks}"
            raise ValueError(msg)
        if seasonal_window_weeks <= 0:
            msg = f"seasonal_window_weeks deve ser positivo, recebeu {seasonal_window_weeks}"
            raise ValueError(msg)
        if min_residual_samples <= 0:
            msg = f"min_residual_samples deve ser positivo, recebeu {min_residual_samples}"
            raise ValueError(msg)
        self._level_window_days = level_window_weeks * 7
        self._seasonal_window_days = seasonal_window_weeks * 7
        self._min_residual_samples = min_residual_samples
        self._demand_by_day: dict[date, float] = {}
        self._sorted_dates: list[date] = []

    def fit(self, history: pl.DataFrame, as_of: date) -> None:
        """Guarda `history` (já filtrado por `date < as_of` pelo simulador)
        num dicionário dia -> unidades. Mesma defesa própria de
        `NaiveForecaster.fit`: confere `as_of` contra o próprio `history`
        recebido, redundante com o corte do simulador mas não dependente
        só dele -- esta classe roda em produção, não só em teste.
        """
        dates: list[date] = history["date"].to_list()
        units: list[float] = history["units_sold"].to_list()
        if dates and max(dates) >= as_of:
            msg = f"history contém data >= as_of: {max(dates)} >= {as_of}"
            raise AssertionError(msg)
        self._demand_by_day = dict(zip(dates, units, strict=True))
        self._sorted_dates = sorted(self._demand_by_day)

    def predict_quantiles(self, as_of: date, horizon: int, quantiles: list[float]) -> pl.DataFrame:
        """Ponto central = soma da previsão diária (nível x índice sazonal)
        nos `horizon` dias a partir de `as_of`; quantil `q` = ponto central +
        quantil empírico dos resíduos do backtest, com piso em 0. Nunca soma
        quantis diários -- é a demanda acumulada direto, conforme o contrato
        de `motor.forecast.base.Forecaster`.
        """
        point = self._point_forecast(as_of, horizon)
        residuals = self._backtest_residuals(horizon)

        if len(residuals) < self._min_residual_samples:
            values = [point] * len(quantiles)
        else:
            sorted_residuals = sorted(residuals)
            values = [max(0.0, point + _empirical_quantile(sorted_residuals, q)) for q in quantiles]

        return pl.DataFrame({"quantile": quantiles, "value": values})

    def _window_dates(self, cutoff: date, window_days: int) -> list[date]:
        return [cutoff - timedelta(days=i) for i in range(window_days, 0, -1)]

    def _seasonal_indices(self, cutoff: date) -> dict[int, float]:
        """Índice multiplicativo por dia ISO da semana, medido na janela
        `[cutoff - seasonal_window_days, cutoff)` -- estritamente anterior a
        `cutoff`, nunca o histórico inteiro (ver docstring do módulo).

        Dia da semana sem nenhuma ocorrência na janela, ou janela sem nenhum
        dado (`overall_mean <= 0`), recebe índice neutro 1.0.
        """
        by_weekday: dict[int, list[float]] = {w: [] for w in _ISO_WEEKDAYS}
        all_values: list[float] = []
        for d in self._window_dates(cutoff, self._seasonal_window_days):
            value = self._demand_by_day.get(d)
            if value is not None:
                by_weekday[d.isoweekday()].append(value)
                all_values.append(value)

        overall_mean = mean(all_values) if all_values else 0.0
        if overall_mean <= 0.0:
            return dict.fromkeys(_ISO_WEEKDAYS, 1.0)

        return {
            w: (mean(values) / overall_mean) if values else 1.0 for w, values in by_weekday.items()
        }

    def _recent_level(self, cutoff: date, seasonal_indices: dict[int, float]) -> float:
        """Média dos valores deseasonalizados na janela
        `[cutoff - level_window_days, cutoff)` -- estritamente anterior a
        `cutoff`. Sem nenhum dia disponível na janela, devolve 0.0."""
        deseasonalized: list[float] = []
        for d in self._window_dates(cutoff, self._level_window_days):
            value = self._demand_by_day.get(d)
            if value is None:
                continue
            index = seasonal_indices[d.isoweekday()]
            deseasonalized.append(value / index if index > 0.0 else value)
        return mean(deseasonalized) if deseasonalized else 0.0

    def _point_forecast(self, cutoff: date, horizon: int) -> float:
        """Soma, para os `horizon` dias a partir de `cutoff`, de
        `nível x índice_sazonal[dia_da_semana]` -- os dois componentes
        calculados com `cutoff` como fronteira (ver docstring do módulo)."""
        seasonal_indices = self._seasonal_indices(cutoff)
        level = self._recent_level(cutoff, seasonal_indices)
        return sum(
            level * seasonal_indices[(cutoff + timedelta(days=i)).isoweekday()]
            for i in range(horizon)
        )

    def _backtest_residuals(self, horizon: int) -> list[float]:
        """Erros históricos do próprio modelo, medidos SÓ dentro do histórico
        visível -- mesmo crivo de `NaiveForecaster._backtest_residuals`: um
        dia `t` só vira amostra se os `horizon` dias seguintes (`t` até
        `t + horizon - 1`) estiverem TODOS presentes no histórico.

        `_point_forecast(cutoff=t, ...)` recalcula sazonalidade e nível
        usando só dados `< t` -- nunca um índice sazonal fixo calculado uma
        vez sobre o histórico inteiro e reaproveitado para todo `t` (ver o
        alerta de vazamento por feature global na docstring do módulo). Como
        `history` já chega a `fit` filtrado por `date < as_of` (garantia do
        simulador), `last_available < as_of` sempre, e todo `t` aceito
        satisfaz `t + horizon - 1 <= last_available < as_of`: o backtest
        nunca alcança `as_of` nem o ultrapassa.
        """
        if not self._sorted_dates:
            return []
        last_available = self._sorted_dates[-1]
        residuals: list[float] = []
        for t in self._sorted_dates:
            end_inclusive = t + timedelta(days=horizon - 1)
            if end_inclusive > last_available:
                continue
            window_days_needed = [t + timedelta(days=i) for i in range(horizon)]
            if not all(d in self._demand_by_day for d in window_days_needed):
                continue
            actual = sum(self._demand_by_day[d] for d in window_days_needed)
            forecast = self._point_forecast(cutoff=t, horizon=horizon)
            residuals.append(actual - forecast)
        return residuals

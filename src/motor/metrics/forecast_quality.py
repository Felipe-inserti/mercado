"""Métricas de qualidade de previsão (Sprint 24, etapa 24.2).

Puro: sem I/O, sem `motor.config.Params` -- recebe séries já alinhadas
(`pl.Series` ou listas) e devolve números simples, no mesmo espírito de
`motor.metrics.financial`. Quem chama (o backtest da 24.7) resolve os
parâmetros e passa os valores.

Todas as séries comparam a demanda ACUMULADA no horizonte (a saída do
`Forecaster`) com a demanda real acumulada da MESMA janela -- nunca diária.

CONVENÇÕES COMUNS
-----------------
- `mask` opcional (booleano; `False` = observação excluída). Serve para tirar
  da avaliação os dias censurados por ruptura provável.
- Observação com `None` em `forecast` (ou `naive_forecast`) é excluída; em
  `relative_mae` a exclusão vale para as DUAS contas (numerador e
  denominador), para que as duas médias usem exatamente os mesmos pontos.
  `None` em `actual` também exclui o ponto.
- Denominador zero (inclusive "nenhuma observação sobrou") devolve `None`.
  Nunca `inf` nem `NaN`: o chamador decide o que fazer com "sem resposta".
"""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl

Values = pl.Series | Sequence[float | None]
Mask = pl.Series | Sequence[bool]


def _as_list(values: Values) -> list[float | None]:
    return values.to_list() if isinstance(values, pl.Series) else list(values)


def _check_same_length(**named: Sequence[object]) -> None:
    lengths = {name: len(seq) for name, seq in named.items()}
    if len(set(lengths.values())) > 1:
        msg = f"séries com tamanhos diferentes: {lengths}"
        raise ValueError(msg)


def _kept_rows(*columns: Values, mask: Mask | None) -> list[tuple[float, ...]]:
    """Linhas (uma por observação) em que nenhuma coluna é `None` e a máscara
    não exclui. Devolve só números -- o resto das funções não vê `None`."""
    lists = [_as_list(col) for col in columns]
    keep = (
        list(mask.to_list() if isinstance(mask, pl.Series) else mask) if mask is not None else None
    )
    _check_same_length(**{f"coluna_{i}": col for i, col in enumerate(lists)})
    if keep is not None:
        _check_same_length(coluna_0=lists[0], mask=keep)
    rows: list[tuple[float, ...]] = []
    for i, row in enumerate(zip(*lists, strict=True)):
        if keep is not None and not keep[i]:
            continue
        if any(v is None for v in row):
            continue
        rows.append(tuple(float(v) for v in row if v is not None))
    return rows


def relative_mae(
    actual: Values, forecast: Values, naive_forecast: Values, mask: Mask | None = None
) -> float | None:
    """MAE do método / MAE do naive sazonal, na MESMA janela de teste.

    Abaixo de 1 = o método é melhor que o naive; acima de 1 = pior.

    NÃO é o MASE clássico (Hyndman & Koehler): o MASE escala o erro pelo MAE
    do naive de um passo calculado no TREINO; aqui a escala é o MAE do naive
    sazonal na própria janela de teste. Por isso o nome é outro.

    `None` em `forecast` ou em `naive_forecast` exclui o ponto das duas
    contas. MAE do naive igual a zero (naive perfeito) ou nenhum ponto
    restante -> `None`.
    """
    rows = _kept_rows(actual, forecast, naive_forecast, mask=mask)
    if not rows:
        return None
    mae_method = sum(abs(a - f) for a, f, _ in rows) / len(rows)
    mae_naive = sum(abs(a - n) for a, _, n in rows) / len(rows)
    if mae_naive == 0:
        return None
    return mae_method / mae_naive


def wape_weighted(
    actual: Values, forecast: Values, unit_value: Values, mask: Mask | None = None
) -> float | None:
    """WAPE ponderado por valor: Σ|erro|xvalor / Σrealxvalor.

    `unit_value` é o valor unitário de cada observação (ex.: custo ou preço
    do item). Soma ponderada em vez de média de razões: item grande pesa mais
    que item pequeno. Denominador zero -> `None`.
    """
    rows = _kept_rows(actual, forecast, unit_value, mask=mask)
    denominator = sum(a * v for a, _, v in rows)
    if denominator == 0:
        return None
    return sum(abs(a - f) * v for a, f, v in rows) / denominator


def bias(actual: Values, forecast: Values, mask: Mask | None = None) -> float | None:
    """Viés: Σ(previsão - real) / Σreal. Positivo = superestima.

    Soma real zero -> `None`.
    """
    rows = _kept_rows(actual, forecast, mask=mask)
    denominator = sum(a for a, _ in rows)
    if denominator == 0:
        return None
    return sum(f - a for a, f in rows) / denominator


def quantile_coverage(actual: Values, forecast_q: Values, mask: Mask | None = None) -> float | None:
    """Fração das observações com real ≤ quantil previsto.

    Para um modelo calibrado no nível `q`, o resultado fica perto de `q`. É
    unilateral por quantil (o modelo não tem quantil abaixo da mediana, então
    não há intervalo). Quem chama passa uma série por quantil de
    `avaliacao.quantis_cobertura` e reporta o nível nominal ao lado.
    Nenhuma observação restante -> `None`.
    """
    rows = _kept_rows(actual, forecast_q, mask=mask)
    if not rows:
        return None
    return sum(1 for a, q in rows if a <= q) / len(rows)

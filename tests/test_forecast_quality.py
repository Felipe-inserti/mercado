"""Testes de `motor.metrics.forecast_quality` (Sprint 24, etapa 24.2).

Todos os exemplos usam 4 pontos com o cálculo à mão no comentário.

Dados base:
    actual   = [10, 20, 30, 40]
    forecast = [12, 18, 33, 36]    erros (f - a) = [+2, -2, +3, -4]
    naive    = [10, 10, 40, 20]    erros (n - a) = [ 0, -10, +10, -20]
"""

from __future__ import annotations

import polars as pl
import pytest

from motor.metrics.forecast_quality import bias, quantile_coverage, relative_mae, wape_weighted

ACTUAL = [10.0, 20.0, 30.0, 40.0]
FORECAST = [12.0, 18.0, 33.0, 36.0]
NAIVE = [10.0, 10.0, 40.0, 20.0]

# -- relative_mae -------------------------------------------------------------


def test_relative_mae_exemplo_de_4_pontos() -> None:
    # MAE método = (2 + 2 + 3 + 4) / 4 = 11 / 4 = 2,75
    # MAE naive  = (0 + 10 + 10 + 20) / 4 = 40 / 4 = 10
    # relativo   = 2,75 / 10 = 0,275
    assert relative_mae(ACTUAL, FORECAST, NAIVE) == pytest.approx(0.275)


def test_relative_mae_aceita_series_polars() -> None:
    result = relative_mae(pl.Series(ACTUAL), pl.Series(FORECAST), pl.Series(NAIVE))
    assert result == pytest.approx(0.275)


def test_relative_mae_denominador_zero_devolve_none() -> None:
    # naive perfeito: MAE naive = 0 -> sem razão definida
    assert relative_mae(ACTUAL, FORECAST, ACTUAL) is None


def test_relative_mae_mascara_exclui_o_ponto_certo() -> None:
    # máscara [T, T, F, T] tira o ponto 3 (|erro| 3 e 10):
    # MAE método = (2 + 2 + 4) / 3 = 8/3 ; MAE naive = (0 + 10 + 20) / 3 = 30/3
    # relativo = 8 / 30
    result = relative_mae(ACTUAL, FORECAST, NAIVE, mask=[True, True, False, True])
    assert result == pytest.approx(8 / 30)


def test_relative_mae_none_na_previsao_exclui_o_ponto_das_duas_contas() -> None:
    # forecast None no ponto 2: sobram pontos 1, 3, 4
    # método = (2 + 3 + 4) / 3 = 9/3 ; naive = (0 + 10 + 20) / 3 = 30/3
    # relativo = 9 / 30 = 0,3
    forecast = [12.0, None, 33.0, 36.0]
    assert relative_mae(ACTUAL, forecast, NAIVE) == pytest.approx(0.3)


def test_relative_mae_none_no_naive_exclui_o_ponto_tambem_do_metodo() -> None:
    # naive None no ponto 3: sobram pontos 1, 2, 4
    # método = (2 + 2 + 4) / 3 = 8/3 (o ponto 3 do método, erro 3, sai também)
    # naive  = (0 + 10 + 20) / 3 = 30/3 ; relativo = 8 / 30
    naive = [10.0, 10.0, None, 20.0]
    assert relative_mae(ACTUAL, FORECAST, naive) == pytest.approx(8 / 30)


def test_relative_mae_sem_nenhum_ponto_devolve_none() -> None:
    assert relative_mae(ACTUAL, FORECAST, NAIVE, mask=[False] * 4) is None


def test_tamanhos_diferentes_levantam_erro() -> None:
    with pytest.raises(ValueError, match="tamanhos diferentes"):
        relative_mae(ACTUAL, FORECAST[:3], NAIVE)


def test_mascara_de_tamanho_errado_levanta_erro() -> None:
    with pytest.raises(ValueError, match="tamanhos diferentes"):
        bias(ACTUAL, FORECAST, mask=[True, True])


# -- wape_weighted ------------------------------------------------------------


def test_wape_weighted_exemplo_de_4_pontos() -> None:
    # valor unitário = [1, 2, 1, 2]
    # Σ|erro|xvalor = 2x1 + 2x2 + 3x1 + 4x2 = 2 + 4 + 3 + 8 = 17
    # Σrealxvalor   = 10x1 + 20x2 + 30x1 + 40x2 = 10 + 40 + 30 + 80 = 160
    # WAPE = 17 / 160 = 0,10625
    assert wape_weighted(ACTUAL, FORECAST, [1.0, 2.0, 1.0, 2.0]) == pytest.approx(0.10625)


def test_wape_weighted_denominador_zero_devolve_none() -> None:
    assert wape_weighted([0.0] * 4, FORECAST, [1.0] * 4) is None
    assert wape_weighted(ACTUAL, FORECAST, [0.0] * 4) is None


def test_wape_weighted_mascara_exclui_o_ponto_certo() -> None:
    # sem o ponto 4 (valor 2): Σ|erro|xvalor = 2 + 4 + 3 = 9 ; Σrealxvalor = 10 + 40 + 30 = 80
    result = wape_weighted(ACTUAL, FORECAST, [1.0, 2.0, 1.0, 2.0], mask=[True, True, True, False])
    assert result == pytest.approx(9 / 80)


def test_wape_weighted_none_na_previsao_exclui_o_ponto() -> None:
    # sem o ponto 1 (valor 1): Σ|erro|xvalor = 4 + 3 + 8 = 15 ; Σrealxvalor = 40 + 30 + 80 = 150
    forecast = [None, 18.0, 33.0, 36.0]
    assert wape_weighted(ACTUAL, forecast, [1.0, 2.0, 1.0, 2.0]) == pytest.approx(0.1)


# -- bias ---------------------------------------------------------------------


def test_bias_exemplo_de_4_pontos() -> None:
    # Σ(f - a) = 2 - 2 + 3 - 4 = -1 ; Σreal = 100 ; viés = -0,01 (subestima 1%)
    assert bias(ACTUAL, FORECAST) == pytest.approx(-0.01)


def test_bias_positivo_quando_superestima() -> None:
    # previsão = real + 5 em cada ponto: Σ(f - a) = 20 ; Σreal = 100 ; viés = +0,2
    assert bias(ACTUAL, [15.0, 25.0, 35.0, 45.0]) == pytest.approx(0.2)


def test_bias_denominador_zero_devolve_none() -> None:
    assert bias([0.0] * 4, FORECAST) is None


def test_bias_mascara_exclui_o_ponto_certo() -> None:
    # sem o ponto 1: Σ(f - a) = -2 + 3 - 4 = -3 ; Σreal = 90 ; viés = -1/30
    assert bias(ACTUAL, FORECAST, mask=[False, True, True, True]) == pytest.approx(-3 / 90)


def test_bias_none_na_previsao_exclui_o_ponto() -> None:
    # sem o ponto 4: Σ(f - a) = 2 - 2 + 3 = 3 ; Σreal = 60 ; viés = 0,05
    forecast = [12.0, 18.0, 33.0, None]
    assert bias(ACTUAL, forecast) == pytest.approx(0.05)


# -- quantile_coverage --------------------------------------------------------


def test_quantile_coverage_exemplo_de_4_pontos() -> None:
    # quantil previsto = [12, 18, 30, 45]
    # real <= quantil: 10<=12 sim ; 20<=18 não ; 30<=30 sim (igualdade conta) ; 40<=45 sim
    # cobertura = 3 / 4 = 0,75
    assert quantile_coverage(ACTUAL, [12.0, 18.0, 30.0, 45.0]) == pytest.approx(0.75)


def test_quantile_coverage_sem_observacao_devolve_none() -> None:
    assert quantile_coverage(ACTUAL, FORECAST, mask=[False] * 4) is None


def test_quantile_coverage_mascara_exclui_o_ponto_certo() -> None:
    # sem o ponto 2 (o único que falha): 3 de 3 = 1,0
    result = quantile_coverage(ACTUAL, [12.0, 18.0, 30.0, 45.0], mask=[True, False, True, True])
    assert result == pytest.approx(1.0)


def test_quantile_coverage_none_na_previsao_exclui_o_ponto() -> None:
    # sem o ponto 2: pontos 1, 3, 4 todos cobertos -> 1,0
    assert quantile_coverage(ACTUAL, [12.0, None, 30.0, 45.0]) == pytest.approx(1.0)

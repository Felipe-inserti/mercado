"""Protocolo `Policy` e `DecisionContext`, no grão de um único par loja-item.

Ver `motor.forecast.base` para a mesma nota de escopo: isto é a versão
reduzida ao par, não o consolidador por fornecedor da seção 5 do CLAUDE.md
(emenda datada lá). `item_params`, `supplier_params` e `weekly_budget` só
existem quando houver consolidação por fornecedor -- não pertencem a este
grão.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

import polars as pl


@dataclass(frozen=True)
class DecisionContext:
    """Tudo que uma política vê para decidir quanto pedir, para um par loja-item.

    `in_transit` é obrigatório e é sempre calculado como posição total menos
    estoque em mãos -- nunca uma subtração ad-hoc feita por quem monta o
    contexto. Omitir pipeline é o bug clássico deste tipo de sistema
    (CLAUDE.md, seção 5): a política pede de novo o que já está a caminho, e
    o resultado infla silenciosamente.
    """

    as_of: date
    on_hand: float
    in_transit: float
    forecast: pl.DataFrame  # colunas: quantile, value -- saída de Forecaster.predict_quantiles


class Policy(Protocol):
    """Decide quanto pedir para um par loja-item."""

    def order(self, ctx: DecisionContext) -> float:
        """Unidades a pedir, antes das regras de guarda (sprint futura: ainda não existem)."""

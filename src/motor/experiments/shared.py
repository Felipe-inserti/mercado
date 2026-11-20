"""Compatibilidade das premissas compartilhadas dos experimentos.

As implementações vivem em `motor.simulator.pair`, sem dependência da
camada de experimentos. Os nomes antigos permanecem disponíveis.
"""

from motor.simulator import pair

build_simulator_for_pair = pair.build_simulator_for_pair
initial_stock_units = pair.initial_stock_units

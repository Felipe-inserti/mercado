"""Teste de fumaça: garante que o pacote instala e importa corretamente."""

import motor


def test_import_motor() -> None:
    """Confirma que o pacote `motor` pode ser importado a partir do layout src/."""
    assert motor is not None

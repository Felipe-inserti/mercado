"""Testes de `InventoryState` -- estado isolado, sem simulação, sem dado real.

Cada teste usa números pequenos e verificáveis à mão. Onde a ordem interna
dos lotes importa e não tem efeito colateral observável de fora (empate de
validade), o teste inspeciona `estado._lotes` diretamente -- é o único jeito
honesto de verificar essa invariante, porque duas unidades com a mesma
validade são, por design, fungíveis do ponto de vista de quem chama.
"""

from datetime import date, timedelta

import pytest

from motor.inventory import InventoryState

D0 = date(2026, 1, 1)


def _dias(n: int) -> date:
    return D0 + timedelta(days=n)


# -- receber -----------------------------------------------------------


def test_receber_incorpora_lote_ao_estoque_em_maos() -> None:
    estado = InventoryState(data_inicial=D0)
    estado.receber(10.0, validade=_dias(5))
    assert estado.em_maos() == 10.0
    assert estado.posicao() == 10.0


# -- consumir ------------------------------------------------------------


def test_consumir_atende_totalmente_quando_ha_estoque_suficiente() -> None:
    estado = InventoryState(data_inicial=D0)
    estado.receber(10.0, validade=_dias(5))
    atendido = estado.consumir(7.0)
    assert atendido == 7.0
    assert estado.em_maos() == 3.0


def test_consumir_parcial_de_lote_deixa_restante_disponivel() -> None:
    estado = InventoryState(data_inicial=D0)
    estado.receber(10.0, validade=_dias(5))
    estado.consumir(4.0)
    # 10 - 4 = 6 permanecem, disponíveis para o próximo consumo
    assert estado.em_maos() == 6.0
    atendido = estado.consumir(6.0)
    assert atendido == 6.0
    assert estado.em_maos() == 0.0


def test_consumir_maior_que_estoque_devolve_disponivel_sem_excecao() -> None:
    estado = InventoryState(data_inicial=D0)
    estado.receber(5.0, validade=_dias(5))
    atendido = estado.consumir(10.0)
    assert atendido == 5.0  # não 10 -- demanda não atendida desaparece
    assert estado.em_maos() == 0.0
    # uma segunda tentativa sobre estoque zerado também não gera saldo negativo
    atendido_2 = estado.consumir(3.0)
    assert atendido_2 == 0.0
    assert estado.em_maos() == 0.0


def test_expiracao_no_meio_da_fila_fefo_lote_antigo_vence_novo_continua() -> None:
    estado = InventoryState(data_inicial=D0)
    estado.receber(4.0, validade=_dias(2))  # vence primeiro
    estado.receber(6.0, validade=_dias(20))  # sobrevive
    estado.avancar_para(_dias(3))
    perdido = estado.expirar()
    assert perdido == 4.0
    assert estado.em_maos() == 6.0


def test_fefo_diverge_de_fifo_lote_recente_com_validade_curta_sai_primeiro() -> None:
    """Um lote de validade longa que CHEGOU primeiro não deve furar a fila:
    o de validade curta, mesmo chegando depois, sai antes -- é FEFO, não
    FIFO por ordem de chegada."""
    estado = InventoryState(data_inicial=D0)
    estado.receber(8.0, validade=_dias(30))  # chega primeiro, vence por último
    estado.receber(5.0, validade=_dias(3))  # chega depois, vence primeiro

    atendido = estado.consumir(5.0)
    assert atendido == 5.0
    # os 5 consumidos vieram inteiramente do lote de validade curta:
    # o de validade longa (8) permanece intacto
    assert estado.em_maos() == 8.0
    estado.avancar_para(_dias(4))
    perdido = estado.expirar()
    assert perdido == 0.0  # o lote de validade curta já foi todo consumido, nada vence


def test_desempate_por_ordem_de_insercao_entre_lotes_de_mesma_validade() -> None:
    venc = _dias(10)
    estado = InventoryState(data_inicial=D0)
    estado.receber(3.0, validade=venc)  # inserido primeiro
    estado.receber(5.0, validade=venc)  # inserido depois

    atendido = estado.consumir(3.0)
    assert atendido == 3.0
    # se a ordem de inserção fosse respeitada ao contrário, sobrariam DOIS
    # lotes (2.0 do segundo + 3.0 do primeiro, intacto); com o primeiro
    # inserido consumido primeiro, sobra um único lote de 5.0
    assert len(estado._lotes) == 1
    assert estado._lotes[0].quantidade == 5.0


# -- avancar_para / expirar ----------------------------------------------


def test_avancar_para_recebe_pedido_em_transito_na_data_de_chegada() -> None:
    estado = InventoryState(data_inicial=D0)
    estado.agendar_pedido(20.0, data_chegada=_dias(2), validade=_dias(10))
    assert estado.em_maos() == 0.0
    assert estado.posicao() == 20.0

    estado.avancar_para(_dias(2))
    assert estado.em_maos() == 20.0
    assert estado.posicao() == 20.0  # posição não salta: só migra de trânsito para mãos


def test_avancar_para_com_salto_de_multiplos_dias_recebe_pedido_intermediario() -> None:
    estado = InventoryState(data_inicial=D0)
    estado.agendar_pedido(7.0, data_chegada=_dias(3), validade=None)
    estado.avancar_para(_dias(10))  # pula direto, sem passar por dias(3)
    assert estado.em_maos() == 7.0
    assert estado.posicao() == 7.0


def test_avancar_para_com_data_anterior_ou_igual_a_corrente_levanta_value_error() -> None:
    estado = InventoryState(data_inicial=_dias(5))
    with pytest.raises(ValueError, match="regressão de data"):
        estado.avancar_para(_dias(5))
    with pytest.raises(ValueError, match="regressão de data"):
        estado.avancar_para(_dias(4))


def test_duas_chegadas_na_mesma_data_sao_ambas_recebidas() -> None:
    chegada = _dias(3)
    estado = InventoryState(data_inicial=D0)
    estado.agendar_pedido(4.0, data_chegada=chegada, validade=_dias(5))
    estado.agendar_pedido(6.0, data_chegada=chegada, validade=_dias(8))
    assert estado.posicao() == 10.0

    estado.avancar_para(chegada)
    assert estado.em_maos() == 10.0
    assert estado.posicao() == 10.0  # pipeline vazio: nada mais em trânsito


def test_nao_perecivel_nunca_expira_mesmo_apos_avanco_longo() -> None:
    estado = InventoryState(data_inicial=D0)
    estado.receber(5.0, validade=None)
    estado.avancar_para(_dias(3650))  # dez anos à frente
    perdido = estado.expirar()
    assert perdido == 0.0
    assert estado.em_maos() == 5.0


def test_avancar_para_seguido_de_expirar_sem_consumir_remove_lote_vencido() -> None:
    estado = InventoryState(data_inicial=D0)
    estado.receber(5.0, validade=_dias(2))
    estado.avancar_para(_dias(5))  # bem além da validade, sem consumir nada
    perdido = estado.expirar()
    assert perdido == 5.0
    assert estado.em_maos() == 0.0


def test_consumir_antes_de_expirar_salva_o_lote_que_venceria_naquele_dia() -> None:
    estado = InventoryState(data_inicial=D0)
    estado.receber(5.0, validade=_dias(1))
    estado.avancar_para(_dias(2))  # data_corrente (dias(2)) > validade (dias(1)): vencido

    atendido = estado.consumir(2.0)  # vendido antes de expirar: salvo da perda
    assert atendido == 2.0

    perdido = estado.expirar()
    assert perdido == 3.0  # só o restante, não os 5 originais
    assert estado.em_maos() == 0.0
    # 2 vendidos + 3 perdidos = 5 originais -- nada desapareceu sem explicação
    assert atendido + perdido == 5.0


def test_lote_com_validade_igual_a_data_corrente_e_consumivel_hoje() -> None:
    estado = InventoryState(data_inicial=_dias(5))
    estado.receber(5.0, validade=_dias(5))  # validade == data corrente

    perdido_hoje = estado.expirar()
    assert perdido_hoje == 0.0  # ainda vendável no próprio dia da validade

    atendido = estado.consumir(5.0)
    assert atendido == 5.0


def test_lote_com_validade_igual_a_data_corrente_some_apos_proximo_avanco() -> None:
    estado = InventoryState(data_inicial=_dias(5))
    estado.receber(5.0, validade=_dias(5))
    estado.avancar_para(_dias(6))  # avança além da validade, sem consumir
    perdido = estado.expirar()
    assert perdido == 5.0
    assert estado.em_maos() == 0.0


# -- sequência completa determinística ------------------------------------


def test_sequencia_completa_deterministica() -> None:
    """Bateria de operações com resultado calculado à mão.

    D0: recebe 10 (validade D0+5); agenda pedido de 20 (chega D0+2,
        validade D0+10).
        em_maos = 10, posição = 10 + 20 = 30.
    D0: consome 4 do lote perecível -> em_maos = 6, posição = 26.
    D0+2: avança -- recebe os 20 agendados.
        em_maos = 6 + 20 = 26, posição = 26 (pipeline vazio).
        expira: nada vencido (D0+5 e D0+10 ainda no futuro) -> perda 0.
    D0+2: consome 6 -- FEFO tira inteiro do lote de validade D0+5
        (é o mais próximo de vencer), o de D0+10 fica intocado.
        em_maos = 20.
    D0+6: avança -- nada a receber. expira: D0+10 ainda não venceu -> perda 0.
        em_maos = 20.
    D0+11: avança -- expira: D0+10 < D0+11 -> perde os 20 restantes.
        em_maos = 0.

    Balanço: recebido/pedido = 10 + 20 = 30.
             consumido = 4 + 6 = 10. perdido = 20. 10 + 20 = 30. Fecha.
    """
    estado = InventoryState(data_inicial=D0)
    estado.receber(10.0, validade=_dias(5))
    estado.agendar_pedido(20.0, data_chegada=_dias(2), validade=_dias(10))
    assert estado.em_maos() == 10.0
    assert estado.posicao() == 30.0

    atendido_d0 = estado.consumir(4.0)
    assert atendido_d0 == 4.0
    assert estado.em_maos() == 6.0
    assert estado.posicao() == 26.0

    estado.avancar_para(_dias(2))
    assert estado.em_maos() == 26.0
    assert estado.posicao() == 26.0
    assert estado.expirar() == 0.0

    atendido_d2 = estado.consumir(6.0)
    assert atendido_d2 == 6.0
    assert estado.em_maos() == 20.0

    estado.avancar_para(_dias(6))
    assert estado.expirar() == 0.0
    assert estado.em_maos() == 20.0

    estado.avancar_para(_dias(11))
    perdido_final = estado.expirar()
    assert perdido_final == 20.0
    assert estado.em_maos() == 0.0
    assert estado.posicao() == 0.0

    total_recebido_ou_pedido = 10.0 + 20.0
    total_consumido = atendido_d0 + atendido_d2
    total_perdido = perdido_final
    assert total_consumido + total_perdido == total_recebido_ou_pedido

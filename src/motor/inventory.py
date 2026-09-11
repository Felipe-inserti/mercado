"""Estado de estoque de um par loja-item: `InventoryState`.

Fonte única de verdade sobre a posição de estoque ao longo do tempo. Isolada
do resto do motor -- não sabe o que é família, o que é perecível, nem lê
premissas de `config/params.yaml`. Quem chama informa a validade de cada
lote no momento em que ele entra no sistema, seja por recebimento imediato
(`receber`) ou por pedido em trânsito (`agendar_pedido`). A tabela de
premissas por família (shelf life por categoria etc.) vive na camada acima
desta e entra na Sprint 6.

Uma instância representa um par loja-item, mas não recebe `item_id` nem
`store_id` -- isso é responsabilidade de quem a instancia.

Este módulo é o componente que quebra em silêncio: um erro aqui não levanta
exceção, apenas faz o resultado financeiro final ficar melhor do que
deveria. Todo o resto do projeto é medido em cima dele.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class Lote:
    """Um lote de estoque em mãos, com quantidade e validade.

    `validade=None` representa item não-perecível. Não usamos `date.max`
    como sentinel: seria aritmeticamente válido, mas semanticamente uma
    mentira (finge uma data real que não existe). `None` força todo código
    que checa expiração a tratar o caso explicitamente.
    """

    quantidade: float
    validade: date | None


@dataclass
class PedidoEmTransito:
    """Um pedido já feito ao fornecedor, ainda não recebido.

    Carrega a validade que o lote resultante terá quando chegar. Essa
    validade é capturada no momento do agendamento porque `avancar_para`
    recebe pedidos automaticamente, sem intervenção do chamador no instante
    exato da chegada -- não há de onde mais tirar essa informação.
    """

    quantidade: float
    data_chegada: date
    validade: date | None


def _chave_fefo(lote: Lote) -> tuple[bool, date]:
    """Chave de ordenação FEFO: vence primeiro, sai primeiro.

    Lotes não-perecíveis (`validade is None`) ordenam por último -- tratados
    como se vencessem "no infinito". O `sort` do Python é estável, então
    lotes com a mesma chave (mesma validade real, ou ambos não-perecíveis)
    preservam a ordem de inserção original, que é o desempate desejado.
    """
    return (lote.validade is None, lote.validade if lote.validade is not None else date.min)


class InventoryState:
    """Posição de estoque de um par loja-item, com pipeline e lotes com validade.

    Ver `posicao()` para o motivo pelo qual esta classe separa "em mãos" de
    "em trânsito" -- é a distinção central que impede o bug clássico deste
    tipo de sistema.
    """

    def __init__(self, data_inicial: date) -> None:
        self._data_corrente = data_inicial
        self._lotes: list[Lote] = []
        self._pipeline: list[PedidoEmTransito] = []

    # -- escrita -------------------------------------------------------

    def receber(self, quantidade: float, validade: date | None) -> None:
        """Incorpora um lote ao estoque em mãos na data corrente.

        `validade` é obrigatória mesmo para não-perecível (`None` passado
        explicitamente). Um default silencioso faria um lote perecível
        esquecido virar imortal -- o mesmo tipo de erro silencioso que
        infla o resultado sem levantar exceção.
        """
        self._lotes.append(Lote(quantidade=quantidade, validade=validade))

    def consumir(self, quantidade: float) -> float:
        """Retira `quantidade` do estoque em mãos em ordem FEFO.

        FEFO (vence primeiro, sai primeiro), não FIFO por data de chegada:
        um lote de validade curta que chegou depois de um de validade longa
        ainda sai primeiro. É a ordem que minimiza perda por vencimento, o
        objetivo de qualquer operação com perecíveis. Ver `_chave_fefo` para
        o desempate entre lotes de mesma validade.

        Consumo parcial de um lote deixa o restante disponível, com a mesma
        validade. Demanda que excede o estoque em mãos NÃO vira backorder: o
        excedente desaparece -- no varejo alimentar o cliente não espera.
        Nunca levanta exceção nem produz saldo negativo; devolve o que foi
        efetivamente atendido.
        """
        self._lotes.sort(key=_chave_fefo)
        restante = quantidade
        atendido = 0.0
        lotes_restantes: list[Lote] = []
        for lote in self._lotes:
            if restante <= 0:
                lotes_restantes.append(lote)
                continue
            abatido = min(lote.quantidade, restante)
            atendido += abatido
            restante -= abatido
            saldo = lote.quantidade - abatido
            if saldo > 0:
                lotes_restantes.append(Lote(quantidade=saldo, validade=lote.validade))
        self._lotes = lotes_restantes
        return atendido

    def avancar_para(self, nova_data: date) -> None:
        """Avança a data corrente e recebe pedidos em trânsito já chegados.

        Não expira nada -- isso é responsabilidade de `expirar()`, chamada
        separadamente pelo loop diário depois do atendimento da demanda. As
        duas operações são deliberadamente separadas: o loop diário da
        Sprint 6 segue a ordem recebimento -> demanda -> atendimento ->
        envelhecimento, com a demanda entre o recebimento e a expiração.
        Fundir as duas impediria o loop de expressar essa ordem -- o
        estoque que chega hoje precisa estar disponível para a demanda de
        hoje, e a expiração só deve ser verificada depois do atendimento,
        senão se perde por validade unidades que teriam sido vendidas
        naquele mesmo dia.

        Salto de mais de um dia funciona sem caso especial: todo pedido com
        `data_chegada <= nova_data` é recebido de uma vez.
        """
        if nova_data <= self._data_corrente:
            raise ValueError(
                f"nova_data ({nova_data}) deve ser posterior à data corrente "
                f"({self._data_corrente}) -- regressão de data é bug de chamador, "
                "não caso de uso válido."
            )
        self._data_corrente = nova_data
        chegados = [pedido for pedido in self._pipeline if pedido.data_chegada <= nova_data]
        self._pipeline = [pedido for pedido in self._pipeline if pedido.data_chegada > nova_data]
        for pedido in chegados:
            self._lotes.append(Lote(quantidade=pedido.quantidade, validade=pedido.validade))

    def expirar(self) -> float:
        """Remove os lotes vencidos na data corrente e devolve o total perdido.

        Usa `<` estrito: um lote com `validade == data_corrente` ainda é
        vendável hoje -- só expira na próxima chamada de `avancar_para` que
        ultrapassar essa data. Não-perecíveis (`validade is None`) nunca são
        removidos por esta operação.

        Deve ser chamada depois do atendimento da demanda do dia (ver
        `avancar_para`). Expirar antes descontaria unidades que ainda seriam
        vendidas hoje -- uma perda fantasma que penaliza o braço perecível
        injustamente.
        """
        vencidos = [lote for lote in self._lotes if self._esta_vencido(lote)]
        self._lotes = [lote for lote in self._lotes if not self._esta_vencido(lote)]
        return sum((lote.quantidade for lote in vencidos), 0.0)

    def _esta_vencido(self, lote: Lote) -> bool:
        return lote.validade is not None and lote.validade < self._data_corrente

    def agendar_pedido(self, quantidade: float, data_chegada: date, validade: date | None) -> None:
        """Registra um pedido em trânsito, com a validade que o lote terá ao chegar.

        `validade` é obrigatória pelo mesmo motivo que em `receber`: um
        default silencioso faria um pedido de item perecível esquecido virar
        um lote imortal quando `avancar_para` o recebe automaticamente, sem
        chance de o chamador informar a validade naquele momento.
        """
        self._pipeline.append(
            PedidoEmTransito(quantidade=quantidade, data_chegada=data_chegada, validade=validade)
        )

    # -- leitura ---------------------------------------------------------

    def posicao(self) -> float:
        """Estoque em mãos MAIS tudo que está em trânsito (já pedido, não recebido).

        Esta é a quantidade que uma política de reposição deve olhar para
        decidir quanto pedir -- nunca `em_maos()` sozinho. Ignorar o
        pipeline aqui é o bug clássico deste tipo de sistema: a política
        pede de novo, a cada revisão, o que já está a caminho. O estoque
        simulado infla, a ruptura desaparece, e o resultado fica ótimo por
        um motivo falso.

        Recebimento não move este número: a quantidade apenas migra de "em
        trânsito" para "em mãos", `em_maos() + em_transito` permanece igual.
        """
        return self.em_maos() + sum((pedido.quantidade for pedido in self._pipeline), 0.0)

    def em_maos(self) -> float:
        """Apenas o estoque físico disponível agora, sem o que está em trânsito."""
        return sum((lote.quantidade for lote in self._lotes), 0.0)

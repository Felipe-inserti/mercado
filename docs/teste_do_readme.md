# Teste do README com uma pessoa de verdade

Condição de "pronto" da Sprint 23: alguém que nunca viu o projeto lê o `README.md` e responde, em
dois minutos, o que é, para quem, o que foi medido e quais são as limitações. Autoavaliação não vale.

## Como aplicar (5 minutos)

1. Escolha um colega que **não conhece o projeto**. Vale alguém que não é de programação: o topo do README é
   escrito para investidor e cliente.
2. Abra só o `README.md` (no GitHub, para o diagrama e as imagens aparecerem). **Não explique nada.**
3. Dê **2 minutos** de leitura, cronometrados. Depois feche a janela e faça as 4 perguntas abaixo, de memória.
4. Anote onde a pessoa travou, o que não entendeu e quanto tempo levou. Isso importa mais que as respostas.

## As 4 perguntas

1. **O que é este projeto, em uma frase, e para quem é?**
2. **O que foi medido e qual é o resultado principal?**
3. **Já foi testado com um cliente real? Como o sistema recebe os dados de um cliente?**
4. **Cite duas limitações que você levaria em conta antes de confiar nos números.**

## Gabarito (o que o README responde)

| # | Resposta esperada | Onde está no README |
|---|---|---|
| 1 | Um motor que decide quanto pedir de cada item na compra semanal de supermercado pequeno ou médio, por fornecedor; para dono e comprador. | Topo e "O problema" |
| 2 | Em simulação sobre dado público: corrigir o fator do próprio ERP leva o serviço de ~60% para ~95%, mas exige bem mais capital (+284%); sobre isso, o motor dá um ganho menor (−2,8% de capital e +2,9% de margem por real no mesmo serviço). Uma única célula de prazos (7/14). | "O que foi medido" |
| 3 | **Não**: só com dado fictício. Recebe exportação do ERP em CSV e NF-e de entrada em XML. | "De onde vêm os dados" |
| 4 | Qualquer duas entre: só uma célula de prazos; só dado público sem estoque (ruptura inferida, não medida); valores em R$ são ilustrativos; nunca rodou com cliente real; guardas só na lista e não no simulador; braço de ML não comparado em iso-serviço. | "Limitações" |

## Critério de aprovação

- As 4 respostas saem corretas **em 2 minutos de leitura**, sem ajuda. Na pergunta 2, o erro mais perigoso é
  citar só o benefício e esquecer o custo em capital, ou citar um número em R$ como se fosse medido.
- Se a pessoa travar em algum ponto, **mude o README nesse ponto** e aplique de novo com outra pessoa.

## Registro

| Data | Quem (cargo, não nome) | Tempo | Acertos (de 4) | Onde travou |
|---|---|---|---|---|
| | | | | |

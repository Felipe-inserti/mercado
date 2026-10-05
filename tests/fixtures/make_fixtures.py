# ruff: noqa: E501  (tabelas de fixture alinhadas por coluna, mais legíveis largas)
"""Gera `tests/fixtures/cliente_exemplo/` -- exportação FICTÍCIA de um cliente (Sprint 22).

Nenhum dado aqui é real: CNPJs com dígito verificador inválido, produtos e
preços inventados. O script existe porque o pipeline da lista de compra
exige semanas de histórico (um CSV de vendas escrito linha a linha não
chega lá), então o volume "de fundo" sai de um gerador com seed fixa e os
PROBLEMAS PLANTADOS são listas explícitas abaixo -- é o que os testes
(`test_loaders_cliente.py`, `test_auditoria_cadastro.py`...) verificam por
igualdade. Os arquivos gerados também vão para o git (determinismo: rodar
duas vezes produz bytes idênticos).

    python tests/fixtures/make_fixtures.py

PROBLEMAS PLANTADOS (a chave de cada um é usada literalmente nos testes)
-----------------------------------------------------------------------
vendas.csv (tipo: V venda, D devolução, C cancelamento)
  - 2024-03-11, 1001: V 10 + D 3        -> sold 10, returned 3 (venda bruta, DC2)
  - 2024-03-12, 1002: V 2 + D 5         -> sold 2, returned 5 (devolução maior que a venda)
  - 2024-03-13, 1002: V 2 + V 3         -> sold 5 (duas linhas do PDV no dia)
  - 2024-03-14, 1001: C 5               -> cancelamento: fora das vendas
  - 2024-03-15, 1007: V 1,250 + V 0,500 -> kg com vírgula decimal, sold 1.75
  - código 9999 "DIVERSOS" (venda genérica) em 11 linhas (a 12ª cairia no dia fechado)
  - código 7777 sem cadastro (2 linhas)
  - 2024-03-31: loja fechada (nenhuma linha de nenhum código)
  - 1018 vende o período inteiro mas não tem fornecedor em lugar nenhum

cadastro.csv
  - 1003: preço (4,50) abaixo do custo (5,20)               -> margem negativa
  - 1008 e 1009: mesmo EAN, ambos UN                        -> união de códigos
  - 1011 (UN) e 1012 (KG): mesmo EAN, unidade diferente     -> NÃO une, só audita
  - 1013 aparece duas vezes (custos 14,00 e 15,50)          -> a última linha vence
  - 1002: custo de cadastro 8,00, última nota 9,80          -> custo divergente
  - 1014: saldo 40, última venda em 2024-01-20              -> parado com saldo
  - 1016: saldo -3                                          -> saldo negativo
  - 1011/1012: perecíveis sem validade_dias (1007 tem 5, 1004 tem 180)
  - 1015/1016 vêm do S4 (lead time 7 >= revisão 7), sem nenhum pedido em aberto
  - 1005: nota com uCom == uTrib e fardo 24 no cadastro     -> fardo do cadastro
  - 1006: nota com uCom == uTrib e sem fardo no cadastro    -> fardo do fornecedor

pedidos_em_aberto.csv: 1001 (60), 1002 (120), 1007 (25,5) do S1; 8888 não existe
saldos (cadastro.saldo_estoque): todo item tem saldo informado, a fotografia é do
  último dia de venda (2024-04-29); o S1 pede segunda/quinta, o S4 terça

nfe/ (NF-e 4.00 de entrada; nomes fora da ordem de data de propósito)
  - nota_1_recente.xml   (2024-04-08, S1): ICMS-ST e desconto no 1002; IPI no 1006
  - nota_2_atacarejo.xml (2024-04-15, S2): compra de emergência, valor MAIOR que o
    do S1 no item 1004 -- a regra ingênua "quem mais se comprou" escolheria o S2
  - nota_3_antiga.xml    (2024-02-05, S1): caixa de 12 no 1004; custo antigo do 1002
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path
from typing import Final

OUT_DIR: Final[Path] = Path(__file__).resolve().parent / "cliente_exemplo"

SEED: Final[int] = 20240101
START: Final[date] = date(2024, 1, 1)
END: Final[date] = date(2024, 4, 29)
CLOSED_DAY: Final[date] = date(2024, 3, 31)

STORE_CNPJ: Final[str] = "55566677000188"
S1: Final[str] = "12345678000101"  # DISTRIBUIDORA ALFA -- regular, principal
S2: Final[str] = "98765432000102"  # ATACADAO BETA ATACAREJO -- emergência (padrão de nome)
S3: Final[str] = "11122233000103"  # ATACADO DO ZE -- regular EXPLÍCITO apesar do nome
S4: Final[str] = "33344455000104"  # DISTRIBUIDORA GAMA -- lead time 7 >= revisão 7, sem pedidos em aberto

# codigo, ean, descricao, categoria, unidade, fornecedor, custo, preco, fardo, saldo, perecivel, validade_dias
CADASTRO: Final[tuple[tuple[str, ...], ...]] = (
    ("1001", "7891000000011", "ARROZ TIPO 1 5KG", "GROCERY", "UN", S1, "17,00", "24,90", "6", "30", "N", ""),
    ("1002", "7891000000012", "FEIJAO CARIOCA 1KG", "GROCERY", "UN", S1, "8,00", "11,90", "12", "50", "N", ""),
    ("1003", "7891000000013", "REFRIGERANTE COLA 2L", "BEVERAGES", "UN", S1, "5,20", "4,50", "6", "80", "N", ""),
    ("1004", "7891000000014", "LEITE UHT INTEGRAL 1L", "DAIRY", "UN", S1, "4,00", "5,49", "", "100", "N", "180"),
    ("1005", "7891000000015", "DETERGENTE LIQUIDO 500ML", "CLEANING", "UN", S1, "2,10", "2,99", "24", "40", "N", ""),
    ("1006", "7891000000016", "ESPONJA MULTIUSO", "CLEANING", "UN", S1, "1,20", "2,50", "", "20", "N", ""),
    ("1007", "7891000000017", "CARNE MOIDA KG", "MEATS", "KG", S1, "32,00", "39,90", "", "12,5", "S", "5"),
    ("1008", "7891000000081", "SABAO EM PO 1KG", "CLEANING", "UN", S1, "9,00", "14,90", "", "25", "N", ""),
    ("1009", "7891000000081", "SABAO PO 1KG (CADASTRO DUPLICADO)", "CLEANING", "UN", S1, "9,00", "14,90", "", "", "N", ""),
    ("1011", "7891000000111", "QUEIJO FATIADO PECA", "DAIRY", "UN", S1, "22,00", "31,90", "", "3", "S", ""),
    ("1012", "7891000000111", "QUEIJO FATIADO KG", "DAIRY", "KG", S1, "22,00", "31,90", "", "2", "S", ""),
    ("1013", "7891000000131", "CAFE 500G", "GROCERY", "UN", S3, "14,00", "21,90", "", "", "N", ""),
    ("1013", "7891000000131", "CAFE TORRADO 500G", "GROCERY", "UN", S3, "15,50", "21,90", "", "60", "N", ""),
    ("1014", "7891000000141", "CAFE SOLUVEL 200G", "GROCERY", "UN", S1, "12,00", "18,90", "", "40", "N", ""),
    ("1015", "7891000000151", "FARINHA DE TRIGO 1KG", "GROCERY", "UN", S4, "3,50", "5,49", "", "5", "N", ""),
    ("1016", "7891000000161", "FUBA 500G", "GROCERY", "UN", S4, "2,00", "3,29", "", "-3", "N", ""),
    ("1017", "7891000000171", "ACUCAR CRISTAL 1KG", "GROCERY", "UN", S1, "3,80", "5,29", "", "0", "N", ""),
    ("1018", "7891000000181", "ITEM SEM FORNECEDOR", "GROCERY", "UN", "", "1,00", "2,00", "", "", "N", ""),
)
CADASTRO_HEADER: Final[str] = (
    "codigo;ean;descricao;categoria;unidade_venda;fornecedor;custo_cadastro;"
    "preco_venda;fardo;saldo_estoque;perecivel;validade_dias"
)

# fornecedor_id;nome;tipo;lead_time_dias;dias_pedido;revisao_dias;pedido_minimo_rs;
# pedido_minimo_un;fardo_padrao  -- `tipo` vazio no S2: a classificação vem do nome
FORNECEDORES: Final[tuple[str, ...]] = (
    "fornecedor_id;nome;tipo;lead_time_dias;dias_pedido;revisao_dias;"
    "pedido_minimo_rs;pedido_minimo_un;fardo_padrao",
    f"{S1};DISTRIBUIDORA ALFA LTDA;regular;3;1|4;4;500,00;0;10",
    f"{S2};ATACADAO BETA ATACAREJO;;1;1|2|3|4|5|6;2;0;0;",
    f"{S3};ATACADO DO ZE COMERCIO;regular;5;3;7;0;0;",
    f"{S4};DISTRIBUIDORA GAMA LTDA;regular;7;2;7;0;0;",
)

# codigo;fornecedor;quantidade;data_prevista -- pedidos feitos na segunda 29/04 ao S1 (lead time 3)
PEDIDOS_EM_ABERTO: Final[tuple[str, ...]] = (
    "codigo;fornecedor;quantidade;data_prevista",
    f"1001;{S1};60;02/05/2024",
    f"1002;{S1};120;02/05/2024",
    f"1007;{S1};25,5;02/05/2024",
    f"8888;{S1};10;02/05/2024",  # código que não existe no cadastro: descartado e contado
)

# (codigo -> (preço, mínimo, máximo unidades/dia, prob. de venda no dia, última data ou None))
BULK: Final[dict[str, tuple[str, int, int, float, date | None]]] = {
    "1001": ("24,90", 8, 22, 1.0, None),
    "1002": ("11,90", 10, 30, 1.0, None),
    "1003": ("4,50", 12, 36, 1.0, None),
    "1004": ("5,49", 15, 40, 1.0, None),
    "1005": ("2,99", 6, 18, 1.0, None),
    "1006": ("2,50", 1, 6, 0.6, None),
    "1007": ("39,90", 2, 9, 1.0, None),
    "1008": ("14,90", 3, 12, 1.0, None),
    "1009": ("14,90", 1, 5, 0.8, date(2024, 4, 20)),
    "1011": ("31,90", 1, 4, 0.5, None),
    "1012": ("31,90", 1, 3, 0.5, None),
    "1013": ("21,90", 4, 14, 1.0, None),
    "1014": ("18,90", 2, 6, 1.0, date(2024, 1, 20)),
    "1015": ("5,49", 5, 16, 1.0, None),
    "1016": ("3,29", 3, 10, 1.0, None),
    "1017": ("5,29", 2, 7, 1.0, date(2024, 2, 1)),
    "1018": ("2,00", 2, 8, 1.0, None),
}

# (data, codigo, quantidade, preco, tipo)
PLANTED_SALES: Final[tuple[tuple[date, str, str, str, str], ...]] = (
    (date(2024, 3, 11), "1001", "10", "24,90", "V"),
    (date(2024, 3, 11), "1001", "3", "24,90", "D"),
    (date(2024, 3, 12), "1002", "2", "11,90", "V"),
    (date(2024, 3, 12), "1002", "5", "11,90", "D"),
    (date(2024, 3, 13), "1002", "2", "11,90", "V"),
    (date(2024, 3, 13), "1002", "3", "11,90", "V"),
    (date(2024, 3, 14), "1001", "5", "24,90", "C"),
    (date(2024, 3, 15), "1007", "1,250", "39,90", "V"),
    (date(2024, 3, 15), "1007", "0,500", "39,90", "V"),
    (date(2024, 4, 22), "7777", "2", "9,90", "V"),
    (date(2024, 4, 23), "7777", "1", "9,90", "V"),
)
GENERIC_CODE: Final[str] = "9999"
GENERIC_EVERY_N_DAYS: Final[int] = 10  # 11 linhas: offsets 0..110, menos o 90 (dia fechado)


def _brl(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def _ddmmyyyy(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def sales_rows() -> list[tuple[date, str, str, str, str]]:
    rng = random.Random(SEED)
    reserved = {(d, code) for d, code, *_ in PLANTED_SALES}
    rows: list[tuple[date, str, str, str, str]] = []
    n_days = (END - START).days + 1
    for offset in range(n_days):
        day = START + timedelta(days=offset)
        if day == CLOSED_DAY:
            continue
        for code, (price, lo, hi, p_sale, last) in BULK.items():
            if (day, code) in reserved or (last is not None and day > last):
                continue
            forced = last is not None and day == last
            if forced or rng.random() < p_sale:
                rows.append((day, code, str(rng.randint(lo, hi)).replace(".", ","), price, "V"))
        if offset % GENERIC_EVERY_N_DAYS == 0 and day != CLOSED_DAY:
            rows.append((day, GENERIC_CODE, "1", _brl(15.0), "V"))
    rows.extend(PLANTED_SALES)
    rows.sort(key=lambda r: (r[0], r[1], r[4], r[2]))
    return rows


# --------------------------------------------------------------------------
# NF-e 4.00 -- só os campos que o loader lê, mais o esqueleto oficial
# --------------------------------------------------------------------------

_NS: Final[str] = "http://www.portalfiscal.inf.br/nfe"


def _item_xml(n: int, item: dict[str, str]) -> str:
    desc = f"        <vDesc>{item['vdesc']}</vDesc>\n" if item.get("vdesc") else ""
    ipi = (
        f"      <IPI><cEnq>999</cEnq><IPITrib><CST>00</CST><vIPI>{item['vipi']}</vIPI></IPITrib></IPI>\n"
        if item.get("vipi")
        else ""
    )
    st = (
        "<ICMS10><orig>0</orig><CST>10</CST><modBCST>4</modBCST>"
        f"<vBCST>1000.00</vBCST><pICMSST>18.00</pICMSST><vICMSST>{item['vicmsst']}</vICMSST></ICMS10>"
        if item.get("vicmsst")
        else "<ICMSSN102><orig>0</orig><CSOSN>102</CSOSN></ICMSSN102>"
    )
    return (
        f'    <det nItem="{n}">\n'
        "      <prod>\n"
        f"        <cProd>FORN-{item['ean'][-4:]}</cProd>\n"
        f"        <cEAN>{item['ean']}</cEAN>\n"
        f"        <xProd>{item['xprod']}</xProd>\n"
        "        <NCM>10063021</NCM>\n"
        "        <CFOP>5102</CFOP>\n"
        f"        <uCom>{item['ucom']}</uCom>\n"
        f"        <qCom>{item['qcom']}</qCom>\n"
        f"        <vUnCom>{item['vuncom']}</vUnCom>\n"
        f"        <vProd>{item['vprod']}</vProd>\n"
        f"        <cEANTrib>{item['ean']}</cEANTrib>\n"
        f"        <uTrib>{item['utrib']}</uTrib>\n"
        f"        <qTrib>{item['qtrib']}</qTrib>\n"
        f"        <vUnTrib>{item['vuntrib']}</vUnTrib>\n"
        f"{desc}"
        "        <indTot>1</indTot>\n"
        "      </prod>\n"
        f"      <imposto>\n        <ICMS>{st}</ICMS>\n{ipi}      </imposto>\n"
        "    </det>\n"
    )


def _nfe_xml(
    *, key: str, number: str, emitted: str, issuer: str, issuer_name: str, items: list[dict[str, str]]
) -> str:
    body = "".join(_item_xml(i, it) for i, it in enumerate(items, start=1))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<nfeProc xmlns="{_NS}" versao="4.00">\n'
        '  <NFe>\n'
        f'    <infNFe Id="NFe{key}" versao="4.00">\n'
        "    <ide>\n"
        "      <cUF>35</cUF><natOp>VENDA DE MERCADORIA</natOp><mod>55</mod><serie>1</serie>\n"
        f"      <nNF>{number}</nNF><dhEmi>{emitted}</dhEmi><tpNF>1</tpNF><finNFe>1</finNFe>\n"
        "    </ide>\n"
        f"    <emit><CNPJ>{issuer}</CNPJ><xNome>{issuer_name}</xNome></emit>\n"
        f"    <dest><CNPJ>{STORE_CNPJ}</CNPJ><xNome>MERCADO EXEMPLO LTDA</xNome></dest>\n"
        f"{body}"
        "    </infNFe>\n"
        "  </NFe>\n"
        "  <protNFe versao=\"4.00\"><infProt><cStat>100</cStat></infProt></protNFe>\n"
        "</nfeProc>\n"
    )


def _it(  # noqa: PLR0917
    ean: str, xprod: str, ucom: str, qcom: str, utrib: str, qtrib: str, vprod: str, **extra: str
) -> dict[str, str]:
    vuncom = f"{float(vprod) / float(qcom):.2f}"
    vuntrib = f"{float(vprod) / float(qtrib):.2f}"
    return {
        "ean": ean, "xprod": xprod, "ucom": ucom, "qcom": qcom, "vuncom": vuncom,
        "utrib": utrib, "qtrib": qtrib, "vuntrib": vuntrib, "vprod": vprod, **extra,
    }  # fmt: skip


def nfe_files() -> dict[str, str]:
    nota_a = _nfe_xml(
        key="35240212345678000101550010000010011000000013",
        number="1001",
        emitted="2024-02-05T09:15:00-03:00",
        issuer=S1,
        issuer_name="DISTRIBUIDORA ALFA LTDA",
        items=[
            _it("7891000000011", "ARROZ TIPO 1 5KG", "CX", "10", "UN", "60", "1080.00"),
            _it("7891000000012", "FEIJAO CARIOCA 1KG", "CX", "10", "UN", "120", "960.00"),
            _it("7891000000014", "LEITE UHT INTEGRAL 1L", "CX", "20", "UN", "240", "960.00"),
        ],
    )
    nota_b = _nfe_xml(
        key="35240412345678000101550010000010421000000028",
        number="1042",
        emitted="2024-04-08T10:40:00-03:00",
        issuer=S1,
        issuer_name="DISTRIBUIDORA ALFA LTDA",
        items=[
            _it("7891000000011", "ARROZ TIPO 1 5KG", "CX", "5", "UN", "30", "540.00"),
            # (1200,00 - 60,00 + 0 + 36,00) / 120 = 9,80 por unidade
            _it("7891000000012", "FEIJAO CARIOCA 1KG", "CX", "10", "UN", "120", "1200.00",
                vdesc="60.00", vicmsst="36.00"),
            _it("7891000000013", "REFRIGERANTE COLA 2L", "CX", "6", "UN", "36", "187.20"),
            # uCom == uTrib: a razão qTrib/qCom NÃO informa o fardo
            _it("7891000000015", "DETERGENTE LIQUIDO 500ML", "UN", "240", "UN", "240", "504.00"),
            # (120,00 + 5,00 de IPI) / 100 = 1,25 por unidade
            _it("7891000000016", "ESPONJA MULTIUSO", "UN", "100", "UN", "100", "120.00", vipi="5.00"),
        ],
    )  # fmt: skip
    nota_c = _nfe_xml(
        key="35240498765432000102550010000882311000000049",
        number="88231",
        emitted="2024-04-15T16:05:00-03:00",
        issuer=S2,
        issuer_name="ATACADAO BETA ATACAREJO",
        items=[_it("7891000000014", "LEITE UHT INTEGRAL 1L", "UN", "400", "UN", "400", "1800.00")],
    )
    return {
        "nota_1_recente.xml": nota_b,
        "nota_2_atacarejo.xml": nota_c,
        "nota_3_antiga.xml": nota_a,
    }


README: Final[str] = """# cliente_exemplo -- dados FICTÍCIOS

Exportação inventada de um cliente, para testar `motor.io.loaders_cliente`
(Sprint 22). Nenhum CNPJ, produto ou preço é real. Gerada por
`tests/fixtures/make_fixtures.py` -- não edite à mão; a lista dos problemas
plantados está na docstring do script.

Layout: CSV com `;` como separador, vírgula decimal e datas `dd/mm/aaaa`;
NF-e no layout 4.00 (estrutura conferida por teste, NÃO validada contra o
XSD oficial).

Dado de cliente real NUNCA entra neste diretório nem no git: fica em
`data/cliente/` (ignorado).
"""


def main() -> None:
    (OUT_DIR / "nfe").mkdir(parents=True, exist_ok=True)

    lines = ["data;codigo;quantidade;preco_unit;tipo"]
    lines += [f"{_ddmmyyyy(d)};{c};{q};{p};{t}" for d, c, q, p, t in sales_rows()]
    (OUT_DIR / "vendas.csv").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    cad = [CADASTRO_HEADER] + [";".join(row) for row in CADASTRO]
    (OUT_DIR / "cadastro.csv").write_text("\n".join(cad) + "\n", encoding="utf-8", newline="\n")
    (OUT_DIR / "pedidos_em_aberto.csv").write_text(
        "\n".join(PEDIDOS_EM_ABERTO) + "\n", encoding="utf-8", newline="\n"
    )
    (OUT_DIR / "fornecedores.csv").write_text(
        "\n".join(FORNECEDORES) + "\n", encoding="utf-8", newline="\n"
    )
    for name, xml in nfe_files().items():
        (OUT_DIR / "nfe" / name).write_text(xml, encoding="utf-8", newline="\n")
    (OUT_DIR / "README.md").write_text(README, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()

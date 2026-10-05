"""Testes de `motor.io.nfe_xml` (Sprint 22): parser puro de NF-e 4.00.

Só estrutura e valores lidos -- nenhuma regra de negócio (fornecedor
principal, custo, fardo) mora aqui. As notas são as fixtures FICTÍCIAS de
`tests/fixtures/cliente_exemplo/nfe/` (estrutura do layout 4.00, não
validadas contra o XSD oficial).
"""

from __future__ import annotations

from datetime import date

import pytest
from motor.io.nfe_xml import NfeParseError, parse_nfe

from tests.cliente_helpers import FIXTURE_DIR, S1, S2, STORE_CNPJ

NFE_DIR = FIXTURE_DIR / "nfe"


def test_cabecalho_da_nota_recente() -> None:
    doc = parse_nfe(NFE_DIR / "nota_1_recente.xml")
    assert doc.key == "35240412345678000101550010000010421000000028"
    assert doc.issued_on == date(2024, 4, 8)
    assert doc.issuer_cnpj == S1
    assert doc.issuer_name == "DISTRIBUIDORA ALFA LTDA"
    assert doc.issuer_cnae is None  # tag opcional, ausente na fixture
    assert doc.recipient_cnpj == STORE_CNPJ
    assert doc.purpose == 1  # finNFe: normal
    assert len(doc.items) == 5


def test_item_com_desconto_e_icms_st() -> None:
    doc = parse_nfe(NFE_DIR / "nota_1_recente.xml")
    feijao = next(i for i in doc.items if i.ean == "7891000000012")
    assert (feijao.ucom, feijao.qcom, feijao.utrib, feijao.qtrib) == ("CX", 10.0, "UN", 120.0)
    assert feijao.vprod == pytest.approx(1200.00)
    assert feijao.vdesc == pytest.approx(60.00)
    assert feijao.vicmsst == pytest.approx(36.00)
    assert feijao.vipi == pytest.approx(0.0)
    # (vProd - vDesc + vIPI + vICMSST) / qTrib  -- frete fora (limitação declarada)
    assert feijao.unit_cost == pytest.approx((1200.00 - 60.00 + 0.0 + 36.00) / 120.0)
    assert feijao.unit_cost == pytest.approx(9.80)


def test_item_com_ipi() -> None:
    doc = parse_nfe(NFE_DIR / "nota_1_recente.xml")
    esponja = next(i for i in doc.items if i.ean == "7891000000016")
    assert esponja.vipi == pytest.approx(5.00)
    assert esponja.unit_cost == pytest.approx(1.25)


def test_razao_do_fardo_so_informa_quando_as_unidades_diferem() -> None:
    doc = parse_nfe(NFE_DIR / "nota_1_recente.xml")
    by_ean = {i.ean: i for i in doc.items}
    assert by_ean["7891000000011"].pack_ratio == pytest.approx(6.0)  # CX 5 -> UN 30
    assert by_ean["7891000000012"].pack_ratio == pytest.approx(12.0)  # CX 10 -> UN 120
    # uCom == uTrib: qTrib/qCom = 1 NÃO informa o fardo -- None, nunca 1,0
    assert by_ean["7891000000015"].pack_ratio is None
    assert by_ean["7891000000016"].pack_ratio is None


def test_nota_do_atacarejo() -> None:
    doc = parse_nfe(NFE_DIR / "nota_2_atacarejo.xml")
    assert doc.issuer_cnpj == S2
    assert doc.issued_on == date(2024, 4, 15)
    (leite,) = doc.items
    assert leite.vprod == pytest.approx(1800.00)
    assert leite.pack_ratio is None


def test_aceita_bytes_alem_de_caminho() -> None:
    path = NFE_DIR / "nota_3_antiga.xml"
    assert parse_nfe(path.read_bytes()).key == parse_nfe(path).key


def test_xml_malformado_levanta_erro_proprio() -> None:
    with pytest.raises(NfeParseError, match="malformado"):
        parse_nfe(b"<nfeProc><NFe></nfeProc>")


def test_entidade_externa_nao_e_resolvida() -> None:
    """XML de terceiro é entrada não confiável: DOCTYPE com ENTITY (XXE,
    billion laughs) é recusado, nunca expandido."""
    hostile = (
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
        b'<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe>&e;</NFe></nfeProc>'
    )
    with pytest.raises(NfeParseError, match=r"entidade|DOCTYPE"):
        parse_nfe(hostile)


def test_sem_infnfe_levanta_erro_proprio() -> None:
    with pytest.raises(NfeParseError, match="infNFe"):
        parse_nfe(b'<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe/></nfeProc>')

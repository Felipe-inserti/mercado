"""Parser puro de NF-e 4.00 (Sprint 22): XML de nota fiscal de entrada -> dataclasses.

Só estrutura e valores lidos -- nenhuma regra de negócio mora aqui
(fornecedor principal, custo, fardo, compra de emergência são decisões de
`motor.io.loaders_cliente`). Separar os dois deixa o parser testável sem
dado de cliente e deixa o loader trocar de fonte (a NFC-e de venda é o
próximo passo, fora da Sprint 22) reaproveitando este item.

XML de terceiro é entrada NÃO CONFIÁVEL: usa `defusedxml`, e DOCTYPE/ENTITY
(XXE, "billion laughs") é recusado, nunca expandido.

O que se lê, e por quê:

- `ide/dhEmi` -- data de emissão. A NF-e NÃO traz a data de chegada na loja
  nem a do pedido, então o lead time NÃO é observável só pela nota; ele vem
  da entrevista (arquivo de fornecedores). Limitação declarada.
- `det/prod`: `cEAN` (casa a nota com o cadastro -- o `cProd` é o código do
  FORNECEDOR, não o da loja), `uCom/qCom` (unidade comercial: a caixa),
  `uTrib/qTrib` (unidade tributável: a unidade de venda), `vProd`, `vDesc`.
- `det/imposto`: `vIPI` e `vICMSST` (qualquer variante `ICMSxx`) -- entram
  no custo real (`NfeItem.unit_cost`). Frete (`vFrete`) fica FORA: rateio de
  frete por item é decisão que o dado não resolve -- limitação declarada.

Layout conferido por teste estrutural contra as fixtures FICTÍCIAS, NÃO
validado contra o XSD oficial.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final
from xml.etree.ElementTree import Element, ParseError

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring

NFE_NAMESPACE: Final[str] = "http://www.portalfiscal.inf.br/nfe"
_NS: Final[dict[str, str]] = {"n": NFE_NAMESPACE}


class NfeParseError(ValueError):
    """XML ilegível, recusado por segurança, ou sem campo obrigatório da NF-e."""


@dataclass(frozen=True)
class NfeItem:
    """Uma linha `det/prod` da nota."""

    ean: str
    description: str
    ucom: str
    qcom: float
    vuncom: float
    utrib: str
    qtrib: float
    vprod: float
    vdesc: float
    vipi: float
    vicmsst: float

    @property
    def unit_cost(self) -> float:
        """Custo unitário na unidade tributável (a de venda):
        `(vProd - vDesc + vIPI + vICMSST) / qTrib`. Frete fica fora."""
        return (self.vprod - self.vdesc + self.vipi + self.vicmsst) / self.qtrib

    @property
    def pack_ratio(self) -> float | None:
        """Unidades de venda por unidade comercial (`qTrib / qCom`), SÓ quando
        as duas unidades diferem. Com `uCom == uTrib` a razão é 1 por
        construção e NÃO informa o fardo: devolve `None`, nunca 1,0."""
        if self.ucom.strip().upper() == self.utrib.strip().upper() or self.qcom <= 0:
            return None
        return self.qtrib / self.qcom


@dataclass(frozen=True)
class NfeDocument:
    key: str
    issued_on: date
    issuer_cnpj: str
    issuer_name: str
    issuer_cnae: str | None
    recipient_cnpj: str
    purpose: int
    """`finNFe`: 1 normal, 2 complementar, 3 ajuste, 4 devolução."""
    items: tuple[NfeItem, ...]


def _text(parent: Element, path: str, *, required: bool, label: str) -> str | None:
    found = parent.find(path, _NS)
    text = found.text.strip() if found is not None and found.text else None
    if required and not text:
        raise NfeParseError(f"NF-e sem o campo obrigatório {label}")
    return text


def _number(parent: Element, path: str, *, label: str, required: bool = True) -> float:
    text = _text(parent, path, required=required, label=label)
    if text is None:
        return 0.0
    try:
        return float(text)
    except ValueError as exc:
        raise NfeParseError(f"NF-e com {label} não numérico: {text!r}") from exc


def _is_digits(value: str) -> bool:
    return value.isdigit()


def _parse_item(det: Element) -> NfeItem:
    prod = det.find("n:prod", _NS)
    if prod is None:
        raise NfeParseError("NF-e com det sem prod")
    ean = _text(prod, "n:cEAN", required=True, label="cEAN") or ""
    ean_trib = _text(prod, "n:cEANTrib", required=False, label="cEANTrib") or ""
    if not _is_digits(ean) and _is_digits(ean_trib):
        ean = ean_trib  # cEAN "SEM GTIN" mas a unidade tributável tem código de barras
    # vICMSST: o elemento existe sob qualquer variante ICMSxx (ICMS10, ICMS30, ICMS70...)
    icms_st = det.find("n:imposto/n:ICMS//n:vICMSST", _NS)
    return NfeItem(
        ean=ean,
        description=_text(prod, "n:xProd", required=False, label="xProd") or "",
        ucom=_text(prod, "n:uCom", required=True, label="uCom") or "",
        qcom=_number(prod, "n:qCom", label="qCom"),
        vuncom=_number(prod, "n:vUnCom", label="vUnCom"),
        utrib=_text(prod, "n:uTrib", required=True, label="uTrib") or "",
        qtrib=_number(prod, "n:qTrib", label="qTrib"),
        vprod=_number(prod, "n:vProd", label="vProd"),
        vdesc=_number(prod, "n:vDesc", label="vDesc", required=False),
        vipi=_number(det, "n:imposto/n:IPI/n:IPITrib/n:vIPI", label="vIPI", required=False),
        vicmsst=float(icms_st.text) if icms_st is not None and icms_st.text else 0.0,
    )


def parse_nfe(source: Path | bytes) -> NfeDocument:
    """Lê uma NF-e 4.00 (arquivo ou bytes). Levanta `NfeParseError` se o XML
    for malformado, tiver DOCTYPE/entidade, ou não tiver `infNFe`."""
    data = source if isinstance(source, bytes) else source.read_bytes()
    try:
        root = fromstring(data, forbid_dtd=True)
    except DefusedXmlException as exc:
        raise NfeParseError(f"XML recusado (DOCTYPE/entidade não permitido): {exc}") from exc
    except ParseError as exc:
        raise NfeParseError(f"XML malformado: {exc}") from exc

    inf = root if root.tag == f"{{{NFE_NAMESPACE}}}infNFe" else root.find(".//n:infNFe", _NS)
    if inf is None:
        raise NfeParseError("NF-e sem o elemento infNFe")

    emitted = _text(inf, "n:ide/n:dhEmi", required=False, label="dhEmi") or _text(
        inf, "n:ide/n:dEmi", required=True, label="dhEmi/dEmi"
    )
    try:
        issued_on = date.fromisoformat((emitted or "")[:10])
    except ValueError as exc:
        raise NfeParseError(f"NF-e com data de emissão inválida: {emitted!r}") from exc

    purpose_text = _text(inf, "n:ide/n:finNFe", required=False, label="finNFe") or "1"
    return NfeDocument(
        key=(inf.get("Id") or "").removeprefix("NFe"),
        issued_on=issued_on,
        issuer_cnpj=_text(inf, "n:emit/n:CNPJ", required=True, label="emit/CNPJ") or "",
        issuer_name=_text(inf, "n:emit/n:xNome", required=True, label="emit/xNome") or "",
        issuer_cnae=_text(inf, "n:emit/n:CNAE", required=False, label="emit/CNAE"),
        recipient_cnpj=_text(inf, "n:dest/n:CNPJ", required=False, label="dest/CNPJ") or "",
        purpose=int(purpose_text),
        items=tuple(_parse_item(det) for det in inf.findall("n:det", _NS)),
    )

"""Leitura pequena de células XLSX para asserts de integração, sem biblioteca extra."""

from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

CellValue = str | float | bool | None
WorkbookCells = dict[str, dict[str, CellValue]]


def read_workbook_cells(path: Path) -> WorkbookCells:
    """Devolve abas na ordem original, com referências A1 e valores tipados."""
    main = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rel = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
    doc_rel = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    with ZipFile(path) as workbook:
        shared = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
        strings = ["".join(node.itertext()) for node in shared.findall("m:si", main)]
        relationships = ElementTree.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
        targets = {
            node.attrib["Id"]: node.attrib["Target"]
            for node in relationships.findall("r:Relationship", rel)
        }
        contents = ElementTree.fromstring(workbook.read("xl/workbook.xml"))
        result: WorkbookCells = {}
        for sheet in contents.findall("m:sheets/m:sheet", main):
            target = targets[sheet.attrib[doc_rel]]
            member = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
            xml = ElementTree.fromstring(workbook.read(member))
            cells: dict[str, CellValue] = {}
            for cell in xml.findall(".//m:sheetData/m:row/m:c", main):
                value = cell.findtext("m:v", namespaces=main)
                kind = cell.attrib.get("t")
                parsed: CellValue
                if kind == "s":
                    parsed = strings[int(value or "0")]
                elif kind == "inlineStr":
                    parsed = "".join(cell.findtext("m:is/m:t", default="", namespaces=main))
                elif kind == "b":
                    parsed = value == "1"
                else:
                    parsed = float(value) if value is not None else None
                cells[cell.attrib["r"]] = parsed
            result[sheet.attrib["name"]] = cells
        return result

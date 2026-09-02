from __future__ import annotations

from lxml import etree

FDSN_NS = "http://www.fdsn.org/xml/station/1"
NSMAP = {None: FDSN_NS}


def qname(tag: str, ns: str = FDSN_NS) -> str:
    return f"{{{ns}}}{tag}"


def local(tag: str) -> str:
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def el(tag: str, text: str | None = None, **attrs: str) -> etree._Element:
    node = etree.Element(qname(tag), nsmap=NSMAP)
    for key, value in attrs.items():
        if value is not None:
            node.set(key, str(value))
    if text is not None:
        node.text = str(text)
    return node


def child_text(parent: etree._Element, tag: str) -> str | None:
    found = parent.find(qname(tag))
    if found is None or found.text is None:
        return None
    text = found.text.strip()
    return text or None


def set_child(parent: etree._Element, tag: str, text: str) -> None:
    found = parent.find(qname(tag))
    if found is None:
        parent.append(el(tag, text))
    else:
        found.text = text


def parse_root(xml: str | bytes) -> etree._Element:
    raw = xml.encode("utf-8") if isinstance(xml, str) else xml
    return etree.fromstring(raw)


def dumps(root: etree._Element) -> str:
    return etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", pretty_print=True
    ).decode("utf-8")


def namespaced_copy(node: etree._Element, ns: str = FDSN_NS) -> etree._Element:
    copy = etree.Element(qname(etree.QName(node).localname, ns), nsmap=NSMAP)
    for key, value in node.attrib.items():
        copy.set(key, value)
    copy.text = node.text
    copy.tail = node.tail
    for child in node:
        copy.append(namespaced_copy(child, ns))
    return copy

"""
epub_common.py
==============

Shared helpers used by the Bible EPUB scripts (fix_links.py, build_navigation.py,
validate_epub.py).

What lives here
---------------
* Unpacking an .epub (it is just a ZIP file) into a working folder and packing it
  back in the exact way the EPUB spec requires (the "mimetype" file first and
  stored without compression).
* Reading/writing XHTML files with lxml, including a small "entity fix": many
  EPUBs made with Sigil contain HTML entities such as ``&nbsp;`` that are NOT
  valid in XML unless the external DTD is loaded. Strict XML parsers (and some
  Kindle conversions) choke on them, so we turn them into numeric references
  (``&#160;``), which mean exactly the same thing.
* Reading the OPF package file (manifest + spine) and the NCX table of contents.
* A table with all Bible books in Spanish (names, aliases, testament and the
  usual number of chapters) used to recognise which file is which book.

Nothing in this module modifies an EPUB by itself; the scripts decide what to do.
"""

from __future__ import annotations

import html.entities
import os
import posixpath
import re
import shutil
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from lxml import etree

# ---------------------------------------------------------------------------
# XML namespaces used inside an EPUB 2 file
# ---------------------------------------------------------------------------
XHTML_NS = "http://www.w3.org/1999/xhtml"
OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"

# Short prefixes for XPath queries, e.g. tree.xpath("//x:a", namespaces=NS)
NS = {"x": XHTML_NS, "opf": OPF_NS, "dc": DC_NS, "ncx": NCX_NS}

# The DOCTYPE used by the original files (XHTML 1.1, standard for EPUB 2).
XHTML11_DOCTYPE = (
    '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"\n'
    '  "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">'
)


def q(tag: str, ns: str = XHTML_NS) -> str:
    """Return a fully qualified lxml tag name, e.g. q('p') -> '{http://...xhtml}p'."""
    return f"{{{ns}}}{tag}"


def local_name(el) -> str:
    """Return the tag name without namespace ('p', 'h2', ...). Comments return ''."""
    if not isinstance(el.tag, str):  # comments / processing instructions
        return ""
    return etree.QName(el).localname


# ---------------------------------------------------------------------------
# Entity handling
# ---------------------------------------------------------------------------
# The five entities that XML itself understands; everything else must be numeric.
_XML_BUILTIN_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}
_NAMED_ENTITY_RE = re.compile(r"&([A-Za-z][A-Za-z0-9]*);")


def replace_html_entities(text: str) -> tuple[str, int]:
    """
    Replace HTML named entities (&nbsp;, &eacute;, ...) by numeric references
    (&#160;, &#233;, ...). Returns the new text and how many replacements were made.

    The five XML built-in entities are left untouched. Unknown names are also left
    untouched (they will show up as a parse error so a human can look at them).
    """
    count = 0

    def _sub(match: re.Match) -> str:
        nonlocal count
        name = match.group(1)
        if name in _XML_BUILTIN_ENTITIES:
            return match.group(0)
        codepoint = html.entities.name2codepoint.get(name)
        if codepoint is None:
            return match.group(0)
        count += 1
        return f"&#{codepoint};"

    return _NAMED_ENTITY_RE.sub(_sub, text), count


# ---------------------------------------------------------------------------
# Parsing / serialising XML documents
# ---------------------------------------------------------------------------
def make_parser() -> etree.XMLParser:
    """
    A safe XML parser: never downloads DTDs from the internet, never expands
    external entities, and keeps whitespace exactly as it is in the file.
    """
    return etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        remove_blank_text=False,
        huge_tree=True,  # some Bible books are > 1 MB of text
    )


def parse_xml_file(path: Path) -> etree._ElementTree:
    """Parse an XML/XHTML file, fixing HTML entities on the fly (in memory only)."""
    raw = path.read_text(encoding="utf-8")
    raw, _ = replace_html_entities(raw)
    return etree.ElementTree(etree.fromstring(raw.encode("utf-8"), make_parser()))


def write_xhtml_file(path: Path, tree: etree._ElementTree) -> None:
    """
    Write an XHTML document back to disk with a standard XML declaration and the
    XHTML 1.1 DOCTYPE (the same header Sigil produces).
    """
    body = etree.tostring(tree.getroot(), encoding="unicode")
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n' + XHTML11_DOCTYPE + "\n\n" + body + "\n",
        encoding="utf-8",
    )


def write_xml_file(path: Path, tree: etree._ElementTree, doctype: str | None = None) -> None:
    """Write a generic XML file (OPF, NCX) with an XML declaration."""
    body = etree.tostring(tree.getroot(), encoding="unicode")
    header = '<?xml version="1.0" encoding="utf-8"?>\n'
    if doctype:
        header += doctype + "\n"
    path.write_text(header + body + "\n", encoding="utf-8")


def element_text(el, skip_links: bool = False) -> str:
    """
    Return all the text inside an element, collapsed to single spaces.
    With skip_links=True the text of <a> descendants is ignored; this is used to
    drop footnote markers like "[*]" or "[a]" from headings.
    """
    parts: list[str] = []

    def walk(node, inside_link: bool) -> None:
        is_link = local_name(node) == "a"
        hidden = skip_links and (inside_link or is_link)
        if node.text and not hidden and isinstance(node.tag, str):
            parts.append(node.text)
        for child in node:
            walk(child, inside_link or is_link)
            if child.tail and not (skip_links and inside_link):
                parts.append(child.tail)

    walk(el, False)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


# ---------------------------------------------------------------------------
# Unpack / pack
# ---------------------------------------------------------------------------
def unpack_epub(epub_path: Path, work_dir: Path) -> Path:
    """
    Extract an EPUB into work_dir (which is emptied first). Returns work_dir.
    """
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    with zipfile.ZipFile(epub_path) as zf:
        zf.extractall(work_dir)
    return work_dir


def pack_epub(work_dir: Path, epub_path: Path) -> None:
    """
    Zip work_dir back into a valid EPUB:
      1. 'mimetype' must be the very first entry and must be STORED (no compression),
         otherwise readers/Kindle may reject the file.
      2. Everything else is compressed normally.
    macOS junk files (.DS_Store, __MACOSX) are skipped.
    """
    epub_path.parent.mkdir(parents=True, exist_ok=True)
    if epub_path.exists():
        epub_path.unlink()
    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr(
            zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED
        )
        for root, dirs, files in os.walk(work_dir):
            dirs[:] = sorted(d for d in dirs if d != "__MACOSX")
            for name in sorted(files):
                if name in ("mimetype", ".DS_Store"):
                    continue
                full = Path(root) / name
                arc = full.relative_to(work_dir).as_posix()
                zf.write(full, arc, compress_type=zipfile.ZIP_DEFLATED)


# ---------------------------------------------------------------------------
# OPF package (manifest + spine + guide)
# ---------------------------------------------------------------------------
@dataclass
class ManifestItem:
    id: str
    href: str  # relative to the OPF folder, e.g. "Text/001.xhtml"
    media_type: str
    element: etree._Element


@dataclass
class EpubPackage:
    """In-memory view of an unpacked EPUB. Paths are absolute pathlib.Path objects."""

    root_dir: Path
    opf_path: Path
    opf_tree: etree._ElementTree
    manifest: dict[str, ManifestItem] = field(default_factory=dict)  # by id
    spine_ids: list[str] = field(default_factory=list)

    # -- paths ---------------------------------------------------------------
    @property
    def opf_dir(self) -> Path:
        return self.opf_path.parent

    def item_path(self, item: ManifestItem) -> Path:
        return self.opf_dir / unquote(item.href)

    def href_of_path(self, path: Path) -> str:
        """Inverse of item_path: absolute path -> href relative to the OPF folder."""
        return path.relative_to(self.opf_dir).as_posix()

    # -- convenience lists ------------------------------------------------------
    def xhtml_items(self) -> list[ManifestItem]:
        return [i for i in self.manifest.values() if i.media_type == "application/xhtml+xml"]

    def spine_items(self) -> list[ManifestItem]:
        return [self.manifest[i] for i in self.spine_ids if i in self.manifest]

    def ncx_item(self) -> ManifestItem | None:
        for item in self.manifest.values():
            if item.media_type == "application/x-dtbncx+xml":
                return item
        return None

    def language(self) -> str:
        lang = self.opf_tree.find(f".//{q('language', DC_NS)}")
        return (lang.text or "es").strip() if lang is not None else "es"

    # -- editing helpers --------------------------------------------------------
    def manifest_el(self) -> etree._Element:
        return self.opf_tree.find(q("manifest", OPF_NS))

    def spine_el(self) -> etree._Element:
        return self.opf_tree.find(q("spine", OPF_NS))

    def guide_el(self) -> etree._Element | None:
        return self.opf_tree.find(q("guide", OPF_NS))

    def add_manifest_item(self, item_id: str, href: str, media_type: str) -> ManifestItem:
        el = etree.SubElement(self.manifest_el(), q("item", OPF_NS))
        el.set("id", item_id)
        el.set("href", href)
        el.set("media-type", media_type)
        el.tail = "\n    "
        item = ManifestItem(item_id, href, media_type, el)
        self.manifest[item_id] = item
        return item

    def remove_manifest_item(self, item_id: str) -> None:
        item = self.manifest.pop(item_id, None)
        if item is not None:
            item.element.getparent().remove(item.element)
        for ref in list(self.spine_el()):
            if ref.get("idref") == item_id:
                self.spine_el().remove(ref)
        self.spine_ids = [i for i in self.spine_ids if i != item_id]

    def save_opf(self) -> None:
        write_xml_file(self.opf_path, self.opf_tree)


def load_package(root_dir: Path) -> EpubPackage:
    """Read META-INF/container.xml to find the OPF, then read manifest and spine."""
    container = parse_xml_file(root_dir / "META-INF" / "container.xml")
    rootfile = container.find(f".//{{{CONTAINER_NS}}}rootfile")
    opf_path = root_dir / rootfile.get("full-path")
    opf_tree = parse_xml_file(opf_path)
    pkg = EpubPackage(root_dir=root_dir, opf_path=opf_path, opf_tree=opf_tree)
    for el in opf_tree.iterfind(f".//{q('item', OPF_NS)}"):
        pkg.manifest[el.get("id")] = ManifestItem(
            el.get("id"), el.get("href"), el.get("media-type"), el
        )
    pkg.spine_ids = [el.get("idref") for el in opf_tree.iterfind(f".//{q('itemref', OPF_NS)}")]
    return pkg


# ---------------------------------------------------------------------------
# Link helpers
# ---------------------------------------------------------------------------
def split_href(href: str) -> tuple[str, str]:
    """'../Text/a.xhtml#x' -> ('../Text/a.xhtml', 'x'). Fragment may be ''."""
    path, _, frag = href.partition("#")
    return unquote(path), unquote(frag)


def is_external(href: str) -> bool:
    """True for http:, mailto:, etc. Those are never touched."""
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", href))


def resolve_href(source_file: Path, href: str) -> tuple[Path, str]:
    """
    Turn an href found inside source_file into (absolute target path, fragment).
    An href like '#v3' points to the same file.
    """
    path, frag = split_href(href)
    if not path:
        return source_file, frag
    return Path(os.path.normpath(source_file.parent / path)), frag


def relative_href(from_file: Path, to_file: Path, fragment: str = "") -> str:
    """Build the shortest relative href from one file to another (with optional #fragment)."""
    if from_file == to_file:
        rel = ""
    else:
        rel = posixpath.relpath(to_file.as_posix(), from_file.parent.as_posix())
    return rel + (f"#{fragment}" if fragment else "")


# ---------------------------------------------------------------------------
# Bible book catalogue (Spanish)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BookInfo:
    key: str  # stable internal key, e.g. "1sam"
    name: str  # display name used in the generated table of contents
    testament: str  # "AT" (Old Testament, incl. deuterocanonical) or "NT"
    chapters: tuple[int, ...]  # accepted chapter counts (varies between editions)
    aliases: tuple[str, ...] = ()  # extra spellings, already normalised


# Order follows the usual Catholic order; it does not matter for detection,
# the generated index always follows the order of the EPUB spine.
BOOKS: tuple[BookInfo, ...] = (
    BookInfo("gen", "Génesis", "AT", (50,)),
    BookInfo("exo", "Éxodo", "AT", (40,)),
    BookInfo("lev", "Levítico", "AT", (27,)),
    BookInfo("num", "Números", "AT", (36,)),
    BookInfo("deu", "Deuteronomio", "AT", (34,)),
    BookInfo("jos", "Josué", "AT", (24,)),
    BookInfo("jue", "Jueces", "AT", (21,)),
    BookInfo("rut", "Rut", "AT", (4,)),
    BookInfo("1sam", "1 Samuel", "AT", (31,)),
    BookInfo("2sam", "2 Samuel", "AT", (24,)),
    BookInfo("1rey", "1 Reyes", "AT", (22,)),
    BookInfo("2rey", "2 Reyes", "AT", (25,)),
    BookInfo("1cro", "1 Crónicas", "AT", (29,)),
    BookInfo("2cro", "2 Crónicas", "AT", (36,)),
    BookInfo("esd", "Esdras", "AT", (10,)),
    BookInfo("neh", "Nehemías", "AT", (13,)),
    BookInfo("tob", "Tobías", "AT", (14,), ("tobit",)),
    BookInfo("jdt", "Judit", "AT", (16,)),
    BookInfo("est", "Ester", "AT", (10, 16)),
    BookInfo("1mac", "1 Macabeos", "AT", (16,)),
    BookInfo("2mac", "2 Macabeos", "AT", (15,)),
    BookInfo("job", "Job", "AT", (42,)),
    BookInfo("sal", "Salmos", "AT", (150, 151), ("salmo", "libro de los salmos")),
    BookInfo("pro", "Proverbios", "AT", (31,)),
    BookInfo("ecl", "Eclesiastés", "AT", (12,), ("qohelet", "cohelet")),
    BookInfo("can", "Cantar de los Cantares", "AT", (8,), ("cantares", "cantar")),
    BookInfo("sab", "Sabiduría", "AT", (19,)),
    BookInfo("eclo", "Eclesiástico", "AT", (51,), ("sirac", "siracida", "ben sira")),
    BookInfo("isa", "Isaías", "AT", (66,)),
    BookInfo("jer", "Jeremías", "AT", (52,)),
    BookInfo("lam", "Lamentaciones", "AT", (5,)),
    BookInfo("bar", "Baruc", "AT", (5, 6), ("baruch",)),
    BookInfo("cjer", "Carta de Jeremías", "AT", (1,)),
    BookInfo("eze", "Ezequiel", "AT", (48,)),
    BookInfo("dan", "Daniel", "AT", (12, 14)),
    BookInfo("ose", "Oseas", "AT", (14,)),
    BookInfo("joe", "Joel", "AT", (3, 4)),
    BookInfo("amo", "Amós", "AT", (9,)),
    BookInfo("abd", "Abdías", "AT", (1,)),
    BookInfo("jon", "Jonás", "AT", (4,)),
    BookInfo("miq", "Miqueas", "AT", (7,)),
    BookInfo("nah", "Nahúm", "AT", (3,), ("nahum", "nahun")),
    BookInfo("hab", "Habacuc", "AT", (3,)),
    BookInfo("sof", "Sofonías", "AT", (3,)),
    BookInfo("hag", "Hageo", "AT", (2,), ("ageo",)),
    BookInfo("zac", "Zacarías", "AT", (14,)),
    BookInfo("mal", "Malaquías", "AT", (3, 4)),
    BookInfo("mat", "Mateo", "NT", (28,), ("san mateo", "evangelio segun san mateo")),
    BookInfo("mar", "Marcos", "NT", (16,), ("san marcos", "evangelio segun san marcos")),
    BookInfo("luc", "Lucas", "NT", (24,), ("san lucas", "evangelio segun san lucas")),
    BookInfo("jua", "Juan", "NT", (21,), ("san juan", "evangelio segun san juan")),
    BookInfo("hch", "Hechos", "NT", (28,), ("hechos de los apostoles",)),
    BookInfo("rom", "Romanos", "NT", (16,)),
    BookInfo("1cor", "1 Corintios", "NT", (16,)),
    BookInfo("2cor", "2 Corintios", "NT", (13,)),
    BookInfo("gal", "Gálatas", "NT", (6,)),
    BookInfo("efe", "Efesios", "NT", (6,)),
    BookInfo("fil", "Filipenses", "NT", (4,)),
    BookInfo("col", "Colosenses", "NT", (4,)),
    BookInfo("1tes", "1 Tesalonicenses", "NT", (5,)),
    BookInfo("2tes", "2 Tesalonicenses", "NT", (3,)),
    BookInfo("1tim", "1 Timoteo", "NT", (6,)),
    BookInfo("2tim", "2 Timoteo", "NT", (4,)),
    BookInfo("tit", "Tito", "NT", (3,)),
    BookInfo("flm", "Filemón", "NT", (1,)),
    BookInfo("heb", "Hebreos", "NT", (13,)),
    BookInfo("stg", "Santiago", "NT", (5,)),
    BookInfo("1pe", "1 Pedro", "NT", (5,)),
    BookInfo("2pe", "2 Pedro", "NT", (3,)),
    BookInfo("1jn", "1 Juan", "NT", (5,)),
    BookInfo("2jn", "2 Juan", "NT", (1,)),
    BookInfo("3jn", "3 Juan", "NT", (1,)),
    BookInfo("jud", "Judas", "NT", (1,)),
    BookInfo("apo", "Apocalipsis", "NT", (22,)),
)

# Ordinal words/roman numerals that may precede a book name ("Primera de Juan",
# "II Reyes", ...). They are converted to a plain digit before the lookup.
_ORDINALS = {
    "i": "1", "1a": "1", "1o": "1", "primer": "1", "primera": "1", "primero": "1",
    "ii": "2", "2a": "2", "2o": "2", "segunda": "2", "segundo": "2",
    "iii": "3", "3a": "3", "3o": "3", "tercera": "3", "tercero": "3",
}


def normalise_name(text: str) -> str:
    """
    Lowercase, remove accents and punctuation, collapse spaces and turn a leading
    ordinal into a digit. 'II REYES' -> '2 reyes', 'Génesis' -> 'genesis'.
    """
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", text.lower())
    words = text.split()
    if words and words[0] in _ORDINALS:
        words[0] = _ORDINALS[words[0]]
    # "1 de juan" / "1 carta de juan" -> "1 juan"
    if len(words) >= 3 and words[0].isdigit() and words[1] in ("de", "carta", "libro"):
        words = [words[0]] + [w for w in words[1:] if w not in ("de", "carta", "libro", "a", "los")]
    return " ".join(words)


def _build_book_index() -> dict[str, BookInfo]:
    index: dict[str, BookInfo] = {}
    for book in BOOKS:
        for alias in (book.name, *book.aliases):
            index[normalise_name(alias)] = book
    return index


BOOK_INDEX = _build_book_index()


def lookup_book(heading_text: str) -> BookInfo | None:
    """Return the BookInfo whose name matches a heading text exactly, or None."""
    return BOOK_INDEX.get(normalise_name(heading_text))


def testament_of_heading(heading_text: str) -> str | None:
    """Recognise the 'Antiguo Testamento' / 'Nuevo Testamento' divider pages."""
    norm = normalise_name(heading_text)
    if norm in ("antiguo testamento", "el antiguo testamento"):
        return "AT"
    if norm in ("nuevo testamento", "el nuevo testamento"):
        return "NT"
    return None


# ---------------------------------------------------------------------------
# Chapter / verse markup (shared by fix_links.py and build_navigation.py)
# ---------------------------------------------------------------------------
# A chapter heading whose whole text is "12", "12." or "Capítulo 12".
CHAPTER_HEADING_RE = re.compile(r"^(?:cap[ií]tulo\s+)?(\d{1,3})\.?$", re.IGNORECASE)
# A Psalm heading: "Salmo 12", "Salmo 12 (11)", "Salmos 12".
PSALM_HEADING_RE = re.compile(r"^salmos?\s+(\d{1,3})\b", re.IGNORECASE)
# A verse number: "12", "12-13", "12–13", optionally followed by a letter ("12a").
VERSE_RE = re.compile(r"^(\d{1,3})(?:\s*[-–]\s*(\d{1,3}))?[a-z]?$")
# <sup> with these classes are never verses (e.g. the book abbreviation "Gén").
NON_VERSE_SUP_CLASSES = {"sigla"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def css_classes(el) -> set[str]:
    return set((el.get("class") or "").split())


def is_verse_sup(sup) -> bool:
    """True for <sup>12</sup> / <sup class="versiculo">12</sup> not inside a link."""
    if local_name(sup) != "sup" or css_classes(sup) & NON_VERSE_SUP_CLASSES or len(sup):
        return False
    if not VERSE_RE.match((sup.text or "").strip()):
        return False
    return not any(local_name(a) == "a" for a in sup.iterancestors())


def verse_number(sup) -> int:
    """First number of a verse label: '12-13' -> 12."""
    return int(VERSE_RE.match((sup.text or "").strip()).group(1))


def remove_keep_tail(el) -> None:
    """Remove an element; its tail text (if not just whitespace) is kept in place."""
    parent = el.getparent()
    if el.tail and el.tail.strip():
        prev = el.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "") + el.tail
        else:
            parent.text = (parent.text or "") + el.tail
    parent.remove(el)


def assign_play_order(nav_map) -> None:
    """
    Number every <navPoint> in document order (playOrder = 1, 2, 3 ...).
    The EPUB 2 rule is that entries pointing to the SAME target must share the
    same playOrder, so a repeated target reuses the number it got first.
    """
    by_src: dict[str, int] = {}
    counter = 0
    for nav_point in nav_map.iter(q("navPoint", NCX_NS)):
        content = nav_point.find(q("content", NCX_NS))
        src = content.get("src", "") if content is not None else ""
        if src not in by_src:
            counter += 1
            by_src[src] = counter
        nav_point.set("playOrder", str(by_src[src]))

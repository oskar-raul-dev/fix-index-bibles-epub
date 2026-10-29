"""
set_metadata.py
===============

Step 3 of 3. Writes the final metadata and the final file name, using the map in
bibles_config.py:

    title / title sort       "01-La Biblia de las Américas"
    author / author sort     "Anónimo"   (any previous author is replaced;
                                          translators and other contributors stay)
    collection (series)      "Biblias", position 1, 2, 3 ...
    file name                "01-La Biblia de las Américas - Anónimo.epub"

The collection is written the way Calibre stores it in an EPUB 2 file
(<meta name="calibre:series"> and <meta name="calibre:series_index">), so Calibre
shows it as the book's series when you add the file.

How to use
----------
    python set_metadata.py                      # uses BIBLE_PATH below
    python set_metadata.py "some file.epub"

The input can be the original EPUB or any intermediate one ("... [fixed].epub",
"... [fixed] [nav].epub"): the " [fixed]" / " [nav]" suffixes are ignored when the
file is looked up in bibles_config.BIBLES.
"""

from __future__ import annotations

import sys
from pathlib import Path

from lxml import etree

from bibles_config import AUTHOR, BIBLES, COLLECTION, OUTPUT_DIR, WORK_DIR
from epub_common import DC_NS, NCX_NS, OPF_NS, load_package, pack_epub, parse_xml_file, q, unpack_epub, write_xml_file

# Folders (OUTPUT_DIR, WORK_DIR) come from bibles_config.py.
BIBLE_PATH = OUTPUT_DIR / "[Biblias 01] La Biblia de las Americas [10343] (r1.4) [fixed] [nav].epub"

# Suffixes added by the other scripts; removed to find the original name.
KNOWN_SUFFIXES = (" [nav]", " [fixed]")


def original_name(epub_path: Path) -> str:
    """'[Biblias 01] ... (r1.4) [fixed] [nav].epub' -> '[Biblias 01] ... (r1.4).epub'."""
    stem = epub_path.stem
    changed = True
    while changed:
        changed = False
        for suffix in KNOWN_SUFFIXES:
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
                changed = True
    return stem + ".epub"


def lookup(epub_path: Path) -> tuple[int, str]:
    name = original_name(epub_path)
    if name not in BIBLES:
        sys.exit(f"'{name}' is not in bibles_config.BIBLES. Add it there first.")
    return BIBLES[name]


def set_meta(metadata, name: str, value: str) -> None:
    """Create or replace <meta name="..." content="..."/> inside <metadata>."""
    for meta in metadata.findall(q("meta", OPF_NS)):
        if meta.get("name") == name:
            metadata.remove(meta)
    meta = etree.SubElement(metadata, q("meta", OPF_NS), name=name, content=value)
    meta.tail = "\n  "


def set_metadata(epub_path: Path, output_dir: Path = OUTPUT_DIR, work_dir: Path = WORK_DIR) -> Path:
    epub_path = Path(epub_path)
    number, title = lookup(epub_path)
    out_path = Path(output_dir) / f"{title} - {AUTHOR}.epub"
    unpacked = unpack_epub(epub_path, Path(work_dir) / f"{title} [meta]")
    pkg = load_package(unpacked)
    metadata = pkg.opf_tree.find(q("metadata", OPF_NS))
    opf_attr = f"{{{OPF_NS}}}"

    # Title: keep one <dc:title>.
    titles = metadata.findall(q("title", DC_NS))
    for extra in titles[1:]:
        metadata.remove(extra)
    if titles:
        titles[0].text = title
    else:
        etree.SubElement(metadata, q("title", DC_NS)).text = title

    # Author: replace every <dc:creator> by a single "Anónimo" (contributors stay).
    creators = metadata.findall(q("creator", DC_NS))
    for creator in creators[1:]:
        metadata.remove(creator)
    creator = creators[0] if creators else etree.SubElement(metadata, q("creator", DC_NS))
    creator.text = AUTHOR
    creator.attrib.clear()
    creator.set(f"{opf_attr}role", "aut")
    creator.set(f"{opf_attr}file-as", AUTHOR)

    # Sort title, collection and position (Calibre's EPUB 2 conventions).
    set_meta(metadata, "calibre:title_sort", title)
    set_meta(metadata, "calibre:series", COLLECTION)
    set_meta(metadata, "calibre:series_index", str(number))
    pkg.save_opf()

    # The NCX also carries the title (<docTitle>), keep it consistent.
    ncx_item = pkg.ncx_item()
    if ncx_item is not None:
        ncx_path = pkg.item_path(ncx_item)
        ncx = parse_xml_file(ncx_path)
        text = ncx.find(f"{q('docTitle', NCX_NS)}/{q('text', NCX_NS)}")
        if text is not None:
            text.text = title
            write_xml_file(
                ncx_path,
                ncx,
                '<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN"\n'
                '   "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">',
            )

    pack_epub(unpacked, out_path)
    print(f"[set_metadata] {epub_path.name}")
    print(f"  title: {title} | author: {AUTHOR} | collection: {COLLECTION} #{number}")
    print(f"  -> {out_path}")
    return out_path


if __name__ == "__main__":
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else BIBLE_PATH
    if not source.exists():
        sys.exit(f"EPUB not found: {source}\nEdit BIBLE_PATH at the top of {Path(__file__).name}.")
    set_metadata(source)

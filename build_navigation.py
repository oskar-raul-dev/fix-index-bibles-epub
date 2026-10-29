"""
build_navigation.py
===================

Step 2 of 2. Rebuilds the navigation of a Bible EPUB for comfortable reading on
Kindle (and any other reader):

1. Table of contents (NCX, the one Kindle shows in "Go to / Table of contents"):
       Front matter (cover, title, introduction ...)
       Antiguo Testamento            <- only if the Bible has both testaments
           Génesis
               Capítulo 1
               Capítulo 2 ...
           Éxodo ...
       Nuevo Testamento
           Mateo ...
       Back matter (notes, maps, about the author ...)
   Every level folds: open "Antiguo Testamento", then "Génesis", then pick a
   chapter. With TESTAMENTS_AS_PARENTS = False the books go to the top level.
   (HTML <details> is not supported by Kindle; nested NCX entries are the way
   to get folding lists there.)

2. An HTML index page ("Índice") with the books split by testament. It is also
   declared as the guide "toc" page so Kindle's "Table of Contents" jumps there.

3. At the top of every book: a list of links to each chapter ("1 · 2 · 3 ...").

4. At the start of every chapter: a list of links (anchors) to every verse,
   plus a small link back to the book's chapter list.
   Lists are plain wrapping paragraphs, not tables: Kindle renders tables as
   special blocks (thumbnails you must tap) and big ones can freeze it.
   NAV_LAYOUT = "table" brings the grid back if you prefer it.

How to use
----------
1. Change BIBLE_PATH below (or pass the path as the first argument). Normally you
   run fix_links.py first and use its "[fixed]" output here.
2. Run:  python build_navigation.py
3. The result is written to OUTPUT_DIR with the suffix " [nav]".
   The input file is never modified. Running the script again on its own output
   is safe: previously generated tables are removed and rebuilt.

How books, chapters and verses are recognised (works for all 8 Bibles)
---------------------------------------------------------------------
* Book:     the first <h1>/<h2>/<h3> of a file whose text is a known book name
            (see BOOKS in epub_common.py). A following file without a book
            heading but with verses (e.g. "SalmosII.xhtml") continues the book.
* Chapter:  a heading (<h2>..<h6>) whose text is "12", "Capítulo 12" or
            "Salmo 12 ..."; or an inline marker like
            <span class="firstletter"><sup class="sigla">Gén</sup>12</span>.
            Books without any chapter marker (Abdías, Judas ...) get chapter 1.
* Verse:    <sup>12</sup>, <sup class="versiculo">12</sup> or ranges <sup>12-13</sup>
            that are not inside a link (footnote markers like [a] are links).
"""

from __future__ import annotations

import copy
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from bibles_config import OUTPUT_DIR, WORK_DIR
from epub_common import (
    CHAPTER_HEADING_RE,
    HEADING_TAGS,
    NCX_NS,
    NON_VERSE_SUP_CLASSES,
    OPF_NS,
    PSALM_HEADING_RE,
    BookInfo,
    EpubPackage,
    assign_play_order,
    element_text,
    is_external,
    is_verse_sup,
    load_package,
    local_name,
    lookup_book,
    pack_epub,
    parse_xml_file,
    q,
    relative_href,
    resolve_href,
    testament_of_heading,
    unpack_epub,
    write_xhtml_file,
    write_xml_file,
)

# ---------------------------------------------------------------------------
# Configuration — change these to your needs
# ---------------------------------------------------------------------------
# Folders (OUTPUT_DIR, WORK_DIR) come from bibles_config.py.

# The EPUB to process. By default: the output of fix_links.py for Bible 01.
BIBLE_PATH = OUTPUT_DIR / "[Biblias 01] La Biblia de las Americas [10343] (r1.4) [fixed].epub"
OUTPUT_SUFFIX = " [nav]"

# How the chapter/verse link lists are drawn: "inline" (a wrapping paragraph,
# recommended for Kindle) or "table" (a grid; Kindle renders tables poorly: they
# can appear as a thumbnail you must tap, and large ones can freeze the device).
NAV_LAYOUT = "inline"
# Text placed between two links in the "inline" layout.
NAV_SEPARATOR = " · "

# Add the list of verse links at the start of every chapter. It is the heaviest part
# (one link per verse, ~31,000 per Bible). Set False if the Kindle still feels slow:
# the chapter lists and the folding table of contents stay.
ADD_VERSE_LISTS = True

# Split big book files into several smaller files, always at a chapter boundary.
# Kindle lays out a whole file before showing any page of it, so huge files (Salmos
# is ~500 KB) make jumps, "back to library" and page turns slow. Amazon's own
# guideline is to keep each file small; long omnibus books do exactly this.
SPLIT_LARGE_FILES = True
SPLIT_MAX_BYTES = 100_000  # target maximum size of each file (bytes of XHTML)
# Experiment: put EVERY chapter in its own file (ignores SPLIT_MAX_BYTES). Then each
# table-of-contents entry points to the start of a file, like ordinary books do,
# which may let Kindle jump straight to the chapter without the thumbnail preview.
# A Bible ends up with ~1,200 small files. Set False to go back to ~100 KB parts.
CHAPTER_PER_FILE = True

# Number of cells per row in the verse and chapter tables (only for NAV_LAYOUT = "table").
VERSE_COLUMNS = 10
CHAPTER_COLUMNS = 10

# Labels shown to the reader (the Bibles are in Spanish).
LABEL_OLD_TESTAMENT = "Antiguo Testamento"
LABEL_NEW_TESTAMENT = "Nuevo Testamento"
LABEL_INDEX = "Índice"
LABEL_CHAPTER = "Capítulo {n}"
LABEL_PSALM = "Salmo {n}"
LABEL_BACK_TO_CHAPTERS = "{book}: capítulos"
LABEL_NOTES_GROUP = "Notas"

# True: use the book names as written in each Bible ("Hechos de los Apóstoles").
# False: use the uniform names of epub_common.BOOKS ("Hechos").
USE_SOURCE_BOOK_NAMES = True

# Put the generated HTML index in the book and use it as the Kindle "toc" page.
CREATE_HTML_INDEX = True
# Remove an older generated HTML table of contents (e.g. Sigil's TOC.xhtml).
REMOVE_OLD_HTML_TOC = True
# Table of contents layout.
#   True (default): Antiguo Testamento > Génesis > Capítulo 1 ... (3 folding levels;
#       a Kindle Paperwhite folds all three).
#   False: "Antiguo Testamento" is a plain entry and the books sit next to it,
#       each one folding its chapters (2 levels, for readers that fold only 2).
TESTAMENTS_AS_PARENTS = True

# Group many consecutive "Notas de ..." entries of the NCX under one "Notas" entry.
GROUP_NOTES_IN_NCX = True

# A file without a book heading must have at least this many verse numbers to be
# treated as the continuation of the previous book (protects against notes pages).
MIN_CONTINUATION_VERSES = 10

# Inline chapter markers: elements with one of these classes contain a chapter number.
INLINE_CHAPTER_CLASSES = {"firstletter"}

# Everything this script inserts uses this prefix (class names, ids, file names).
# That is how a second run finds and removes what the first run created.
PREFIX = "bnav"
CSS_HREF = f"Styles/{PREFIX}.css"
INDEX_HREF = f"Text/{PREFIX}-indice.xhtml"

CSS_CONTENT = f"""/* Generated by build_navigation.py — navigation tables */
table.{PREFIX}-grid {{
  border-collapse: collapse;
  margin: 0.4em auto 0.8em auto;
}}
table.{PREFIX}-grid td {{
  border: 1px solid #999;
  padding: 0.15em 0.35em;
  text-align: center;
  font-size: 0.8em;
  text-indent: 0;
}}
table.{PREFIX}-grid a {{
  text-decoration: none;
}}
p.{PREFIX}-links {{
  text-indent: 0;
  text-align: left;
  line-height: 1.9;
  margin: 0.4em 0 0.6em 0;
}}
p.{PREFIX}-links a {{
  text-decoration: none;
}}
p.{PREFIX}-back {{
  font-size: 0.75em;
  text-align: right;
  text-indent: 0;
  margin: 0.2em 0 0 0;
}}
h1.{PREFIX}-title, h2.{PREFIX}-testament {{
  text-align: center;
}}
p.{PREFIX}-book {{
  text-indent: 0;
  margin: 0.2em 0 0.2em 1em;
}}
"""

# Chapter/verse regular expressions live in epub_common.py (shared with fix_links.py).
NOTES_LABEL_RE = re.compile(r"^notas?\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class Verse:
    label: str  # "12" or "12-13"
    element: etree._Element  # the <sup>
    anchor: str = ""  # id given to the <sup>


@dataclass
class Chapter:
    number: int
    path: Path  # file where the chapter starts
    marker: etree._Element  # heading or block that starts the chapter
    insert_after: bool  # True: verse table goes after the marker (headings)
    is_psalm: bool = False
    anchor: str = ""
    verses: list[Verse] = field(default_factory=list)
    start: etree._Element | None = None  # first element of the chapter (for splitting)
    starts_file: bool = False  # True when the chapter is the first thing in its file

    @property
    def label(self) -> str:
        return (LABEL_PSALM if self.is_psalm else LABEL_CHAPTER).format(n=self.number)


@dataclass
class Book:
    info: BookInfo
    files: list[Path]
    heading: etree._Element
    name: str = ""  # name as written in this Bible ("Hechos de los Apóstoles")
    anchor: str = ""
    chapters: list[Chapter] = field(default_factory=list)

    @property
    def first_file(self) -> Path:
        return self.files[0]


@dataclass
class Bible:
    pkg: EpubPackage
    docs: dict[Path, etree._ElementTree]  # every spine document, in spine order
    books: list[Book] = field(default_factory=list)
    dividers: dict[str, Path] = field(default_factory=dict)  # "AT"/"NT" -> divider page
    warnings: list[str] = field(default_factory=list)

    def spine_paths(self) -> list[Path]:
        return list(self.docs)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def classes(el) -> set[str]:
    return set((el.get("class") or "").split())


def is_generated(el) -> bool:
    return any(c.startswith(f"{PREFIX}-") for c in classes(el))


def has_link_ancestor(el) -> bool:
    return any(local_name(a) == "a" for a in el.iterancestors())


def block_of(el) -> etree._Element:
    """The block element (child of <body> or of a <div>) that contains el."""
    node = el
    while node.getparent() is not None and local_name(node.getparent()) not in ("body", "div", "blockquote"):
        node = node.getparent()
    return node


def unique_id(wanted: str, used: set[str]) -> str:
    candidate, n = wanted, 1
    while candidate in used:
        n += 1
        candidate = f"{wanted}-{n}"
    used.add(candidate)
    return candidate


def ensure_id(el, wanted: str, used: set[str]) -> str:
    """Keep an existing id (other links may use it); otherwise assign a new unique one."""
    if el.get("id"):
        return el.get("id")
    new_id = unique_id(wanted, used)
    el.set("id", new_id)
    return new_id


def x(tag: str, parent=None, text: str | None = None, **attrs) -> etree._Element:
    """Tiny element factory for XHTML. x('a', td, '3', href='#v3')."""
    el = etree.Element(q(tag)) if parent is None else etree.SubElement(parent, q(tag))
    for k, v in attrs.items():
        el.set(k.rstrip("_"), v)  # class_ -> class
    if text is not None:
        el.text = text
    return el


def grid_table(cells: list[tuple[str, str]], columns: int) -> etree._Element:
    """
    Build the list of links: [(text, href), ...].

    NAV_LAYOUT = "inline" (default): one paragraph "1 · 2 · 3 ..." that wraps like
        normal text. This is what Kindle handles well.
    NAV_LAYOUT = "table": a <table> with `columns` cells per row. Looks tidier in a
        browser, but Kindle treats every table as a special block (it may show it as
        a thumbnail you must tap, and big tables can freeze the device).
    """
    if NAV_LAYOUT == "table":
        table = x("table", class_=f"{PREFIX}-grid")
        table.text = "\n"
        for start in range(0, len(cells), columns):
            tr = x("tr", table)
            tr.tail = "\n"
            for text, href in cells[start : start + columns]:
                td = x("td", tr)
                x("a", td, text, href=href)
        return table

    p = x("p", class_=f"{PREFIX}-links")
    for i, (text, href) in enumerate(cells):
        a = x("a", p, text, href=href)
        if i < len(cells) - 1:
            a.tail = NAV_SEPARATOR
    return p


# ---------------------------------------------------------------------------
# 1. Load and clean
# ---------------------------------------------------------------------------
def load_bible(root_dir: Path) -> Bible:
    pkg = load_package(root_dir)
    docs: dict[Path, etree._ElementTree] = {}
    for item in pkg.spine_items():
        if item.media_type == "application/xhtml+xml" and item.href != INDEX_HREF:
            docs[pkg.item_path(item).resolve()] = parse_xml_file(pkg.item_path(item))
    return Bible(pkg=pkg, docs=docs)


def remove_previous_run(bible: Bible) -> None:
    """Remove tables/links inserted by an earlier run, plus the generated index page."""
    for tree in bible.docs.values():
        for el in [e for e in tree.iter() if isinstance(e.tag, str) and is_generated(e)]:
            parent = el.getparent()
            if parent is not None:
                if el.tail and el.tail.strip():
                    prev = el.getprevious()
                    if prev is not None:
                        prev.tail = (prev.tail or "") + el.tail
                    else:
                        parent.text = (parent.text or "") + el.tail
                parent.remove(el)
    for item in list(bible.pkg.manifest.values()):
        if item.href == INDEX_HREF:
            bible.pkg.remove_manifest_item(item.id)
            bible.pkg.item_path(item).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 2. Find books and testament dividers
# ---------------------------------------------------------------------------
def first_headings(tree, limit: int = 3) -> list[etree._Element]:
    found = []
    for el in tree.getroot().iter():
        if local_name(el) in ("h1", "h2", "h3"):
            found.append(el)
            if len(found) == limit:
                break
    return found


def count_verses(tree) -> int:
    return sum(1 for sup in tree.iter(q("sup")) if is_verse_sup(sup))


def is_continuation(tree) -> bool:
    """
    A file without a book heading continues the previous book when it has a real
    amount of verses and does not look like a notes page ("Notas de ...").
    """
    headings = first_headings(tree, limit=1)
    if headings and NOTES_LABEL_RE.match(element_text(headings[0], skip_links=True)):
        return False
    return count_verses(tree) >= MIN_CONTINUATION_VERSES


SMALL_WORDS = {"de", "del", "la", "las", "los", "el", "y", "a", "al", "en"}


def display_name(text: str) -> str:
    """
    Book name as the Bible writes it. ALL-CAPS headings ("CANTAR DE LOS CANTARES")
    are converted to title case ("Cantar de los Cantares").
    """
    if text != text.upper():
        return text
    words = text.lower().split()
    return " ".join(
        w if (i > 0 and w in SMALL_WORDS) else w[:1].upper() + w[1:] for i, w in enumerate(words)
    )


def find_books(bible: Bible) -> None:
    current: Book | None = None
    previous_was_book = False
    for path, tree in bible.docs.items():
        book_heading, info = None, None
        for h in first_headings(tree):
            text = element_text(h, skip_links=True)
            info = lookup_book(text)
            if info:
                book_heading = h
                break
            testament = testament_of_heading(text)
            if testament and testament not in bible.dividers:
                bible.dividers[testament] = path
        if info is not None:
            if current is not None and current.info.key == info.key and previous_was_book:
                current.files.append(path)  # same book split in several files
            else:
                name = display_name(element_text(book_heading, skip_links=True)) if USE_SOURCE_BOOK_NAMES else info.name
                current = Book(info=info, files=[path], heading=book_heading, name=name)
                bible.books.append(current)
            previous_was_book = True
        elif previous_was_book and current is not None and is_continuation(tree):
            current.files.append(path)  # continuation file (e.g. SalmosII.xhtml)
        else:
            previous_was_book = False


# ---------------------------------------------------------------------------
# 3. Find chapters and verses inside each book
# ---------------------------------------------------------------------------
def chapter_from_heading(el) -> tuple[int, bool] | None:
    text = element_text(el, skip_links=True)
    m = CHAPTER_HEADING_RE.match(text)
    if m:
        return int(m.group(1)), False
    m = PSALM_HEADING_RE.match(text)
    if m:
        return int(m.group(1)), True
    return None


def chapter_from_inline(el) -> int | None:
    # Text without the <sup class="sigla"> abbreviation: "Gén1" -> "1".
    parts = [el.text or ""]
    for child in el:
        if not (classes(child) & NON_VERSE_SUP_CLASSES):
            parts.append(element_text(child))
        parts.append(child.tail or "")
    m = re.search(r"(\d{1,3})\s*$", "".join(parts).strip())
    return int(m.group(1)) if m else None


def accept_chapter(bible: Bible, book: Book, chapter: Chapter) -> None:
    """
    Add a chapter unless it is obviously a mistake that fix_links.py could not
    repair: the same number as the current chapter (a duplicate heading). Gaps and
    jumps are accepted but reported, so nothing silently disappears.
    """
    if book.chapters:
        current = book.chapters[-1].number
        if chapter.number == current:
            bible.warnings.append(f"{book.name}: repeated heading for chapter {current} ignored")
            return
        if chapter.number != current + 1:
            bible.warnings.append(
                f"{book.name}: chapter {chapter.number} follows chapter {current} "
                f"({chapter.path.name}) — check the source"
            )
    book.chapters.append(chapter)


def find_chapters(bible: Bible, book: Book) -> None:
    orphan_verses: list[tuple[Path, Verse]] = []  # verses before the first chapter marker
    psalms = book.info.key == "sal"
    for path in book.files:
        for el in bible.docs[path].getroot().iter():
            if not isinstance(el.tag, str) or el is book.heading:
                continue
            tag = local_name(el)
            new_chapter = None
            if tag in HEADING_TAGS and tag != "h1":
                found = chapter_from_heading(el)
                if found:
                    number, is_psalm_label = found
                    new_chapter = Chapter(number, path, el, insert_after=True,
                                          is_psalm=psalms or is_psalm_label)
            elif classes(el) & INLINE_CHAPTER_CLASSES:
                number = chapter_from_inline(el)
                if number is not None:
                    new_chapter = Chapter(number, path, block_of(el), insert_after=False,
                                          is_psalm=psalms)
            elif tag == "sup" and is_verse_sup(el):
                verse = Verse((el.text or "").strip().replace("–", "-").replace(" ", ""), el)
                if book.chapters:
                    book.chapters[-1].verses.append(verse)
                else:
                    orphan_verses.append((path, verse))
            if new_chapter is not None:
                accept_chapter(bible, book, new_chapter)

    if not book.chapters and orphan_verses:
        # One-chapter book without markers (Abdías, Filemón, Judas ...).
        path, first = orphan_verses[0]
        chapter = Chapter(1, path, block_of(first.element), insert_after=False, is_psalm=psalms)
        chapter.verses = [v for _, v in orphan_verses]
        book.chapters.append(chapter)
    elif orphan_verses:
        bible.warnings.append(
            f"{book.name}: {len(orphan_verses)} verse number(s) before the first chapter were ignored"
        )

    count = len(book.chapters)
    if count not in book.info.chapters:
        bible.warnings.append(
            f"{book.name}: found {count} chapters (expected {' or '.join(map(str, book.info.chapters))})"
        )


# ---------------------------------------------------------------------------
# 4. Anchors and tables inside the book files
# ---------------------------------------------------------------------------
def used_ids(tree) -> set[str]:
    return {el.get("id") for el in tree.iter() if isinstance(el.tag, str) and el.get("id")}


def add_anchors(bible: Bible, book: Book) -> None:
    ids_by_file = {p: used_ids(bible.docs[p]) for p in book.files}
    book.anchor = ensure_id(book.heading, f"{PREFIX}-{book.info.key}", ids_by_file[book.first_file])
    for ch in book.chapters:
        ids = ids_by_file[ch.path]
        if ch.insert_after or not ch.verses or not ADD_VERSE_LISTS:
            # Heading markers: the heading itself is the jump target.
            ch.anchor = ensure_id(ch.marker, f"{PREFIX}-c{ch.number}", ids)
        else:
            # Inline markers (chapter number inside the first paragraph): the verse
            # table goes BEFORE that paragraph, so the table itself is the target;
            # otherwise jumping to the chapter would hide its table above the screen.
            ch.anchor = unique_id(f"{PREFIX}-c{ch.number}", ids)
        for v in ch.verses if ADD_VERSE_LISTS else []:
            first_num = v.label.split("-")[0]
            # A verse can be in a later file than its chapter start (rare); use its own file ids.
            file_ids = ids_by_file[file_of(bible, v.element)]
            v.anchor = ensure_id(v.element, f"{PREFIX}-c{ch.number}v{first_num}", file_ids)


def file_of(bible: Bible, el) -> Path:
    """The file an element belongs to (compares the root <html> element of each doc)."""
    root = el.getroottree().getroot()
    return next(p for p, t in bible.docs.items() if t.getroot() is root)


def insert_chapter_grid(bible: Bible, book: Book) -> None:
    if len(book.chapters) < 2:
        return
    cells = [(str(ch.number), relative_href(book.first_file, ch.path, ch.anchor)) for ch in book.chapters]
    div = x("div", class_=f"{PREFIX}-chapters")
    div.append(grid_table(cells, CHAPTER_COLUMNS))
    div.tail = "\n"
    book.heading.addnext(div)


def insert_verse_tables(bible: Bible, book: Book) -> None:
    back_href_target = book.first_file
    for ch in book.chapters:
        ch.start = ch.marker
        if not ch.verses or not ADD_VERSE_LISTS:
            continue
        cells = []
        for v in ch.verses:
            v_path = file_of(bible, v.element)
            cells.append((v.label, relative_href(ch.path, v_path, v.anchor)))
        div = x("div", class_=f"{PREFIX}-verses")
        if not ch.insert_after:
            div.set("id", ch.anchor)  # see add_anchors()
        div.text = "\n"
        div.append(grid_table(cells, VERSE_COLUMNS))
        if len(book.chapters) > 1:
            back = x("p", div, class_=f"{PREFIX}-back")
            x("a", back, LABEL_BACK_TO_CHAPTERS.format(book=book.name),
              href=relative_href(ch.path, back_href_target, book.anchor))
        div.tail = "\n"
        if ch.insert_after:
            ch.marker.addnext(div)
        else:
            ch.marker.addprevious(div)
            ch.start = div  # the list now opens the chapter


def link_stylesheet(bible: Bible, paths: list[Path]) -> None:
    css_path = bible.pkg.opf_dir / CSS_HREF
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text(CSS_CONTENT, encoding="utf-8")
    if not any(i.href == CSS_HREF for i in bible.pkg.manifest.values()):
        bible.pkg.add_manifest_item(f"{PREFIX}.css", CSS_HREF, "text/css")
    for path in paths:
        head = bible.docs[path].getroot().find(q("head"))
        href = relative_href(path, css_path.resolve())
        if any(l.get("href") == href for l in head.iter(q("link"))):
            continue
        link = x("link", head, href=href, rel="stylesheet", type="text/css")
        link.tail = "\n"


# ---------------------------------------------------------------------------
# 4b. Split big files at chapter boundaries
# ---------------------------------------------------------------------------
def body_child_of(el, body) -> etree._Element:
    """The direct child of <body> that contains el (or el itself)."""
    node = el
    while node.getparent() is not None and node.getparent() is not body:
        node = node.getparent()
    return node


def split_large_files(bible: Bible) -> int:
    """
    Cut every book file bigger than SPLIT_MAX_BYTES into parts, each part holding
    whole chapters. The first part keeps the original file name (so links to the
    book still work); the others are named '<name>-bnav2.xhtml', '-bnav3', ...
    Afterwards every link in the book that pointed to a moved element is fixed.
    Returns the number of new files.
    """
    pkg = bible.pkg
    origin: dict[Path, Path] = {}  # new part -> original file
    moved: dict[tuple[Path, str], Path] = {}  # (original file, id) -> new part
    spine_order = list(bible.docs)

    for book in bible.books:
        new_files: list[Path] = []
        for path in book.files:
            root = bible.docs[path].getroot()
            body = root.find(q("body"))
            chapters = [ch for ch in book.chapters if ch.path == path and ch.start is not None]
            too_small = len(etree.tostring(root)) <= SPLIT_MAX_BYTES and not CHAPTER_PER_FILE
            if too_small or len(chapters) < 2:
                new_files.append(path)
                continue

            children = list(body)
            position = {id(c): i for i, c in enumerate(children)}
            starts = [position[id(body_child_of(ch.start, body))] for ch in chapters]
            starts[0] = 0  # the first part also keeps the book title and introduction
            sizes = [len(etree.tostring(c)) for c in children]

            # Greedy packing: consecutive chapters go together until the limit.
            groups: list[list[int]] = [[0]]  # lists of chapter indexes
            current = sum(sizes[starts[0] : starts[1] if len(starts) > 1 else len(children)])
            for i in range(1, len(chapters)):
                end = starts[i + 1] if i + 1 < len(starts) else len(children)
                block = sum(sizes[starts[i] : end])
                if CHAPTER_PER_FILE or current + block > SPLIT_MAX_BYTES:
                    groups.append([i])
                    current = block
                else:
                    groups[-1].append(i)
                    current += block

            new_files.append(path)
            previous_part = path
            for part_no, group in enumerate(groups[1:], start=2):
                first, last = group[0], group[-1]
                end = starts[last + 1] if last + 1 < len(starts) else len(children)
                part_path = path.with_name(f"{path.stem}-{PREFIX}{part_no}{path.suffix}")
                # New document: same <html>/<head>, empty <body> with the same attributes.
                part_root = etree.Element(root.tag, nsmap=root.nsmap, attrib=dict(root.attrib))
                part_root.text = root.text
                part_root.append(copy.deepcopy(root.find(q("head"))))
                part_body = etree.SubElement(part_root, q("body"), attrib=dict(body.attrib))
                part_body.text = "\n"
                for child in children[starts[first] : end]:
                    part_body.append(child)  # append() MOVES the element
                    for el in child.iter():
                        if isinstance(el.tag, str) and el.get("id"):
                            moved[(path, el.get("id"))] = part_path
                for i in group:
                    chapters[i].path = part_path
                chapters[first].starts_file = True  # it is the first thing in the new file
                bible.docs[part_path] = etree.ElementTree(part_root)
                origin[part_path] = path
                new_files.append(part_path)

                # Manifest + spine (right after the previous part).
                href = pkg.href_of_path(part_path)
                item_id = re.sub(r"[^A-Za-z0-9._-]", "_", part_path.name)
                if not item_id[0].isalpha():
                    item_id = "x" + item_id
                pkg.add_manifest_item(item_id, href, "application/xhtml+xml")
                prev_id = next(i.id for i in pkg.manifest.values() if pkg.item_path(i).resolve() == previous_part)
                for ref in pkg.spine_el():
                    if ref.get("idref") == prev_id:
                        new_ref = etree.Element(q("itemref", OPF_NS), idref=item_id)
                        new_ref.tail = ref.tail
                        ref.addnext(new_ref)
                        break
                spine_order.insert(spine_order.index(previous_part) + 1, part_path)
                previous_part = part_path
        book.files = new_files

    if not origin:
        return 0
    pkg.spine_ids = [r.get("idref") for r in pkg.spine_el()]
    bible.docs = {p: bible.docs[p] for p in spine_order}

    # Fix every link that pointed to a moved element. Links that were written inside
    # a moved part are resolved against the ORIGINAL file (where they were written).
    for path, tree in bible.docs.items():
        base = origin.get(path, path)
        for a in tree.iter(q("a")):
            href = a.get("href")
            if not href or is_external(href):
                continue
            target, frag = resolve_href(base, href)
            target = target.resolve()
            new_target = moved.get((target, frag), target)
            new_href = relative_href(path, new_target, frag)
            if new_href != href:
                a.set("href", new_href)
    return len(origin)


# ---------------------------------------------------------------------------
# 5. HTML index page
# ---------------------------------------------------------------------------
def split_testaments(bible: Bible) -> list[tuple[str | None, list[Book]]]:
    """[('AT', books), ('NT', books)] or [(None, books)] when only one testament exists."""
    at = [b for b in bible.books if b.info.testament == "AT"]
    nt = [b for b in bible.books if b.info.testament == "NT"]
    if at and nt:
        return [("AT", at), ("NT", nt)]
    return [(None, bible.books)]


def testament_label(code: str) -> str:
    return LABEL_OLD_TESTAMENT if code == "AT" else LABEL_NEW_TESTAMENT


def create_index_page(bible: Bible) -> Path:
    pkg = bible.pkg
    path = (pkg.opf_dir / INDEX_HREF).resolve()
    html = etree.Element(q("html"), nsmap={None: "http://www.w3.org/1999/xhtml"})
    html.set("{http://www.w3.org/XML/1998/namespace}lang", pkg.language())
    head = x("head", html)
    x("title", head, LABEL_INDEX)
    x("link", head, href=relative_href(path, (pkg.opf_dir / CSS_HREF).resolve()),
      rel="stylesheet", type="text/css")
    body = x("body", html)
    body.text = "\n"
    x("h1", body, LABEL_INDEX, class_=f"{PREFIX}-title", id=f"{PREFIX}-indice").tail = "\n"
    for code, books in split_testaments(bible):
        if code:
            target = bible.dividers.get(code)
            h2 = x("h2", body, class_=f"{PREFIX}-testament")
            if target:
                x("a", h2, testament_label(code), href=relative_href(path, target))
            else:
                h2.text = testament_label(code)
            h2.tail = "\n"
        for book in books:
            p = x("p", body, class_=f"{PREFIX}-book")
            x("a", p, book.name, href=relative_href(path, book.first_file, book.anchor))
            p.tail = "\n"
    tree = etree.ElementTree(html)
    write_xhtml_file(path, tree)

    # Manifest, spine (just before the first Bible content) and guide.
    item = pkg.add_manifest_item(f"{PREFIX}-indice.xhtml", INDEX_HREF, "application/xhtml+xml")
    first_content = region_bounds(bible)[0]
    spine = pkg.spine_el()
    first_idref = next(i.id for i in pkg.spine_items() if pkg.item_path(i).resolve() == first_content)
    for ref in spine:
        if ref.get("idref") == first_idref:
            new_ref = etree.Element(q("itemref", OPF_NS), idref=item.id)
            new_ref.tail = ref.tail
            ref.addprevious(new_ref)
            break
    pkg.spine_ids = [r.get("idref") for r in spine]
    set_guide_toc(pkg, INDEX_HREF)
    return path


def set_guide_toc(pkg: EpubPackage, href: str) -> None:
    guide = pkg.guide_el()
    if guide is None:
        guide = etree.SubElement(pkg.opf_tree.getroot(), q("guide", OPF_NS))
    for ref in list(guide):
        if isinstance(ref.tag, str) and ref.get("type") == "toc":
            guide.remove(ref)
    ref = etree.SubElement(guide, q("reference", OPF_NS), type="toc", title=LABEL_INDEX, href=href)
    ref.tail = "\n  "


def remove_old_html_toc(bible: Bible) -> list[Path]:
    """
    Remove a previous HTML table of contents (Sigil's TOC.xhtml, recognised by its
    'sgc-toc' classes). Returns the removed paths so NCX entries to them are dropped.
    """
    removed = []
    pkg = bible.pkg
    for item in list(pkg.xhtml_items()):
        path = pkg.item_path(item).resolve()
        tree = bible.docs.get(path)
        if tree is None:
            continue
        if any(c.startswith("sgc-toc") for el in tree.iter() if isinstance(el.tag, str) for c in classes(el)):
            pkg.remove_manifest_item(item.id)
            path.unlink(missing_ok=True)
            del bible.docs[path]
            guide = pkg.guide_el()
            if guide is not None:
                for ref in list(guide):
                    if isinstance(ref.tag, str) and resolve_href(pkg.opf_path, ref.get("href", ""))[0].resolve() == path:
                        guide.remove(ref)
            removed.append(path)
    return removed


# ---------------------------------------------------------------------------
# 6. NCX
# ---------------------------------------------------------------------------
def region_bounds(bible: Bible) -> tuple[Path, Path]:
    """First and last spine document that belongs to the Bible text (dividers + books)."""
    spine = bible.spine_paths()
    paths = [p for b in bible.books for p in b.files] + list(bible.dividers.values())
    indexes = [spine.index(p) for p in paths if p in spine]
    return spine[min(indexes)], spine[max(indexes)]


class NcxBuilder:
    """Creates <navPoint> elements; playOrder is assigned at the end in document order."""

    def __init__(self, ncx_path: Path) -> None:
        self.ncx_path = ncx_path
        self.counter = 0

    def nav_point(self, parent, label: str, target: Path, fragment: str = "") -> etree._Element:
        self.counter += 1
        np_ = etree.SubElement(parent, q("navPoint", NCX_NS), id=f"{PREFIX}-np{self.counter}")
        nav_label = etree.SubElement(np_, q("navLabel", NCX_NS))
        etree.SubElement(nav_label, q("text", NCX_NS)).text = label
        etree.SubElement(np_, q("content", NCX_NS), src=relative_href(self.ncx_path, target, fragment))
        return np_


def ncx_target(ncx_path: Path, nav_point) -> Path:
    content = nav_point.find(q("content", NCX_NS))
    return resolve_href(ncx_path, content.get("src", ""))[0].resolve()


def ncx_label(nav_point) -> str:
    text = nav_point.find(f"{q('navLabel', NCX_NS)}/{q('text', NCX_NS)}")
    return (text.text or "").strip() if text is not None else ""


def rebuild_ncx(bible: Bible, index_page: Path | None, removed: list[Path]) -> None:
    pkg = bible.pkg
    ncx_item = pkg.ncx_item()
    ncx_path = pkg.item_path(ncx_item).resolve()
    tree = parse_xml_file(ncx_path)
    nav_map = tree.find(q("navMap", NCX_NS))
    old_top = [np_ for np_ in nav_map if local_name(np_) == "navPoint"]

    # Undo what a previous run of this script added at the top level, so running the
    # script twice gives the same result: the "Notas" group is unwrapped back into its
    # children and the old "Índice" entry is dropped (a new one is created below).
    index_path = (pkg.opf_dir / INDEX_HREF).resolve()
    unwrapped = []
    for np_ in old_top:
        if np_.get("id") == f"{PREFIX}-notes":
            unwrapped.extend(np_.findall(q("navPoint", NCX_NS)))
        elif ncx_target(ncx_path, np_) != index_path:
            unwrapped.append(np_)
    for np_ in old_top:
        nav_map.remove(np_)
    for np_ in unwrapped:
        nav_map.append(np_)
    old_top = unwrapped

    spine = bible.spine_paths()
    first, last = region_bounds(bible)
    start, end = spine.index(first), spine.index(last)
    book_files = {p for b in bible.books for p in b.files}

    # Labels the old NCX gave to whole files (used for intro pages inside the Bible).
    old_labels: dict[Path, str] = {}
    for np_ in nav_map.iter(q("navPoint", NCX_NS)):
        src = np_.find(q("content", NCX_NS)).get("src", "")
        if "#" not in src:
            old_labels.setdefault(ncx_target(ncx_path, np_), ncx_label(np_))

    def position(np_) -> int:
        target = ncx_target(ncx_path, np_)
        return spine.index(target) if target in spine else -1

    front = [np_ for np_ in old_top if 0 <= position(np_) < start and ncx_target(ncx_path, np_) not in removed]
    back = [np_ for np_ in old_top if position(np_) > end or position(np_) == -1 and ncx_target(ncx_path, np_) not in removed]
    back = [np_ for np_ in back if ncx_target(ncx_path, np_) not in removed]

    # Empty the navMap and rebuild it.
    for np_ in old_top:
        nav_map.remove(np_)
    builder = NcxBuilder(ncx_path)
    for np_ in front:
        nav_map.append(np_)
    if index_page is not None:
        builder.nav_point(nav_map, LABEL_INDEX, index_page)

    groups = split_testaments(bible)
    books_by_first_file = {b.first_file: b for b in bible.books}
    for code, books in groups:
        if code:
            target = bible.dividers.get(code) or books[0].first_file
            testament_np = builder.nav_point(nav_map, testament_label(code), target)
            # See TESTAMENTS_AS_PARENTS: nest the books inside the testament, or not.
            parent = testament_np if TESTAMENTS_AS_PARENTS else nav_map
        else:
            parent = nav_map
        wanted = {p for b in books for p in b.files}
        divider_files = set(bible.dividers.values())
        for path in spine[start : end + 1]:
            if path in books_by_first_file and path in wanted:
                book = books_by_first_file[path]
                book_np = builder.nav_point(parent, book.name, book.first_file, book.anchor)
                if len(book.chapters) > 1:
                    for ch in book.chapters:
                        # A chapter that opens its own file is linked without "#anchor",
                        # the way ordinary books link their chapters.
                        builder.nav_point(book_np, ch.label, ch.path, "" if ch.starts_file else ch.anchor)
            elif path not in book_files and path not in divider_files and path in old_labels:
                # Introductions and similar pages between books stay in their testament.
                in_this_testament = code is None or _testament_at(bible, spine, path) == code
                if in_this_testament:
                    builder.nav_point(parent, old_labels[path], path)

    if GROUP_NOTES_IN_NCX:
        back = group_notes(back, builder, nav_map, ncx_path)
    for np_ in back:
        nav_map.append(np_)

    # Indentation for readability, then sequential playOrder and real depth.
    etree.indent(nav_map, space="  ", level=1)
    assign_play_order(nav_map)

    def depth(el, level=0):
        kids = el.findall(q("navPoint", NCX_NS))
        return max([depth(k, level + 1) for k in kids], default=level)

    for meta in tree.iter(q("meta", NCX_NS)):
        if meta.get("name") == "dtb:depth":
            meta.set("content", str(depth(nav_map)))
    write_xml_file(
        ncx_path,
        tree,
        '<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN"\n'
        '   "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">',
    )


def _testament_at(bible: Bible, spine: list[Path], path: Path) -> str | None:
    """Testament of a non-book page = testament of the next book after it in the spine."""
    idx = spine.index(path)
    for book in bible.books:
        if spine.index(book.first_file) > idx:
            return book.info.testament
    return bible.books[-1].info.testament if bible.books else None


def group_notes(back: list, builder: NcxBuilder, nav_map, ncx_path: Path) -> list:
    """Put 3+ consecutive top-level 'Notas de ...' entries under a single 'Notas' entry."""
    result, run = [], []

    def flush():
        if len(run) >= 3:
            parent = etree.Element(q("navPoint", NCX_NS), id=f"{PREFIX}-notes")
            label = etree.SubElement(parent, q("navLabel", NCX_NS))
            etree.SubElement(label, q("text", NCX_NS)).text = LABEL_NOTES_GROUP
            content = run[0].find(q("content", NCX_NS))
            etree.SubElement(parent, q("content", NCX_NS), src=content.get("src"))
            for np_ in run:
                parent.append(np_)
            result.append(parent)
        else:
            result.extend(run)
        run.clear()

    for np_ in back:
        if NOTES_LABEL_RE.match(ncx_label(np_)) and len(np_.findall(q("navPoint", NCX_NS))) == 0:
            run.append(np_)
        else:
            flush()
            result.append(np_)
    flush()
    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def build_navigation(epub_path: Path, output_dir: Path = OUTPUT_DIR, work_dir: Path = WORK_DIR) -> Path:
    epub_path = Path(epub_path)
    stem = epub_path.stem.replace(OUTPUT_SUFFIX, "")
    out_path = Path(output_dir) / f"{stem}{OUTPUT_SUFFIX}.epub"
    unpacked = unpack_epub(epub_path, Path(work_dir) / f"{stem}{OUTPUT_SUFFIX}")

    bible = load_bible(unpacked)
    remove_previous_run(bible)
    find_books(bible)
    if not bible.books:
        sys.exit("No Bible books recognised. Check the book names in epub_common.BOOKS.")

    for book in bible.books:
        find_chapters(bible, book)
        add_anchors(bible, book)
        insert_chapter_grid(bible, book)
        insert_verse_tables(bible, book)

    link_stylesheet(bible, [p for b in bible.books for p in b.files])
    new_parts = split_large_files(bible) if SPLIT_LARGE_FILES else 0
    removed = remove_old_html_toc(bible) if REMOVE_OLD_HTML_TOC else []
    # Write every document: splitting may have changed links in any of them (notes...).
    for path, tree in bible.docs.items():
        write_xhtml_file(path, tree)
    index_page = create_index_page(bible) if CREATE_HTML_INDEX else None
    rebuild_ncx(bible, index_page, removed)
    bible.pkg.save_opf()
    pack_epub(unpacked, out_path)

    # Report
    total_ch = sum(len(b.chapters) for b in bible.books)
    total_v = sum(len(c.verses) for b in bible.books for c in b.chapters)
    split = " / ".join(f"{testament_label(c)}: {len(bs)}" for c, bs in split_testaments(bible) if c)
    print(f"[build_navigation] {epub_path.name}")
    print(f"  books: {len(bible.books)} ({split or 'single testament'}), chapters: {total_ch}, verses: {total_v}")
    if new_parts:
        biggest = max(len(etree.tostring(t.getroot())) for t in bible.docs.values())
        print(f"  big files split: {new_parts} new files (largest file now {biggest // 1000} KB)")
    for w in bible.warnings:
        print(f"  ! {w}")
    print(f"  -> {out_path}")
    return out_path


if __name__ == "__main__":
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else BIBLE_PATH
    if not source.exists():
        sys.exit(f"EPUB not found: {source}\nEdit BIBLE_PATH at the top of {Path(__file__).name}.")
    build_navigation(source)

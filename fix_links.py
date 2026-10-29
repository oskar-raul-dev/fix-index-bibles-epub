"""
fix_links.py
============

Step 1 of 2. Repairs links and other technical problems in a Bible EPUB so that
it opens cleanly everywhere (Kindle / Send to Kindle, Apple Books, Calibre...).

How to use
----------
1. Change BIBLE_PATH below to the .epub you want to repair (or pass the path as
   the first command line argument, which overrides the constant).
2. Run:  python fix_links.py
3. The repaired copy is written to OUTPUT_DIR with the suffix " [fixed]".
   The original file is NEVER modified.

What it fixes (each step is a function below, in this order)
-------------------------------------------------------------
1. fix_entities            HTML named entities (&nbsp; ...) -> numeric (&#160;).
                           They are invalid in XHTML and break strict parsers.
2. fix_manifest            Manifest entries whose file does not exist are removed;
                           files that exist but are not declared are added.
3. fix_duplicate_ids       Two elements with the same id in one file: later ones
                           are renamed (links can only point to one of them).
4. fix_chapter_markup      Wrong chapter headings found in these Bibles:
                           a) a verse number typed as a chapter heading
                              (<h2>18</h2><p><sup>1</sup>... in the middle of
                              Genesis 49) -> turned back into verse 18;
                           b) an empty verse plus a stray heading "1";
                           c) the same chapter included twice with identical
                              text -> the second copy is removed.
                           Anything else that looks odd is only reported.
5. fix_broken_links        <a href> pointing to a missing file or a missing anchor.
                           Tries, in order: case-insensitive file/anchor match,
                           repairing a footnote "back" link, pointing to the file
                           without the anchor, and as a last resort removing the
                           link (the text stays).
6. fix_note_round_trips    A footnote reference (verse -> note) whose "<<" back
                           link points somewhere else is corrected.
7. fix_titles_and_lang     Empty <title> and missing xml:lang attributes.
8. fix_ncx                 NCX (the Kindle "Go to" table of contents): broken
                           targets, sequential playOrder, unique ids, real depth.
9. fix_opf                 Spine/guide entries that point to missing items.

Every change is printed in a short report at the end.
"""

from __future__ import annotations

import mimetypes
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

from lxml import etree

from bibles_config import INPUT_DIR, OUTPUT_DIR, WORK_DIR
from epub_common import (
    CHAPTER_HEADING_RE,
    HEADING_TAGS,
    NCX_NS,
    OPF_NS,
    XHTML_NS,
    assign_play_order,
    EpubPackage,
    element_text,
    is_external,
    is_verse_sup,
    load_package,
    local_name,
    pack_epub,
    parse_xml_file,
    q,
    relative_href,
    remove_keep_tail,
    replace_html_entities,
    resolve_href,
    unpack_epub,
    verse_number,
    write_xhtml_file,
    write_xml_file,
)

# ---------------------------------------------------------------------------
# Configuration — change these to your needs
# ---------------------------------------------------------------------------
# Folders come from bibles_config.py (INPUT_DIR can be changed with BIBLE_INPUT_DIR).
# OUTPUT_DIR: where the repaired EPUB is written.
# WORK_DIR:   where the EPUB is unzipped while working (kept for inspection).

# The EPUB to repair. By default: the first Bible in the input folder.
BIBLE_PATH = INPUT_DIR / "[Biblias 01] La Biblia de las Americas [10343] (r1.4).epub"

# Suffix appended to the output file name.
OUTPUT_SUFFIX = " [fixed]"

XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


# ---------------------------------------------------------------------------
# Small report object: collects messages per category
# ---------------------------------------------------------------------------
class Report:
    def __init__(self) -> None:
        self.items: dict[str, list[str]] = defaultdict(list)

    def add(self, category: str, message: str) -> None:
        self.items[category].append(message)

    def print(self, max_examples: int = 5) -> None:
        if not self.items:
            print("  Nothing to fix.")
            return
        for category, messages in self.items.items():
            print(f"  - {category}: {len(messages)}")
            for m in messages[:max_examples]:
                print(f"      {m}")
            if len(messages) > max_examples:
                print(f"      ... ({len(messages) - max_examples} more)")


# ---------------------------------------------------------------------------
# A loaded EPUB with all XHTML documents parsed in memory
# ---------------------------------------------------------------------------
class Book:
    """
    Holds the package plus every XHTML document parsed, and an index of ids.
    Paths are always normalised absolute paths so they can be compared.
    """

    def __init__(self, pkg: EpubPackage) -> None:
        self.pkg = pkg
        self.docs: dict[Path, etree._ElementTree] = {}
        self.dirty: set[Path] = set()  # documents modified -> must be saved
        for item in pkg.xhtml_items():
            path = norm(pkg.item_path(item))
            if path.exists():
                self.docs[path] = parse_xml_file(path)
        self.ids: dict[Path, dict[str, etree._Element]] = {}
        self.rebuild_ids()

    def rebuild_ids(self) -> None:
        self.ids = {}
        for path, tree in self.docs.items():
            table: dict[str, etree._Element] = {}
            for el in tree.iter():
                if isinstance(el.tag, str) and el.get("id") and el.get("id") not in table:
                    table[el.get("id")] = el
            self.ids[path] = table

    def links(self):
        """Yield (path, <a> element) for every link with an href in every document."""
        for path, tree in self.docs.items():
            for a in tree.iter(q("a")):
                if a.get("href"):
                    yield path, a

    def save(self) -> None:
        for path in self.dirty:
            write_xhtml_file(path, self.docs[path])


def norm(path: Path) -> Path:
    return Path(os.path.normpath(path))


# ---------------------------------------------------------------------------
# Step 1 — entities (works on raw text, before parsing)
# ---------------------------------------------------------------------------
def fix_entities(root_dir: Path, report: Report) -> None:
    for path in sorted(root_dir.rglob("*")):
        if path.suffix.lower() not in (".xhtml", ".html", ".htm", ".ncx", ".opf", ".xml"):
            continue
        text = path.read_text(encoding="utf-8")
        new_text, count = replace_html_entities(text)
        if count:
            path.write_text(new_text, encoding="utf-8")
            report.add("Files with HTML entities replaced", f"{path.name}: {count} entities")


# ---------------------------------------------------------------------------
# Step 2 — manifest vs. files on disk
# ---------------------------------------------------------------------------
def fix_manifest(pkg: EpubPackage, report: Report) -> None:
    # 2a. Entries whose file is missing.
    for item in list(pkg.manifest.values()):
        if not pkg.item_path(item).exists():
            pkg.remove_manifest_item(item.id)
            report.add("Manifest items removed (file missing)", item.href)

    # 2b. Content files present on disk but not declared in the manifest.
    declared = {norm(pkg.item_path(i)) for i in pkg.manifest.values()}
    for path in sorted(pkg.opf_dir.rglob("*")):
        if not path.is_file() or path == pkg.opf_path or norm(path) in declared:
            continue
        if path.name in (".DS_Store",) or "META-INF" in path.parts:
            continue
        media_type = {
            ".xhtml": "application/xhtml+xml",
            ".ncx": "application/x-dtbncx+xml",
            ".css": "text/css",
        }.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0]
        if not media_type:
            continue
        href = pkg.href_of_path(path)
        item_id = re.sub(r"[^A-Za-z0-9._-]", "_", path.name)
        if not item_id[0].isalpha():
            item_id = "x" + item_id
        while item_id in pkg.manifest:
            item_id += "_"
        pkg.add_manifest_item(item_id, href, media_type)
        report.add("Manifest items added (file not declared)", href)


# ---------------------------------------------------------------------------
# Step 3 — duplicate ids inside one document
# ---------------------------------------------------------------------------
def fix_duplicate_ids(book: Book, report: Report) -> None:
    for path, tree in book.docs.items():
        seen: dict[str, int] = {}
        for el in tree.iter():
            if not isinstance(el.tag, str) or not el.get("id"):
                continue
            ident = el.get("id")
            if ident in seen:
                seen[ident] += 1
                new_id = f"{ident}-dup{seen[ident]}"
                el.set("id", new_id)
                book.dirty.add(path)
                report.add("Duplicate ids renamed", f"{path.name}: {ident} -> {new_id}")
            else:
                seen[ident] = 1
    book.rebuild_ids()


# ---------------------------------------------------------------------------
# Step 4 — chapter headings that are wrong in the source
# ---------------------------------------------------------------------------
def heading_chapter_number(el) -> int | None:
    """Number of a plain chapter heading (<h2>12</h2>, <h2>Capítulo 12</h2>), else None."""
    if local_name(el) not in HEADING_TAGS or local_name(el) == "h1":
        return None
    m = CHAPTER_HEADING_RE.match(element_text(el, skip_links=True))
    return int(m.group(1)) if m else None


def block_text(elements) -> str:
    """Text of a list of elements, ignoring footnote markers (used to spot duplicates)."""
    return " ".join(element_text(e, skip_links=True) for e in elements)


def remove_notes_of(book: Book, path: Path, elements) -> int:
    """
    Before deleting a duplicated block, delete the footnotes that only the block
    referenced (otherwise they stay in the notes file with a broken "<<" link).
    Returns how many notes were removed.
    """
    removed = 0
    for container in elements:
        for a in container.iter(q("a")):
            href = a.get("href")
            if not href or is_external(href) or not a.get("id"):
                continue
            target, frag = resolve_href(path, href)
            target = norm(target)
            note = book.ids.get(target, {}).get(frag)
            if note is None:
                continue
            box = note if (len(note) or (note.text or "").strip()) else note.getparent()
            if box is not None and box.getparent() is not None:
                remove_keep_tail(box)
                book.dirty.add(target)
                removed += 1
    return removed


def fix_chapter_markup(book: Book, report: Report) -> None:
    for path, tree in book.docs.items():
        # Events in document order: ("H", heading, n) and ("V", sup, n).
        events = []
        for el in tree.getroot().iter():
            if not isinstance(el.tag, str):
                continue
            n = heading_chapter_number(el)
            if n is not None:
                events.append(("H", el, n))
            elif is_verse_sup(el):
                events.append(("V", el, verse_number(el)))
        headings = [i for i, e in enumerate(events) if e[0] == "H"]
        if len(headings) < 2:
            continue

        current = None  # number of the last accepted chapter heading
        current_el = None
        for pos, idx in enumerate(headings):
            _, el, n = events[idx]
            if current is None or n == current + 1:
                current, current_el = n, el
                continue
            # Number of the next chapter heading (None at the end of the file).
            nxt = events[headings[pos + 1]][2] if pos + 1 < len(headings) else None
            # "Fits" = the following heading does not continue from this one, i.e. this
            # heading is an isolated mistake, not the start of a real new numbering.
            next_fits = nxt is None or nxt == current + 1 or nxt != n + 1
            prev_verses = [e for e in events[headings[pos - 1] + 1 : idx] if e[0] == "V"]
            last_verse = prev_verses[-1][2] if prev_verses else None
            next_verse = next((e for e in events[idx + 1 :] if e[0] == "V"), None)
            where = f"{path.name}: chapter {current}, heading '{n}'"

            # a) A verse number typed as a heading: <h2>18</h2><p><sup>1</sup> ...
            if last_verse is not None and n == last_verse + 1 and next_fits:
                remove_keep_tail(el)
                if next_verse is not None and next_verse[2] == 1:
                    next_verse[1].text = str(n)
                report.add("Verse numbers that were tagged as chapter headings", where + f" -> verse {n}")
                book.dirty.add(path)
                continue

            # b) An empty verse "<p><sup>1</sup></p>" followed by a stray heading "1".
            prev = el.getprevious()
            if (
                n == 1
                and next_fits
                and prev is not None
                and local_name(prev) == "p"
                and not element_text(prev, skip_links=True).strip("0123456789 ")
                and len(prev) == 1
                and is_verse_sup(prev[0])
            ):
                remove_keep_tail(prev)
                remove_keep_tail(el)
                report.add("Stray chapter headings removed", where + " (with an empty verse)")
                book.dirty.add(path)
                continue

            # c) The same chapter twice in a row with identical text.
            if n == current and el.getparent() is current_el.getparent():
                first_block, second_block = [], []
                sib = current_el.getnext()
                while sib is not None and sib is not el:
                    first_block.append(sib)
                    sib = sib.getnext()
                sib = el.getnext()
                while sib is not None and heading_chapter_number(sib) is None:
                    second_block.append(sib)
                    sib = sib.getnext()
                if second_block and block_text(first_block) == block_text(second_block):
                    removed_notes = remove_notes_of(book, path, [el, *second_block])
                    for e in [el, *second_block]:
                        remove_keep_tail(e)
                    report.add(
                        "Duplicated chapters removed",
                        where + f" ({len(second_block)} paragraphs, {removed_notes} footnotes)",
                    )
                    book.dirty.add(path)
                    continue

            report.add("Suspicious chapter headings (not changed)", where)
            current, current_el = n, el


# ---------------------------------------------------------------------------
# Step 5 — broken links
# ---------------------------------------------------------------------------
def unwrap(el: etree._Element) -> None:
    """Remove an element but keep its text and children in place."""
    parent = el.getparent()
    index = parent.index(el)
    # Text of the element goes after the previous sibling (or into the parent text).
    text = (el.text or "")
    if index == 0:
        parent.text = (parent.text or "") + text
    else:
        prev = parent[index - 1]
        prev.tail = (prev.tail or "") + text
    # Move the children up one level.
    for offset, child in enumerate(list(el)):
        parent.insert(index + offset, child)
    # The element's tail goes after the last moved child (or the previous node).
    tail = el.tail or ""
    new_index = parent.index(el)
    if new_index == 0:
        parent.text = (parent.text or "") + tail
    else:
        prev = parent[new_index - 1]
        prev.tail = (prev.tail or "") + tail
    parent.remove(el)


def note_ids_around(a: etree._Element) -> set[str]:
    """
    The ids that identify the footnote a back link belongs to:
      * ids of the link's ancestors (<p id="notaa"> ... <a href="..">&lt;&lt;</a></p>)
      * ids of empty anchors in the same block (<p><a id="notaa"/> ... </p>)
    """
    ids: set[str] = set()
    for anc in a.iterancestors():
        if anc.get("id"):
            ids.add(anc.get("id"))
    parent = a.getparent()
    if parent is not None:
        for sib in parent.iter(q("a")):
            if sib.get("id") and not sib.get("href"):
                ids.add(sib.get("id"))
    return ids


def find_candidate_file(book: Book, wanted: Path) -> Path | None:
    """Case-insensitive match on the file name (Sigil sometimes renames files)."""
    matches = [p for p in book.docs if p.name.lower() == wanted.name.lower()]
    return matches[0] if len(matches) == 1 else None


def fix_broken_links(book: Book, report: Report) -> None:
    for path, a in list(book.links()):
        href = a.get("href")
        if is_external(href):
            continue
        target, frag = resolve_href(path, href)
        target = norm(target)

        # --- the target file does not exist --------------------------------------
        if target not in book.docs:
            if target.exists():  # a link to an image or other non-XHTML resource
                continue
            candidate = find_candidate_file(book, target)
            if candidate is not None:
                new_href = relative_href(path, candidate, frag)
                a.set("href", new_href)
                book.dirty.add(path)
                report.add("Links re-pointed to existing file", f"{path.name}: {href} -> {new_href}")
                target = candidate
            else:
                report.add("Links removed (target file missing)", f"{path.name}: {href}")
                unwrap(a)
                book.dirty.add(path)
                continue

        # --- the file exists but the anchor does not ------------------------------
        if frag and frag not in book.ids[target]:
            # a) Same id with different upper/lower case.
            ci = [i for i in book.ids[target] if i.lower() == frag.lower()]
            if len(ci) == 1:
                a.set("href", relative_href(path, target, ci[0]))
                book.dirty.add(path)
                report.add("Anchors fixed (case)", f"{path.name}: #{frag} -> #{ci[0]}")
                continue

            # b) A footnote back link: find the reference in the target file that
            #    points to this note and give it the missing id (or point to its id).
            note_ids = note_ids_around(a)
            ref = None
            for cand in book.docs[target].iter(q("a")):
                h = cand.get("href")
                if not h or is_external(h):
                    continue
                t2, f2 = resolve_href(target, h)
                if norm(t2) == path and f2 in note_ids:
                    ref = cand
                    break
            if ref is not None:
                if ref.get("id"):
                    a.set("href", relative_href(path, target, ref.get("id")))
                    book.dirty.add(path)
                else:
                    ref.set("id", frag)
                    book.ids[target][frag] = ref
                    book.dirty.add(target)
                report.add("Footnote back links repaired", f"{path.name}: {href}")
                continue

            # c) Point to the file itself (the reader at least lands on the right page).
            a.set("href", relative_href(path, target))
            book.dirty.add(path)
            report.add("Links without anchor (anchor missing)", f"{path.name}: {href}")


# ---------------------------------------------------------------------------
# Step 6 — footnote round trips (verse -> note -> back to the same verse)
# ---------------------------------------------------------------------------
def fix_note_round_trips(book: Book, report: Report) -> None:
    for path, fwd in list(book.links()):
        fwd_id = fwd.get("id")
        href = fwd.get("href")
        if not fwd_id or is_external(href):
            continue  # a footnote reference always carries its own id
        target, frag = resolve_href(path, href)
        target = norm(target)
        if target == path or target not in book.docs or not frag:
            continue
        note = book.ids[target].get(frag)
        if note is None:
            continue
        # The note "box": the element itself, or its parent when it is an empty anchor.
        box = note if (len(note) or (note.text or "").strip()) else note.getparent()
        back_links = [b for b in box.iter(q("a")) if b.get("href") and not is_external(b.get("href"))]
        if not back_links:
            continue
        resolved = [(b, *resolve_href(target, b.get("href"))) for b in back_links]
        if any(norm(t) == path and f == fwd_id for _, t, f in resolved):
            continue  # already correct
        # Only one back link and it is wrong: is it someone else's valid reference?
        if len(resolved) != 1:
            continue
        b, t, f = resolved[0]
        other = book.ids.get(norm(t), {}).get(f)
        if other is not None and local_name(other) == "a" and other.get("href"):
            t3, f3 = resolve_href(norm(t), other.get("href"))
            if norm(t3) == target and f3 == frag:
                continue  # shared note referenced from two places; leave it alone
        new_href = relative_href(target, path, fwd_id)
        report.add("Footnote back links corrected", f"{target.name}: {b.get('href')} -> {new_href}")
        b.set("href", new_href)
        book.dirty.add(target)


# ---------------------------------------------------------------------------
# Step 7 — <title> and xml:lang
# ---------------------------------------------------------------------------
def fix_titles_and_lang(book: Book, report: Report) -> None:
    lang = book.pkg.language()
    dc_title = book.pkg.opf_tree.find(f".//{{http://purl.org/dc/elements/1.1/}}title")
    book_title = (dc_title.text or "").strip() if dc_title is not None else ""
    for path, tree in book.docs.items():
        root = tree.getroot()
        if not root.get(XML_LANG):
            root.set(XML_LANG, lang)
            book.dirty.add(path)
            report.add("xml:lang added", path.name)
        title = root.find(f"{q('head')}/{q('title')}")
        if title is not None and not (title.text or "").strip():
            heading = next(
                (h for tag in ("h1", "h2", "h3") for h in root.iter(q(tag)) if element_text(h, True)),
                None,
            )
            # Pages without any heading (cover, credits...) get the book title.
            new_title = element_text(heading, True) if heading is not None else book_title
            title.text = new_title
            book.dirty.add(path)
            report.add("Empty <title> filled", f"{path.name}: {new_title}")


# ---------------------------------------------------------------------------
# Step 8 — NCX
# ---------------------------------------------------------------------------
def fix_ncx(book: Book, report: Report) -> None:
    item = book.pkg.ncx_item()
    if item is None:
        report.add("NCX", "no NCX in manifest (nothing to fix)")
        return
    ncx_path = norm(book.pkg.item_path(item))
    tree = parse_xml_file(ncx_path)
    nav_map = tree.find(q("navMap", NCX_NS))

    # 8a. Broken targets.
    for content in nav_map.iter(q("content", NCX_NS)):
        src = content.get("src", "")
        target, frag = resolve_href(ncx_path, src)
        target = norm(target)
        if target not in book.docs:
            cand = find_candidate_file(book, target)
            if cand is None:
                nav_point = content.getparent()
                nav_point.getparent().remove(nav_point)
                report.add("NCX entries removed (file missing)", src)
                continue
            target = cand
            content.set("src", relative_href(ncx_path, target, frag))
            report.add("NCX targets re-pointed", src)
        if frag and frag not in book.ids[target]:
            content.set("src", relative_href(ncx_path, target))
            report.add("NCX targets without anchor (anchor missing)", src)

    # 8b. Sequential playOrder (shared by entries with the same target) and unique ids.
    assign_play_order(nav_map)
    used_ids: set[str] = set()
    for order, nav_point in enumerate(nav_map.iter(q("navPoint", NCX_NS)), start=1):
        ident = nav_point.get("id") or f"navPoint-{order}"
        if ident in used_ids:
            ident = f"navPoint-{order}"
        nav_point.set("id", ident)
        used_ids.add(ident)

    # 8c. dtb:depth must match the real nesting depth.
    def depth(el, level=0):
        kids = el.findall(q("navPoint", NCX_NS))
        return max([depth(k, level + 1) for k in kids], default=level)

    real_depth = str(max(depth(nav_map), 1))
    for meta in tree.iter(q("meta", NCX_NS)):
        if meta.get("name") == "dtb:depth" and meta.get("content") != real_depth:
            report.add("NCX depth corrected", f"{meta.get('content')} -> {real_depth}")
            meta.set("content", real_depth)

    write_xml_file(
        ncx_path,
        tree,
        '<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN"\n'
        '   "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">',
    )


# ---------------------------------------------------------------------------
# Step 9 — OPF spine and guide
# ---------------------------------------------------------------------------
def fix_opf(pkg: EpubPackage, report: Report) -> None:
    spine = pkg.spine_el()
    for ref in list(spine):
        if ref.get("idref") not in pkg.manifest:
            spine.remove(ref)
            report.add("Spine entries removed (no manifest item)", ref.get("idref"))
    guide = pkg.guide_el()
    if guide is not None:
        for ref in list(guide):
            if not isinstance(ref.tag, str):
                continue
            path, _ = resolve_href(pkg.opf_path, ref.get("href", ""))
            if not norm(path).exists():
                guide.remove(ref)
                report.add("Guide entries removed (file missing)", ref.get("href"))
    pkg.save_opf()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def fix_epub(epub_path: Path, output_dir: Path = OUTPUT_DIR, work_dir: Path = WORK_DIR) -> Path:
    """Repair one EPUB and return the path of the repaired copy."""
    epub_path = Path(epub_path)
    out_path = Path(output_dir) / f"{epub_path.stem}{OUTPUT_SUFFIX}.epub"
    unpacked = unpack_epub(epub_path, Path(work_dir) / f"{epub_path.stem}{OUTPUT_SUFFIX}")
    report = Report()

    fix_entities(unpacked, report)  # 1 (raw text, so it goes first)
    pkg = load_package(unpacked)
    fix_manifest(pkg, report)  # 2
    book = Book(pkg)
    fix_duplicate_ids(book, report)  # 3
    fix_chapter_markup(book, report)  # 4
    book.rebuild_ids()
    fix_broken_links(book, report)  # 5
    book.rebuild_ids()
    fix_note_round_trips(book, report)  # 6
    fix_titles_and_lang(book, report)  # 7
    book.save()
    fix_ncx(book, report)  # 8
    fix_opf(pkg, report)  # 9

    pack_epub(unpacked, out_path)
    print(f"[fix_links] {epub_path.name}")
    report.print()
    print(f"  -> {out_path}")
    return out_path


if __name__ == "__main__":
    # A path given on the command line wins over the BIBLE_PATH constant.
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else BIBLE_PATH
    if not source.exists():
        sys.exit(f"EPUB not found: {source}\nEdit BIBLE_PATH at the top of {Path(__file__).name}.")
    fix_epub(source)

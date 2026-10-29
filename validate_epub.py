"""
validate_epub.py
================

Read-only checker. Opens an EPUB (original or generated) and reports problems
WITHOUT changing anything. Use it before and after the other scripts to see
what changed.

Checks
------
* ZIP layout: 'mimetype' is the first entry and is stored uncompressed.
* Every XHTML file is well-formed XML *as is* (no entity fixing here, on purpose:
  this is what a strict reader sees).
* Every internal <a href> points to an existing file and an existing anchor.
* Footnote round trips: verse -> note -> "<<" back to the same verse.
* NCX: every target exists, playOrder is 1..N, and how many entries per level.
* OPF: spine items exist in the manifest; manifest files exist on disk.

How to use
----------
    python validate_epub.py                 # uses BIBLE_PATH below
    python validate_epub.py "some file.epub"
Exit code is 0 when no problem was found, 1 otherwise.
"""

from __future__ import annotations

import os
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

from lxml import etree

from epub_common import NCX_NS, is_external, load_package, local_name, make_parser, q, resolve_href

# Strict parser: like make_parser() but undefined entities (&nbsp; without DTD) ARE
# an error here, because that is exactly what a strict e-reader would complain about.
STRICT_PARSER = etree.XMLParser(load_dtd=False, no_network=True, huge_tree=True)

from bibles_config import OUTPUT_DIR  # noqa: E402  (folders live in bibles_config.py)

BIBLE_PATH = OUTPUT_DIR / "01-La Biblia de las Américas - Anónimo.epub"


def validate(epub_path: Path) -> int:
    """Print a report for one EPUB and return the number of problems found."""
    problems: Counter = Counter()
    examples: dict[str, list[str]] = {}

    def problem(kind: str, detail: str) -> None:
        problems[kind] += 1
        examples.setdefault(kind, [])
        if len(examples[kind]) < 3:
            examples[kind].append(detail)

    # --- ZIP layout ---------------------------------------------------------------
    with zipfile.ZipFile(epub_path) as zf:
        first = zf.infolist()[0]
        if first.filename != "mimetype" or first.compress_type != zipfile.ZIP_STORED:
            problem("mimetype not first/stored", first.filename)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(epub_path) as zf:
            zf.extractall(root)
        pkg = load_package(root)

        # --- OPF consistency ----------------------------------------------------------
        for idref in pkg.spine_ids:
            if idref not in pkg.manifest:
                problem("spine item not in manifest", idref)
        for item in pkg.manifest.values():
            if not pkg.item_path(item).exists():
                problem("manifest file missing", item.href)

        # --- parse XHTML strictly -----------------------------------------------------
        docs: dict[Path, etree._ElementTree] = {}
        for item in pkg.xhtml_items():
            path = Path(os.path.normpath(pkg.item_path(item)))
            try:
                docs[path] = etree.parse(str(path), STRICT_PARSER)
            except etree.XMLSyntaxError as exc:
                problem("XHTML not well-formed", f"{path.name}: {exc}")
        ids = {
            p: {el.get("id") for el in t.iter() if isinstance(el.tag, str) and el.get("id")}
            for p, t in docs.items()
        }

        # --- links --------------------------------------------------------------------
        link_count = 0
        for path, tree in docs.items():
            for a in tree.iter(q("a")):
                href = a.get("href")
                if not href or is_external(href):
                    continue
                link_count += 1
                target, frag = resolve_href(path, href)
                target = Path(os.path.normpath(target))
                if target not in docs:
                    if not target.exists():
                        problem("link to missing file", f"{path.name}: {href}")
                    continue
                if frag and frag not in ids[target]:
                    problem("link to missing anchor", f"{path.name}: {href}")

        # --- footnote round trips -------------------------------------------------------
        notes_ok = 0
        by_id = {
            (p, el.get("id")): el
            for p, t in docs.items()
            for el in t.iter()
            if isinstance(el.tag, str) and el.get("id")
        }
        for path, tree in docs.items():
            for fwd in tree.iter(q("a")):
                if not fwd.get("id") or not fwd.get("href") or is_external(fwd.get("href")):
                    continue
                target, frag = resolve_href(path, fwd.get("href"))
                target = Path(os.path.normpath(target))
                note = by_id.get((target, frag))
                if target == path or note is None:
                    continue
                box = note if (len(note) or (note.text or "").strip()) else note.getparent()
                backs = [resolve_href(target, b.get("href")) for b in box.iter(q("a")) if b.get("href")]
                if not backs:
                    continue
                if any(Path(os.path.normpath(t)) == path and f == fwd.get("id") for t, f in backs):
                    notes_ok += 1
                else:
                    problem("footnote back link points elsewhere", f"{path.name}#{fwd.get('id')}")

        # --- NCX ----------------------------------------------------------------------
        levels: Counter = Counter()
        ncx_item = pkg.ncx_item()
        if ncx_item is None:
            problem("no NCX", "")
        else:
            ncx_path = Path(os.path.normpath(pkg.item_path(ncx_item)))
            ncx = etree.parse(str(ncx_path), make_parser())
            nav_map = ncx.find(q("navMap", NCX_NS))
            orders = []
            order_by_src: dict[str, str] = {}
            for np_ in nav_map.iter(q("navPoint", NCX_NS)):
                depth = sum(1 for anc in np_.iterancestors() if local_name(anc) == "navPoint") + 1
                levels[depth] += 1
                orders.append(int(np_.get("playOrder", "0")))
                src = np_.find(q("content", NCX_NS)).get("src", "")
                if order_by_src.setdefault(src, np_.get("playOrder")) != np_.get("playOrder"):
                    problem("NCX same target with different playOrder", src)
                target, frag = resolve_href(ncx_path, src)
                target = Path(os.path.normpath(target))
                if target not in docs:
                    problem("NCX target file missing", src)
                elif frag and frag not in ids[target]:
                    problem("NCX target anchor missing", src)
            # Numbers must start at 1 and never jump (repeats are allowed for same targets).
            seen_max = 0
            for o in orders:
                if o > seen_max + 1:
                    problem("NCX playOrder not sequential", str(o))
                    break
                seen_max = max(seen_max, o)

    # --- report -------------------------------------------------------------------------
    print(f"[validate] {epub_path.name}")
    print(f"  xhtml files: {len(docs)}, internal links: {link_count}, footnotes ok: {notes_ok}")
    print("  NCX entries per level: " + ", ".join(f"L{k}={v}" for k, v in sorted(levels.items())))
    if not problems:
        print("  OK — no problems found")
    for kind, n in problems.items():
        print(f"  ! {kind}: {n}")
        for e in examples[kind]:
            print(f"      {e}")
    return sum(problems.values())


if __name__ == "__main__":
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else BIBLE_PATH
    if not source.exists():
        sys.exit(f"EPUB not found: {source}\nEdit BIBLE_PATH at the top of {Path(__file__).name}.")
    sys.exit(1 if validate(source) else 0)

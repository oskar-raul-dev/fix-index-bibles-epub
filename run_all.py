"""
run_all.py
==========

Processes EVERY .epub listed in bibles_config.BIBLES that exists in INPUT_DIR
(default: input/ inside the project; change it with BIBLE_INPUT_DIR):

    original.epub
      --fix_links-->        work/stages/... [fixed].epub
      --build_navigation--> work/stages/... [fixed] [nav].epub
      --set_metadata-->     output/01-La Biblia de las Américas - Anónimo.epub

Only the final files go to output/; the intermediate ones stay in work/stages/.
The final file is validated at the end.

The individual scripts still work on their own with their BIBLE_PATH constant;
this file only calls their main functions in a loop.

    python run_all.py
"""

from __future__ import annotations

import time

from bibles_config import BIBLES, INPUT_DIR, OUTPUT_DIR, STAGES_DIR, WORK_DIR
from build_navigation import build_navigation
from fix_links import fix_epub
from set_metadata import set_metadata
from validate_epub import validate

# Folders come from bibles_config.py:
#   INPUT_DIR  originals (input/ or $BIBLE_INPUT_DIR)
#   OUTPUT_DIR final files only
#   WORK_DIR   unpacked copies;  STAGES_DIR  intermediate [fixed] / [nav] epubs


def main() -> None:
    print(f"Input folder: {INPUT_DIR}")
    epubs = [INPUT_DIR / name for name in BIBLES if (INPUT_DIR / name).exists()]
    missing = [name for name in BIBLES if not (INPUT_DIR / name).exists()]
    for name in missing:
        print(f"(skipped, not found) {name}")
    if not epubs:
        print("No Bibles found. Copy the original .epub files into input/ or set BIBLE_INPUT_DIR.")
    for epub in epubs:
        start = time.time()
        print("=" * 100)
        fixed = fix_epub(epub, STAGES_DIR, WORK_DIR)
        nav = build_navigation(fixed, STAGES_DIR, WORK_DIR)
        final = set_metadata(nav, OUTPUT_DIR, WORK_DIR)
        validate(final)
        print(f"  ({time.time() - start:.1f} s)")


if __name__ == "__main__":
    main()

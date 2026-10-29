"""
bibles_config.py
================

Project configuration in ONE place:

1. Folders (input, output, work). All are relative to this project folder, so the
   scripts work from any terminal opened inside the project (no initial `cd`).
   The input folder can be changed without editing code with the environment
   variable BIBLE_INPUT_DIR, e.g.:
       BIBLE_INPUT_DIR=~/Documents/Torrents/Biblias_Arreglar python run_all.py

2. Final names and metadata of each Bible. Edit the BIBLES map to rename files,
   change the order in the collection, or add a new Bible.

Key   : file name of the ORIGINAL epub inside INPUT_DIR (exactly as on disk).
Value : (number in the collection, title).

From each entry set_metadata.py produces:
    file name    "<title> - <AUTHOR>.epub"   e.g. "01-La Biblia de las Américas - Anónimo.epub"
    title        "<title>"                   (also used as title sort)
    author       AUTHOR                      (also used as author sort)
    collection   COLLECTION, with the number as position in the collection
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).resolve().parent

# Where the ORIGINAL epubs are read from. Default: input/ inside the project.
# Override with the environment variable BIBLE_INPUT_DIR ("~" is expanded).
INPUT_DIR = Path(os.environ.get("BIBLE_INPUT_DIR", PROJECT_DIR / "input")).expanduser().resolve()

# Where the generated epubs are written.
OUTPUT_DIR = PROJECT_DIR / "output"

# Unzipped working copies and intermediate epubs (regenerable, gitignored).
WORK_DIR = PROJECT_DIR / "work"
STAGES_DIR = WORK_DIR / "stages"

# ---------------------------------------------------------------------------
# Names and metadata
# ---------------------------------------------------------------------------
COLLECTION = "Biblias"
AUTHOR = "Anónimo"

BIBLES: dict[str, tuple[int, str]] = {
    "[Biblias 01] La Biblia de las Americas [10343] (r1.4).epub":
        (1, "01-La Biblia de las Américas"),
    "[Biblias 02] Biblia Reina-Valera 1960 [10645] (r1.3).epub":
        (2, "02-Biblia Reina-Valera 1960"),
    "[Biblias 03] Biblia Reina-Valera Contemporanea [10669] (r1.2).epub":
        (3, "03-Biblia Reina-Valera Contemporánea"),
    "[Biblias 04] Nueva Biblia Latinoamericana de Hoy [10671] (r1.3).epub":
        (4, "04-Nueva Biblia Latinoamericana de Hoy"),
    "[Biblias 05] Biblia Nueva Traduccion Viviente [10701] (r1.0 nadie4ever).epub":
        (5, "05-Biblia Nueva Traducción Viviente"),
    "[Biblias 06] Biblia Traduccion al Lenguaje Actual [10794] (r1.0 nadie4ever).epub":
        (6, "06-Biblia Traducción al Lenguaje Actual Protestante"),
    "[Biblias 07] Anonimo - Biblia Traduccion al Lenguaje Actual Catolica [10795] (r1.1).epub":
        (7, "07-Biblia Traducción al Lenguaje Actual Católica"),
    "[Biblias 08] AA. VV. - Sagrada Biblia (Version oficial de la Conferencia Episcopal Espanola) [17507] (r1.4).epub":
        (8, "08-Sagrada Biblia Conferencia Episcopal Española"),
}

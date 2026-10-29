# Bitácora: cómo se analizaron y arreglaron las Biblias

Complemento del `README.md`. Aquí queda **qué se encontró, con qué comandos y por qué
se decidió cada cosa**, para aprender y para repetirlo con otros EPUB.
Los comandos listos para correr están en `comandos.txt`.

---

## 1. Un EPUB por dentro

Un `.epub` es un ZIP con:

```
mimetype                  "application/epub+zip" (primero y sin comprimir)
META-INF/container.xml    dice dónde está el .opf
OEBPS/content.opf         metadata + manifest (lista de archivos) + spine (orden de lectura) + guide
OEBPS/toc.ncx             índice que muestra Kindle (EPUB 2)
OEBPS/Text/*.xhtml        el texto
OEBPS/Styles/*.css        estilos
OEBPS/Images/*            imágenes
```

```bash
mkdir -p /tmp/biblia && unzip -oq "input/[Biblias 02] Biblia Reina-Valera 1960 [10645] (r1.3).epub" -d /tmp/biblia
ls -R /tmp/biblia | head -40
grep -o '<itemref idref="[^"]*"' /tmp/biblia/OEBPS/content.opf     # orden de lectura
grep -o '<text>[^<]*</text>' /tmp/biblia/OEBPS/toc.ncx | head -30   # índice
```

Las 8 son EPUB 2 hechas con Sigil (estilo ePubLibre).

---

## 2. Análisis inicial (scripts `probe_*.py`)

Se descomprimieron las 8 en `unpacked/b1 … b8` y se corrieron diagnósticos:

```bash
i=1; for f in input/*.epub; do mkdir -p unpacked/b$i; unzip -oq "$f" -d unpacked/b$i; i=$((i+1)); done
python probe_links.py     # enlaces rotos e ids duplicados
python probe_notes.py     # notas: ida (versículo → nota) y vuelta (<<)
python probe_ncx.py       # referencias del NCX y del OPF
python probe_struct.py    # cómo marca cada Biblia libros, capítulos y versículos
```

Hallazgos:

| # | Biblia | Capítulos | Versículos | Notas | Índice original |
|---|---|---|---|---|---|
| 01 | LBLA | `<h2 title="Capítulo N">N</h2>` | `<sup>N</sup>` | ~18.600 | libros + capítulos |
| 02 | RVR1960 | igual a 01 | igual | ~300 | libros + capítulos |
| 03 | RVC | `<h2>N</h2>`, Salmos en 2 archivos | igual | ~200 | libros + capítulos |
| 04 | NBLH | `<h2 class="junto">N</h2>` | igual | ~11.300 | solo libros |
| 05 | NTV | `<h3>N</h3>` y `<h3>Salmo N</h3>` | igual | ~4.800 | solo libros |
| 06 | TLA | `<h3>N</h3>` | `<sup>N-M</sup>` (rangos) | ~480 | solo libros |
| 07 | TLA Católica | `<h2>N</h2>`, 74 libros | rangos | ~500 | libros + capítulos |
| 08 | CEE | `<span class="firstletter"><sup class="sigla">Gén</sup>N</span>` dentro del párrafo; Salmos `<h4>Salmo N</h4>`; varios versículos por párrafo | `<sup class="versiculo">N</sup>` | ~1.200 | secciones temáticas |

Comandos útiles de esa exploración:

```bash
# Qué formas de <sup> hay (N = número)
grep -ho '<sup[^>]*>[^<]*</sup>' unpacked/b*/OEBPS/Text/*.xhtml | sed -E 's/[0-9]+/N/g' | sort | uniq -c | sort -rn | head -20
# Ver un caso concreto con contexto
grep -n -B3 -A3 '>25</h2>' unpacked/b1/OEBPS/Text/002.xhtml          # Éxodo 25 duplicado
grep -n -B3 -A3 'sigil_not_in_toc">18</h2>' unpacked/b4/OEBPS/Text/genesis.xhtml
# Archivos más pesados
ls -lS unpacked/b2/OEBPS/Text | head
```

---

## 3. Errores encontrados en los originales

| Biblia | Problema | Qué hace el script |
|---|---|---|
| 7 de 8 | `&nbsp;` (inválido en XHTML) | → `&#160;` |
| 01 | Éxodo 25 duplicado completo (+29 notas) | borra la copia y sus notas |
| 03 | Juan 8: versículo vacío + encabezado "1" suelto | los quita |
| 04 | 7 versículos marcados como capítulo (Gén 49:18, Hch 13:41, Jer 21:12, Ez 35:4, Dn 4:3, Sal 119:2 y 119:15) | los vuelve versículos |
| 05, 06 | sin `xml:lang`, `<title>` vacíos | los completa |
| 04 | Salmos 94–118 de otra traducción metidos en el Salmo 118 | solo se avisa (es contenido) |

Los enlaces de notas estaban bien en las 8 (ida y vuelta).

---

## 4. Decisiones tomadas por pruebas en la Kindle

| Intento | Resultado en Kindle | Decisión |
|---|---|---|
| Índice AT ▸ libro ▸ capítulos | En Paperwhite pliega los 3 niveles | `TESTAMENTS_AS_PARENTS = True` |
| Cuadrículas con `<table>` | Miniatura que hay que tocar; la #02 se congelaba | listas en párrafo (`NAV_LAYOUT = "inline"`) |
| Libros en un solo archivo (Salmos ~500 KB) | saltos y botón "volver" lentos | partir: `CHAPTER_PER_FILE = True` |
| Reenviar sin borrar la versión vieja | Kindle reusa la conversión anterior | borrar antes de reenviar |

---

## 5. Pruebas hechas fuera del Mac (en la nube, referencia)

```bash
uv python install 3.14                      # Python 3.14.6 de prueba
uv venv -p 3.14 venv314
VIRTUAL_ENV=venv314 uv pip install -r requirements.txt
venv314/bin/python run_all.py
java -jar epubcheck-5.2.1/epubcheck.jar "output/02-Biblia Reina-Valera 1960 - Anónimo.epub"
```

Resultado: las 8 con **0 errores / 0 advertencias** en epubcheck 5.2.1.

---

## 6. Limpieza manual

```bash
rm -rf .venv-probe __pycache__   # basura
rm -rf work                      # copias de trabajo e intermedios (se regeneran)
rm -f run_all.log
# opcional, si ya no quieres el material del análisis:
# rm -rf unpacked; rm -f probe_*.py
```

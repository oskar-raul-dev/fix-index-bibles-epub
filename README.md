# Arreglo Biblias EPUB para Kindle

Proyecto para arreglar Biblias EPUB y aprender a manipular EPUB con Python.

Scripts en **Python 3.14 + lxml** que toman las 8 Biblias EPUB de la carpeta de entrada (`input/`)
y generan copias corregidas, livianas y fáciles de navegar en Kindle:

- índice plegable **Antiguo Testamento ▸ libro ▸ capítulos** (y lo mismo para el Nuevo);
- lista de capítulos al inicio de cada libro (`1 · 2 · 3 …`);
- lista de versículos al inicio de cada capítulo, con enlace de regreso a los capítulos;
- nombre de archivo y metadata listos para Calibre (`01-La Biblia de las Américas - Anónimo.epub`,
  autor *Anónimo*, colección *Biblias* con su número).

**Los .epub originales nunca se modifican.** Todas las rutas son relativas al proyecto:
se trabaja con una terminal abierta en la carpeta del proyecto (por ejemplo la terminal de VS Code), sin `cd`.

---

## Objetivo

La Biblia no se lee como una novela, de principio a fin: se lee **por referencias**.
Un sermón, un plan de lectura o una cita dicen "Juan 3:16" o "Salmo 23", y uno
necesita llegar rápido a ese **libro → capítulo → versículo** y volver.

Los EPUB originales solo traían un índice por libros (algunos ni eso), así que en Kindle
había que pasar páginas hasta encontrar el capítulo. Este proyecto reorganiza la
navegación para moverse como se lee la Biblia:

- **Índice plegable en tres niveles**: Antiguo/Nuevo Testamento ▸ libro ▸ capítulo.
  Desde el menú de Kindle se llega a cualquier capítulo en 3 toques.
- **Lista de capítulos al inicio de cada libro** (`1 · 2 · 3 …`): para saltar dentro del libro.
- **Lista de versículos al inicio de cada capítulo**: para llegar al versículo exacto,
  con un enlace de regreso a la lista de capítulos.
- Y que todo sea **liviano** para que la Kindle responda rápido (sin tablas, un archivo por capítulo).

De paso, es un proyecto de **aprendizaje** para manipular EPUB con Python: abrirlos,
entender su estructura (OPF, NCX, XHTML), corregirlos y volver a empaquetarlos.

## Origen de las Biblias

Las Biblias se descargaron de **[epublibre.org](https://epublibre.org/)**. Quien quiera
usar estos scripts puede buscar Biblias en ese portal y ponerlas en `input/`
(ver `input/README.md`; los nombres deben coincidir con `bibles_config.py`).

**Los EPUB no están en el repositorio**, ni los originales ni los generados
(`.gitignore` los excluye). Que un texto bíblico se consiga en muchos sitios no significa
que sea de dominio público: las traducciones modernas (por ejemplo Reina-Valera 1960,
La Biblia de las Américas, NTV, TLA, NBLH, la de la Conferencia Episcopal) tienen
derechos de autor de sus editoriales o sociedades bíblicas; solo ediciones antiguas,
como la Reina-Valera de 1909, suelen estar en dominio público. Por eso aquí solo se
publica el código.

---

## 1. Uso rápido

```bash
pyenv local 3.14.9              # solo la primera vez
python -m venv .venv            # solo la primera vez
source .venv/bin/activate
pip install -r requirements.txt # solo la primera vez (instala lxml)
python run_all.py
```

### De dónde lee los originales

Todas las carpetas se definen en un solo lugar, arriba de `bibles_config.py`:

| Constante | Por defecto | Qué es |
|---|---|---|
| `INPUT_DIR` | `input/` | EPUB originales. Se cambia sin tocar código con la variable de ambiente `BIBLE_INPUT_DIR` |
| `OUTPUT_DIR` | `output/` | EPUB generados |
| `WORK_DIR`, `STAGES_DIR` | `work/`, `work/stages/` | copias descomprimidas e intermedios |

Dos formas de dar los originales (ver `input/README.md`):

```bash
cp ~/Documents/Torrents/Biblias_Arreglar/*.epub input/                      # copiarlos a input/
BIBLE_INPUT_DIR=~/Documents/Torrents/Biblias_Arreglar python run_all.py     # o leerlos donde están
```

`input/` está en `.gitignore` (solo se versionan su `README.md` y `.gitkeep`), igual que `work/` y `unpacked/`.

Resultado en `output/` (solo los finales):

```
01-La Biblia de las Américas - Anónimo.epub
02-Biblia Reina-Valera 1960 - Anónimo.epub
03-Biblia Reina-Valera Contemporánea - Anónimo.epub
04-Nueva Biblia Latinoamericana de Hoy - Anónimo.epub
05-Biblia Nueva Traducción Viviente - Anónimo.epub
06-Biblia Traducción al Lenguaje Actual Protestante - Anónimo.epub
07-Biblia Traducción al Lenguaje Actual Católica - Anónimo.epub
08-Sagrada Biblia Conferencia Episcopal Española - Anónimo.epub
```

Los intermedios (`... [fixed].epub`, `... [fixed] [nav].epub`) quedan en `work/stages/`,
y las copias descomprimidas en `work/`. Ambas se pueden borrar: se regeneran.

Comandos completos y comentados: `comandos.txt`. Bitácora de lo que se encontró y cómo: `COMANDOS.md`.

---

## 2. La historia: qué hace cada script

```
original.epub
  └─ fix_links.py ─────────▶ ... [fixed].epub          (arregla lo técnico)
       └─ build_navigation.py ─▶ ... [fixed] [nav].epub (arma la navegación)
            └─ set_metadata.py ─▶ 01-... - Anónimo.epub (nombre y metadata)
                 └─ validate_epub.py                    (revisa, no cambia nada)
```

### `fix_links.py` — el mecánico
Abre el EPUB (es un ZIP) y repara lo técnico, paso por paso (cada paso es una función):

1. `fix_entities`: `&nbsp;` y otras entidades HTML → numéricas (`&#160;`). En XHTML son inválidas.
2. `fix_manifest`: la lista de archivos del OPF coincide con los archivos reales.
3. `fix_duplicate_ids`: renombra ids repetidos.
4. `fix_chapter_markup`: capítulos mal marcados en el texto fuente:
   versículo escrito como capítulo (#04, Gén 49:18 y 6 más), "1" suelto (#03, Juan 8),
   capítulo duplicado completo (#01, Éxodo 25, con sus 29 notas).
5. `fix_broken_links`: enlaces a archivos o anclas que no existen.
6. `fix_note_round_trips`: cada nota vuelve (`<<`) al mismo versículo.
7. `fix_titles_and_lang`: `<title>` vacíos e idioma (`xml:lang`).
8. `fix_ncx`: índice NCX con destinos válidos y `playOrder` correcto.
9. `fix_opf`: spine y guide sin referencias rotas.

### `build_navigation.py` — el bibliotecario
- Reconoce cada libro por su título (catálogo de 73 libros en español en `epub_common.py`),
  aunque venga partido en varios archivos.
- Encuentra capítulos y versículos aunque cada Biblia los marque distinto
  (`<h2>1</h2>`, `Capítulo 1`, `Salmo 1`, `<span class="firstletter">Gén 1</span>`…).
- Pone las listas de capítulos y de versículos (párrafos, no tablas).
- Pone cada capítulo en su propio archivo (archivos chicos = Kindle rápido).
- Rehace el índice NCX (el que muestra Kindle) y crea una página "Índice".
- Se puede correr varias veces: borra lo que generó antes (todo lleva el prefijo `bnav`).

### `set_metadata.py` — las fichas
Según `bibles_config.py`: título y orden de título, autor *Anónimo* (los traductores
quedan como colaboradores), colección *Biblias* con su número, y el nombre final del archivo.

### `validate_epub.py` — el inspector
Solo mira: XML bien formado, enlaces, notas ida y vuelta, NCX, OPF. Sirve para comparar
el original con el resultado.

### `run_all.py` — el capataz
Pasa todas las Biblias de `bibles_config.py` por los tres pasos y valida el final.

### `epub_common.py` — la caja de herramientas
Abrir y empaquetar EPUB (con `mimetype` primero y sin comprimir, como exige el estándar),
leer y escribir XHTML, catálogo de libros, expresiones para capítulos y versículos.

### `bibles_config.py` — la lista
Diccionario `archivo original → (número, título)`, más `COLLECTION` y `AUTHOR`.
Para renombrar, reordenar o agregar una Biblia se edita solo este archivo.

### `probe_*.py` — diagnósticos del análisis inicial
Scripts cortos que leen `unpacked/` (las Biblias descomprimidas) para entender la estructura.
Ver `COMANDOS.md`.

---

## 3. Configuración (constantes arriba de cada script)

| Script | Constante | Para qué |
|---|---|---|
| todos | `BIBLE_PATH` | archivo a procesar si corres el script solo (o pásalo como argumento) |
| `build_navigation.py` | `TESTAMENTS_AS_PARENTS` | `True`: AT ▸ libro ▸ capítulo. `False`: libros arriba, testamentos como entradas sueltas |
| | `CHAPTER_PER_FILE` | `True`: un archivo por capítulo. `False`: partes de ~`SPLIT_MAX_BYTES` |
| | `SPLIT_LARGE_FILES`, `SPLIT_MAX_BYTES` | partir libros grandes (y tamaño objetivo) |
| | `ADD_VERSE_LISTS` | `False` quita las listas de versículos (~31.000 enlaces) si Kindle va lento |
| | `NAV_LAYOUT`, `NAV_SEPARATOR` | `"inline"` (`1 · 2 · 3`) o `"table"` (cuadrícula; mala en Kindle) |
| | `USE_SOURCE_BOOK_NAMES` | nombres de libro como los escribe cada Biblia, o los uniformes del catálogo |
| | `LABEL_*` | textos: "Capítulo {n}", "Antiguo Testamento", "Índice"… |
| | `GROUP_NOTES_IN_NCX`, `REMOVE_OLD_HTML_TOC`, `CREATE_HTML_INDEX` | detalles del índice |
| `bibles_config.py` | `BIBLES`, `COLLECTION`, `AUTHOR` | nombres, orden, colección, autor |

---

## 4. Lo que aprendimos con la Kindle

- **Tablas = mal.** Kindle muestra las tablas como miniatura que hay que tocar, y muchas
  tablas en un archivo grande la congelaban (la #02 dejaba la pantalla en blanco).
  Por eso las listas son párrafos.
- **Archivos chicos = rápido.** Kindle arma un archivo completo antes de mostrar una página.
  Los libros de muchas novelas van rápido porque vienen en muchos archivos chicos.
  Salmos en un solo archivo de ~500 KB era lento; ahora cada capítulo es un archivo.
- **El índice de 3 niveles funciona** en Kindle Paperwhite.
- **`&nbsp;` rompe** a los lectores estrictos: siempre `&#160;`.
- Al reenviar por "Send to Kindle", **borra antes la versión vieja** (en el Kindle y en
  "Contenido y dispositivos" de Amazon) para que no reuse la conversión anterior.
- Calibre lee la colección como *serie*; la Kindle no crea colecciones a partir de esa
  metadata al enviar por correo: la colección se arma en el dispositivo.

### Avisos de contenido (no se tocan)
- **#04 Salmos** trae un bloque de otra traducción (Salmos 94–118 repetidos dentro del Salmo 118).
- **#08**: el índice muestra capítulos en vez de los títulos de sección que tenía.

---

## 5. Editar a mano en Sigil

[Sigil](https://sigil-ebook.com) es un editor libre de EPUB. Úsalo para retoques puntuales.

### Regla de oro
- **Cambios de contenido o estructura** (corregir texto, quitar páginas): hazlos sobre el
  **original** de `input/` (o una copia) y vuelve a correr `python run_all.py`.
  Así no se pierde nada al regenerar.
- **Retoques finales** (portada, metadata): hazlos sobre el archivo de `output/`.
  Si vuelves a correr `run_all.py`, se pisan; repítelos o cámbialos en `bibles_config.py`.

### Cambiar la portada
1. Prepara la imagen: **JPG**, vertical, ideal **1600 × 2560 px** (proporción 1:1,6), menos de 5 MB.
2. Sigil → *File ▸ Open* (Archivo ▸ Abrir) el `.epub`.
3. *Tools ▸ Add Cover…* (Herramientas ▸ Añadir portada) → *Other Files…* → elige la imagen.
   Sigil la copia a `Images/`, actualiza la página de portada (`cubierta.xhtml`) y la marca
   como portada en la metadata.
4. *File ▸ Save* (Ctrl/Cmd + S).

Alternativa más simple: en **Calibre** → *Editar metadatos* → *Examinar* (portada) → Aceptar.
Calibre incrusta la portada al enviar o guardar el libro.

### Editar metadata (título, autor, idioma…)
*Tools ▸ Metadata Editor* (F8). Para título, autor y serie también sirve `bibles_config.py`
o Calibre (*Editar metadatos*).

### Editar texto o estilos
- En el panel izquierdo (*Book Browser*): `Text/` tiene los capítulos (`001.xhtml`,
  `001-bnav2.xhtml`…), `Styles/` las hojas de estilo. `bnav.css` es la de las listas generadas.
- Doble clic abre el archivo; *View ▸ Code View* muestra el HTML.
- Buscar y reemplazar en todo el libro: *Edit ▸ Find & Replace* (Ctrl/Cmd + F),
  con *Mode: Regex* y *Target: All HTML Files* para reemplazos masivos.

### Índice (cuidado)
- *Tools ▸ Table Of Contents ▸ Edit Table Of Contents* permite renombrar entradas.
- **No uses *Generate Table Of Contents***: lo rehace desde los encabezados y borra el índice
  plegable por capítulos. Si lo hiciste por error, vuelve a correr `build_navigation.py`.

### Validar antes de enviar
- *Tools ▸ Well-Formed Check EPUB* (F7).
- Plugin **EPUBCheck** de Sigil, o desde terminal: `python validate_epub.py "output/archivo.epub"`.

---

## 6. Estructura de la carpeta

```
<proyecto>/
├── README.md            este archivo
├── CLAUDE.md            guía del proyecto para Claude Code
├── COMANDOS.md          bitácora: análisis, errores encontrados, comandos
├── comandos.txt         comandos listos para copiar y correr
├── requirements.txt     lxml
├── bibles_config.py     carpetas (INPUT_DIR…), nombres, orden, colección, autor
├── epub_common.py       herramientas compartidas
├── fix_links.py         paso 1
├── build_navigation.py  paso 2
├── set_metadata.py      paso 3
├── validate_epub.py     revisión (solo lectura)
├── run_all.py           todo de una vez
├── probe_*.py           diagnósticos del análisis inicial (leen unpacked/)
├── input/               EPUB originales (ignorado por git; tiene README.md y .gitkeep)
├── unpacked/            Biblias originales descomprimidas (para los probe_*.py)
├── work/                copias de trabajo e intermedios (se regenera)
└── output/              los 8 EPUB finales
```

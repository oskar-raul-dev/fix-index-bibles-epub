# input/

Aquí van los **EPUB originales** que procesan los scripts. El contenido de esta carpeta
está ignorado por git (solo se versionan este README y `.gitkeep`).

Los nombres de archivo deben coincidir **exactamente** con las claves de `BIBLES`
en `bibles_config.py`, por ejemplo:

```
input/[Biblias 01] La Biblia de las Americas [10343] (r1.4).epub
input/[Biblias 02] Biblia Reina-Valera 1960 [10645] (r1.3).epub
...
```

## Dos formas de darles los originales

1. **Copiarlos aquí** (los originales quedan intactos donde estaban):

   ```bash
   cp ~/Documents/Torrents/Biblias_Arreglar/*.epub input/
   ```

2. **Dejarlos donde están** y apuntar la variable de ambiente `BIBLE_INPUT_DIR`:

   ```bash
   BIBLE_INPUT_DIR=~/Documents/Torrents/Biblias_Arreglar python run_all.py
   # o para toda la sesión de terminal:
   export BIBLE_INPUT_DIR=~/Documents/Torrents/Biblias_Arreglar
   ```

Los scripts **nunca modifican** los archivos de entrada.

## Fuentes

Las Biblias no se suben al repositorio (derechos de autor). Se descargan de
[epublibre.org](https://www.epublibre.org):

| # | Biblia | Enlace |
|---|---|---|
| 01 | La Biblia de las Américas | _pendiente_ |
| 02 | Biblia Reina-Valera 1960 | _pendiente_ |
| 03 | Biblia Reina-Valera Contemporánea | _pendiente_ |
| 04 | Nueva Biblia Latinoamericana de Hoy | _pendiente_ |
| 05 | Biblia Nueva Traducción Viviente | _pendiente_ |
| 06 | Biblia Traducción al Lenguaje Actual (Protestante) | _pendiente_ |
| 07 | Biblia Traducción al Lenguaje Actual (Católica) | _pendiente_ |
| 08 | Sagrada Biblia (Conferencia Episcopal Española) | _pendiente_ |

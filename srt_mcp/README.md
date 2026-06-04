# srt_mcp — Servidor MCP para ficheros `.srt`

Servidor [MCP](https://modelcontextprotocol.io) que expone como *tools* operaciones de
**lectura y búsqueda** sobre los subtítulos `.srt` que genera el transcriptor del proyecto
(`transcriber/transcribe_diarize.py`). Construido con el SDK oficial `mcp` (FastMCP).

## ⚠️ Runtime separado (Python ≥3.10)

El SDK `mcp`/FastMCP **exige Python ≥3.10**, pero el `.venv` del transcriptor es **3.9.6**
(pineado por torch/pyannote). Por eso este componente vive en **su propio venv** (`.venv-mcp`),
creado sobre el `python3` del sistema (≥3.10). No depende de torch/pyannote. `.venv-mcp` es el
runtime que usa **Claude Code** (vía `.mcp.json`); el **analyzer** arranca su propia copia del
servidor con su intérprete (`.venv-analyzer`, que también es 3.10+ y trae `mcp`).

## Instalación

Desde la raíz del repo:

```bash
make install-mcp
```

Esto crea `.venv-mcp` con `python3` (≥3.10) e instala `mcp`. Equivale a:

```bash
python3 -m venv .venv-mcp
.venv-mcp/bin/pip install -r srt_mcp/requirements.txt
```

## Tools expuestas

`ruta` es **opcional**: si se omite, se usa la env `SRT_MCP_DEFAULT_FILE`.

- **`leer_srt(ruta=None, desde=0, limite=200, desde_seg=None, hasta_seg=None)`** — parsea el
  `.srt` a cues estructurados (`indice`, `inicio`/`fin`, `inicio_seg`/`fin_seg`, `hablante`,
  `texto`). Paginado (los plenos generan miles de cues) y opcionalmente acotado a una ventana
  temporal en segundos.
- **`buscar_srt(consulta, ruta=None, regex=False, ignorar_mayusculas=True, contexto=0, limite=50)`**
  — busca texto (subcadena o regex) y devuelve los cues coincidentes con sus timestamps y,
  opcionalmente, cues vecinos como contexto.
- **`listar_srt(directorio=None)`** — enumera los `.srt` disponibles en un directorio (por defecto
  `SRT_MCP_BASE_DIR`, o la carpeta del fichero por defecto). Devuelve por cada uno `nombre`, `ruta`
  (el valor a pasar luego a `leer_srt`/`buscar_srt`), `tamano_bytes`, `num_cues` y `duracion`. Sirve
  para **descubrir qué plenos hay** antes de leerlos.

El prefijo `[HABLANTE]` que el writer antepone al texto en SRT multi-hablante se separa
automáticamente en el campo `hablante` (es `null` en SRT de un solo hablante).

## Registro en Claude Code

Ya hay un `.mcp.json` (scope de proyecto) en la raíz del repo apuntando a `.venv-mcp`. Sus paths
usan `${CLAUDE_PROJECT_DIR:-.}` (la raíz del proyecto que Claude Code inyecta) en vez de rutas
absolutas, así que es portable entre clones y se commitea tal cual.
Tras `make install-mcp`, reinicia Claude Code en este repo y aprueba el servidor `srt`
cuando lo pida. Las tools `leer_srt`, `buscar_srt` y `listar_srt` quedarán disponibles.

Variables opcionales:
- `SRT_MCP_DEFAULT_FILE`: fichero `.srt` por defecto cuando se llama a una tool sin `ruta`
  (lo usa el analyzer al arrancar el servidor). Si no hay ni `ruta` ni esta env, `leer_srt`/
  `buscar_srt` devuelven un error claro. Queda **exento** de la contención de `SRT_MCP_BASE_DIR`
  (lo aprobó quien arrancó el servidor).
- `SRT_MCP_BASE_DIR`: si se define, restringe las lecturas por `ruta` a ese directorio (p. ej.
  `outputs/videos`) y es la carpeta por defecto de `listar_srt`. El analyzer la fija al directorio
  del catálogo de plenos (`ANALYZER_TRANSCRIPTS_DIR`).

## Lanzar manualmente / inspeccionar

```bash
make mcp-serve                              # arranca el servidor por stdio
# o, con el inspector oficial (requiere Node):
npx @modelcontextprotocol/inspector .venv-mcp/bin/python -m srt_mcp
```

## Estructura

- `srt_parser.py` — parser puro stdlib (sin dependencias), testeable aislado. Inverso de
  `fmt_srt_time()`/`write_output()` del transcriptor.
- `server.py` — instancia FastMCP y las tres tools (`leer_srt`, `buscar_srt`, `listar_srt`).
- `__main__.py` — entrypoint `python -m srt_mcp`.

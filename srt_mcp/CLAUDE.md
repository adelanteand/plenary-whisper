# CLAUDE.md — `srt_mcp/`

Guía para trabajar dentro de este componente. Complementa la `CLAUDE.md` de la raíz (que
describe el monorepo entero); aquí van solo las reglas locales. El README de usuario está en
`srt_mcp/README.md`.

## Qué es

Servidor [MCP](https://modelcontextprotocol.io) construido con el SDK oficial `mcp` (FastMCP)
que expone, como *tools*, operaciones de **lectura y búsqueda** sobre los `.srt` que genera el
transcriptor (`transcriber/transcribe_diarize.py`). Transporte **stdio** (sin puerto de red).

Tiene **dos consumidores** y los cambios de tools afectan a ambos:
- **Claude Code** — registrado en `.mcp.json` (raíz), arranca
  `${CLAUDE_PROJECT_DIR:-.}/.venv-mcp/bin/python -m srt_mcp` (paths portables entre clones).
  Pasa `ruta` explícita en cada llamada.
- **El analyzer** — es un **cliente MCP** (`analyzer/mcp_client.py`) que arranca su propia copia
  del servidor con su intérprete. Conserva `ruta` en el esquema (el modelo puede dirigir
  `leer_srt`/`buscar_srt` a cualquier pleno listado por `listar_srt`); si la omite, se usa
  `SRT_MCP_DEFAULT_FILE`. Fija `SRT_MCP_BASE_DIR` al directorio del catálogo para acotar esas
  lecturas. El analyzer NO importa este paquete; habla solo el protocolo MCP.

## Runtime

- **Python ≥3.10 en venv propio (`.venv-mcp`)**: el SDK `mcp` lo exige. *Aquí sí* se puede usar
  `match/case` y sintaxis 3.10+ (a diferencia del transcriber, que está pineado a 3.9). Aun así,
  `srt_parser.py` se mantiene compatible para poder testearlo aislado en cualquier intérprete.
- Instalación/arranque desde la raíz: `make install-mcp`, `make mcp-serve`.

## Módulos

- `srt_parser.py` — parser puro stdlib SRT→cues **+ operaciones sobre cues** (`buscar_en_cues`,
  `leer_cues`). Es el **inverso** de `fmt_srt_time()`/`write_output()` del transcriptor. Es la
  **única fuente** de la lógica de parseo/búsqueda/lectura.
- `server.py` — instancia FastMCP (`mcp = FastMCP("srt-plenos")`), `_resolver_ruta()` /
  `_resolver_directorio()` (validación + resolución) y las tres tools (envoltorios finos sobre
  `srt_parser`). `main()` = `mcp.run()`.
- `__main__.py` — entrypoint `python -m srt_mcp`.

## Tools

`ruta` es **opcional**; si se omite se usa la env `SRT_MCP_DEFAULT_FILE`.

- `leer_srt(ruta=None, desde=0, limite=200, desde_seg=None, hasta_seg=None)` → cues estructurados
  (`indice`, `inicio`/`fin`, `inicio_seg`/`fin_seg`, `hablante`, `texto`), paginados y opcionalmente
  acotados a una ventana temporal en segundos.
- `buscar_srt(consulta, ruta=None, regex=False, ignorar_mayusculas=True, contexto=0, limite=50)` →
  cues coincidentes con timestamps y, opcionalmente, cues vecinos como contexto. **`consulta` va
  primero** porque `ruta` tiene default (en Python los parámetros con default van al final).
- `listar_srt(directorio=None)` → catálogo de `.srt` del directorio (`directorio` explícito →
  `SRT_MCP_BASE_DIR` → carpeta de `SRT_MCP_DEFAULT_FILE`). Por fichero: `nombre`, `ruta` (= el
  filename, lo que se pasa luego a `leer_srt`/`buscar_srt`), `tamano_bytes`, `num_cues`, `duracion`.

## Variables de entorno

- `SRT_MCP_DEFAULT_FILE` — fichero `.srt` por defecto cuando se llama a `leer_srt`/`buscar_srt`
  sin `ruta`. Lo fija el cliente del analyzer al arrancar (si hay pleno cargado). Si no hay ni
  `ruta` ni esta env, esas tools devuelven un error claro (`ValueError`). Queda **exento** de la
  contención de `SRT_MCP_BASE_DIR` (es un fichero ya aprobado por quien arrancó el servidor; así
  un `--srt` fuera del catálogo sigue funcionando).
- `SRT_MCP_BASE_DIR` — si se define, restringe a ese directorio las lecturas por una `ruta` dada
  por el llamante (defensa cuando el modelo o Claude Code pueden pasar `ruta` arbitraria) y es la
  carpeta por defecto de `listar_srt`. **El analyzer SÍ la fija** ahora (al catálogo de plenos,
  `ANALYZER_TRANSCRIPTS_DIR`), porque conserva `ruta` en el esquema.

## Restricciones críticas (no romper)

- **`srt_parser.py` debe seguir siendo stdlib puro** (sin importar `mcp` ni nada externo): así es
  importable y testeable de forma aislada y sirve de única fuente de la lógica de cues.
- **Las docstrings de las tools son lo que ve el modelo**: son la "descripción" de cada tool en el
  protocolo. Manténlas precisas sobre parámetros y forma del resultado al editarlas.
- **No hagas `ruta` obligatoria**: ambos consumidores la pasan opcional. El analyzer la **conserva**
  en el esquema (para abrir cualquier pleno del catálogo) pero la omite para el pleno por defecto;
  Claude Code la pasa explícita. Sin `ruta` se cae a `SRT_MCP_DEFAULT_FILE`. Mantén esa semántica.
- **Contención del fichero por defecto**: la comprobación de `SRT_MCP_BASE_DIR` se aplica SOLO a una
  `ruta`/`directorio` dados por el llamante, NO a `SRT_MCP_DEFAULT_FILE` (ver `from_default` en
  `_resolver_ruta`). No la apliques al default o romperás un `--srt` fuera del catálogo.
- **El prefijo `[HABLANTE]`** que el writer antepone en SRT multi-hablante se separa al campo
  `hablante` (es `null` en SRT de un solo hablante, coherente con `write_output`). No mezclar el
  prefijo con `texto`.
- **`_MAX_LIMITE`** (en `srt_parser.py`) es el tope defensivo de cues/coincidencias por respuesta:
  los plenos generan miles de cues y devolverlos todos saturaría el contexto del cliente.
- **Formato SRT**: `HH:MM:SS,mmm` (acepta también `.` por robustez). Si cambia el writer del
  transcriptor, mantén `srt_parser` como su inverso exacto.

## Verificación

No hay tests ni linter configurados. Comprobación manual por stdio (roundtrip
`initialize`/`list_tools`/`call_tool`) desde `.venv-mcp`:

```python
# .venv-mcp/bin/python con PYTHONPATH=<raíz del repo>
import asyncio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

async def main():
    p = StdioServerParameters(command="python", args=["-m", "srt_mcp"])
    async with stdio_client(p) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            print([t.name for t in (await s.list_tools()).tools])
            res = await s.call_tool("buscar_srt", {
                "consulta": "se levanta la sesión",
                "ruta": "outputs/videos/pleno_11_mayo_2026_transcripcion.srt",
                "limite": 1,
            })
            print(res.isError, res.content[0].text[:120])

asyncio.run(main())
```

O con el inspector oficial (requiere Node):
`npx @modelcontextprotocol/inspector .venv-mcp/bin/python -m srt_mcp`.

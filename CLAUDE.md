# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Monorepo con dos componentes para trabajar con audios de plenos municipales en castellano:

- **`transcriber/`** — herramienta CLI de un solo script que transcribe audios largos con Whisper
  y, **opcionalmente (con `--diarize`)**, diariza los hablantes con pyannote.audio. Por defecto
  solo transcribe. Toda la lógica vive en `transcriber/transcribe_diarize.py`.
- **`analyzer/`** — chatbot que analiza las transcripciones generadas, construido con el
  Anthropic SDK siguiendo una arquitectura hub-spoke (un agente "hub" orquesta; los "spokes"
  especializados hacen el trabajo concreto). Es un **cliente MCP real** del servidor `srt_mcp`
  (lo arranca por stdio y consume sus tools). Corre en **su propio venv 3.10+**
  (`.venv-analyzer`). Entrypoint: `python -m analyzer`. Ver `## Analyzer (chatbot)` más abajo.
- **`srt_mcp/`** — servidor MCP (SDK oficial `mcp`/FastMCP) que expone tools de **lectura y
  búsqueda** sobre los `.srt` generados. Entrypoint: `python -m srt_mcp`. Corre en **su propio
  venv 3.10+** (`.venv-mcp`). Ver `## SRT MCP` más abajo.

`transcriber/` usa el venv 3.9 (`.venv`, por torch/pyannote); `analyzer/` y `srt_mcp/` usan cada
uno su propio venv 3.10+ (`.venv-analyzer` y `.venv-mcp`) porque el SDK `mcp` exige 3.10+. Todos
comparten el `.env` raíz. Cada componente tiene su propio `requirements.txt`.

## Comandos

- `make install` — instala las dependencias del transcriptor (`transcriber/requirements.txt`).
- `make install-analyzer` — crea el venv 3.10+ (`.venv-analyzer`) del chatbot e instala sus deps (incl. el SDK `mcp`).
- `make install-mcp` — crea el venv 3.10+ (`.venv-mcp`) del servidor MCP de `.srt` e instala `mcp`.
- `make mcp-serve` — arranca el servidor MCP de `.srt` por stdio (para inspección manual).
- `make env` — crea `.env` desde `.env_template` (luego hay que rellenar `HF_TOKEN` y `ANTHROPIC_API_KEY`).
- `make download URL="https://...m3u8" OUTPUT=videos/pleno.mp4` — descarga/remux de un stream con ffmpeg (falla con error si ffmpeg no está instalado).
- Ejecución típica del transcriptor (solo transcribe; la diarización va OFF por defecto):
  `python transcriber/transcribe_diarize.py videos/pleno.mp4`
- Con diarización de hablantes (requiere `HF_TOKEN`; `--speakers` solo aplica al diarizar):
  `python transcriber/transcribe_diarize.py videos/pleno.mp4 --diarize --speakers 3`
- Iteración rápida (omite diarización, transcribe un solo fragmento):
  `python transcriber/transcribe_diarize.py videos/pleno.mp4 --debug-chunk 1`
- Solo diarización (no carga Whisper; cachea los turnos para reusarlos luego):
  `python transcriber/transcribe_diarize.py videos/pleno.mp4 --diarize-only --speakers 3`
- Chatbot de análisis (usa la transcripción de muestra por defecto; corre en `.venv-analyzer`):
  `make analyzer` (o `.venv-analyzer/bin/python -m analyzer`)

No hay tests ni linter configurados.

## Arquitectura (pipeline de 5 pasos en `main()`)

1. `convert_to_wav` → convierte a WAV mono 16 kHz, **cacheado** como `<stem>_16k_mono.wav` junto al archivo de origen; si existe se reutiliza (usa `--force-wav` para regenerarlo).
2. `split_audio` + `transcribe_chunks` → trocea el WAV en chunks de `--chunk-minutes` (temporales) y los transcribe con Whisper, sumando un offset global para recomponer los timestamps absolutos. **Dos niveles de caché**:
   - **Por-chunk** (reanudable): cada chunk se cachea individualmente en `<stem>_chunks/<modelo>_<idioma>_<chunk_minutes>min/chunk_NNN.json` según se transcribe. En re-ejecuciones los chunks ya hechos se reutilizan y solo se transcriben los que falten; si todos están cacheados, ni se carga el modelo Whisper (carga perezosa). La clave incluye `chunk_minutes` porque las fronteras de cada chunk dependen de ese parámetro. Usa `--force-chunks` para re-transcribir todos los chunks desde cero (implica saltar también el caché combinado).
   - **Combinado** (ruta rápida): el resultado completo se cachea en `<stem>_segments.json` (con modelo+idioma); en re-ejecuciones se reutiliza si coinciden, saltando split+transcripción por entero. Usa `--force-transcribe` para ignorarlo y reconstruirlo desde los chunks (reutilizando el caché por-chunk).
   
   El caché por-chunk evita perder el progreso si el proceso se interrumpe a mitad (crash, Ctrl-C, OOM); el combinado evita repetir todo cuando solo falla la diarización posterior. El modo `--debug-chunk` no usa el caché por-chunk (siempre transcribe fresco).
3. `diarize` → pyannote sobre el WAV completo; devuelve turnos de hablante. **Opt-in**: solo corre con `--diarize` (o `--diarize-only`); por defecto el pipeline omite este paso y `assign_speakers` etiqueta todo como `HABLANTE`. **Cacheado** en `<stem>_diarization.json` (con modelo de pyannote + nº de hablantes; *no* depende de `chunk_minutes` ni idioma porque corre sobre el WAV entero): en re-ejecuciones se reutiliza si coinciden, saltando pyannote. Usa `--force-diarize` para ignorarlo y re-diarizar. El acceso unificado (lectura de caché → diarizar → guardar) está en `get_diarization()`, compartido por el pipeline completo (`--diarize`) y el modo `--diarize-only`. Este último diariza y termina **sin transcribir** (Whisper nunca se carga), emitiendo solo los turnos cacheados y el tiempo por hablante; es incompatible con `--debug-chunk`.
4. `assign_speakers` → asigna hablante a cada segmento por mayor solapamiento temporal.
5. `write_output` → genera el TXT, el SRT sincronizado (salvo `--no-srt`), un JSON opcional y estadísticas de tiempo por hablante.

## Restricciones críticas (no romper)

- **Python 3.9.6** (solo el transcriptor): su venv (`.venv`) es 3.9. Por eso el script empieza con `from __future__ import annotations`, necesario para que la sintaxis `X | None` no rompa en 3.9. No lo quites. (El `analyzer/` y `srt_mcp/` corren en venvs 3.10+ aparte y no tienen este límite.)
- **`huggingface_hub<1.0`** (pin en `transcriber/requirements.txt`): pyannote.audio 3.4.0 llama internamente a `hf_hub_download(use_auth_token=...)`, kwarg eliminado en huggingface_hub 1.0. No actualices esa dependencia ni cambies el `use_auth_token=` en `diarize()`.
- **`torch<2.6` / `torchaudio<2.6`** (pin en `transcriber/requirements.txt`): torch ≥2.6 cambió el default de `torch.load` a `weights_only=True`, lo que rompe la carga del checkpoint de pyannote.audio 3.4.0 (`WeightsUnpickler error: ... TorchVersion`). torch<2.6 usa `weights_only=False` por defecto y carga bien. No subas torch a ≥2.6 sin actualizar antes pyannote a una versión compatible.
- **Idioma forzado a `es`** (flag `--language`, default `es`): el autodetect de Whisper fallaba (detectaba "Nynorsk") en silencios/aplausos. `--language auto` reactiva la detección automática.
- **`HF_TOKEN`** se carga de `.env` vía `load_dotenv()` y solo es obligatorio cuando se diariza (`--diarize` o `--diarize-only`). Como la diarización está OFF por defecto, la ejecución básica y `--debug-chunk` no lo necesitan.

## Analyzer (chatbot)

Paquete `analyzer/` — un asistente de terminal que analiza transcripciones de plenos con el
Anthropic SDK. Arquitectura **hub-spoke**: el `Orchestrator` ([analyzer/orchestrator.py](analyzer/orchestrator.py))
es el hub que mantiene el contexto y orquesta; los *spokes* (herramientas especializadas) viven
en `analyzer/spokes/`.

**Tool-use vía MCP (implementado):** el hub arranca el servidor `srt_mcp` como subproceso
(cliente MCP real por stdio, ver [analyzer/mcp_client.py](analyzer/mcp_client.py)), descubre sus
tools (`buscar_srt`, `leer_srt`, `listar_srt`) con `list_tools()` y las expone al modelo. En
`ask()` ejecuta el bucle de tool-use: pasa `tools=[...]` a `messages.stream(...)` y, mientras
`stop_reason == "tool_use"`, **enruta** cada llamada al servidor por el protocolo MCP
(`call_tool`) y devuelve los `tool_result` hasta `end_turn`. El analyzer **NO importa el paquete
`srt_mcp`**: todo el acceso al `.srt` pasa por MCP.

El hub arranca el servidor si hay un `.srt` por defecto (derivado del transcript con
`transcript.sibling_srt`, forzable con `--srt` / `ANALYZER_SRT`) **o** un catálogo que listar; así
el modelo puede `listar_srt` los plenos disponibles y abrir cualquiera por `ruta`. La transcripción
cargada sigue yendo completa en `system` (es el pleno "actual"); el resto se consultan por tools.
El hub pasa el `.srt` por defecto vía `SRT_MCP_DEFAULT_FILE` (el modelo lo lee omitiendo `ruta`) y
fija `SRT_MCP_BASE_DIR` al directorio del catálogo (`ANALYZER_TRANSCRIPTS_DIR`, default
`outputs/videos`) para acotar las lecturas por `ruta`. **El cliente conserva `ruta` en el esquema**
(antes la quitaba). Si ni hay `.srt` ni catálogo (o el servidor no arranca), se comporta como
agente único (sin tools).

Módulos: `config.py` (constantes + `.env`), `transcript.py` (ingestión de `.txt`/`.json` +
`sibling_srt`), `prompts.py` (system prompt en castellano), `orchestrator.py` (hub + bucle
tool-use), `mcp_client.py` (cliente MCP síncrono: arranca/consume el servidor `srt_mcp`),
`spokes/` (reservado para futuros spokes in-process), `repl.py` (bucle de chat), `__main__.py`
(entrypoint `python -m analyzer`).

Restricciones propias:
- **`ANTHROPIC_API_KEY`** obligatoria (en `.env`), leída por el SDK desde el entorno.
- **Venv propio 3.10+** (`.venv-analyzer`): el SDK `mcp` (cliente) exige 3.10+. El analyzer ya no
  comparte el venv 3.9 del transcriber (puede usar `match/case` y sintaxis 3.10+;
  `from __future__ import annotations` se conserva pero es inocuo).
- **Puente sync↔async** en `mcp_client.py`: el orquestador es síncrono y el SDK `mcp` es async.
  Se usa un `anyio` `BlockingPortal` con UNA corrutina `_serve` que posee `stdio_client` +
  `ClientSession` toda la sesión (entrar y salir en la misma tarea evita el error de anyio
  "exit cancel scope in a different task"). No reabrir conexión por llamada.
- **Prompt caching**: la transcripción grande va en `system` con un breakpoint `cache_control`
  y el prefijo debe mantenerse **estable** entre turnos (nada de fecha/fichero dentro de
  `system`; los metadatos volátiles van en el primer mensaje `user`). Las `tools` también forman
  parte del prefijo: se piden una vez al servidor y se adaptan **ordenadas por nombre** y fijas
  durante la sesión (`mcp_client._adapt_tools`). No romper esa invariante.
- Modelo por defecto `claude-sonnet-4-6` (`ANALYZER_MODEL` / `--model` lo sobreescriben).

## SRT MCP

Paquete `srt_mcp/` — servidor [MCP](https://modelcontextprotocol.io) construido con el SDK
oficial `mcp` (FastMCP) que expone, como *tools*, operaciones de **lectura, búsqueda y listado**
sobre los `.srt` que genera el transcriptor (sin estadísticas ni transformaciones).

Módulos: `srt_parser.py` (parser puro stdlib SRT→cues, sin dependencias, testeable aislado;
es el inverso de `fmt_srt_time()`/`write_output()` del transcriptor), `server.py` (instancia
FastMCP + tools), `__main__.py` (entrypoint `python -m srt_mcp`).

Tools (`ruta` es **opcional**: si se omite, se usa la env `SRT_MCP_DEFAULT_FILE`):
- `leer_srt(ruta=None, desde=0, limite=200, desde_seg=None, hasta_seg=None)` → cues estructurados
  (`indice`, `inicio`/`fin`, `inicio_seg`/`fin_seg`, `hablante`, `texto`), paginados y opcionalmente
  acotados a una ventana temporal.
- `buscar_srt(consulta, ruta=None, regex=False, ignorar_mayusculas=True, contexto=0, limite=50)` →
  cues coincidentes con timestamps y, opcionalmente, cues vecinos como contexto. (`consulta` es el
  primer parámetro porque `ruta` ahora tiene default.)
- `listar_srt(directorio=None)` → catálogo de `.srt` del directorio (explícito → `SRT_MCP_BASE_DIR`
  → carpeta de `SRT_MCP_DEFAULT_FILE`). Por fichero: `nombre`, `ruta` (= filename, lo que se pasa
  luego a `leer_srt`/`buscar_srt`), `tamano_bytes`, `num_cues`, `duracion`. Para descubrir qué
  plenos existen antes de leerlos.

Dos consumidores: **Claude Code** (vía `.mcp.json`, pasa `ruta` explícita) y el **analyzer**
(cliente MCP que arranca el servidor con `SRT_MCP_DEFAULT_FILE` + `SRT_MCP_BASE_DIR` y conserva
`ruta` en el esquema, para abrir cualquier pleno del catálogo).

Restricciones propias:
- **Python ≥3.10 en venv aparte (`.venv-mcp`)**: el SDK `mcp` exige 3.10+; no depende de
  torch/pyannote. Se puede usar `match/case` y sintaxis 3.10+. Se instala con `make install-mcp`
  (usa el `python3` del sistema, 3.10+). El analyzer arranca su propia copia del servidor con su
  intérprete (`.venv-analyzer`, que también trae `mcp`), así que `.venv-mcp` es solo para Claude Code.
- **Registro en Claude Code** vía `.mcp.json` (scope de proyecto) en la raíz, que lanza
  `${CLAUDE_PROJECT_DIR:-.}/.venv-mcp/bin/python -m srt_mcp` con `PYTHONPATH` al repo. Los paths
  usan `${CLAUDE_PROJECT_DIR:-.}` (la raíz del proyecto que Claude Code inyecta en el entorno del
  servidor; el `:-.` es el fallback) en vez de rutas absolutas, para que el fichero sea **portable
  entre clones**: por eso se commitea tal cual. VS Code marca `CLAUDE_PROJECT_DIR` como variable
  desconocida —falso positivo, la resuelve Claude Code en runtime, no el editor—. Tras
  `make install-mcp`, reiniciar Claude Code y aprobar el servidor `srt`.
- **`SRT_MCP_DEFAULT_FILE`** (env, opcional): fichero `.srt` por defecto cuando se llama a
  `leer_srt`/`buscar_srt` sin `ruta`. Si no hay ni `ruta` ni esta env, esas tools dan error claro.
  **Exento** de la contención de `SRT_MCP_BASE_DIR` (es un fichero ya aprobado).
- **`SRT_MCP_BASE_DIR`** (env, opcional): si se define, restringe a ese directorio las lecturas por
  una `ruta` dada por el llamante y es la carpeta por defecto de `listar_srt`. El analyzer la fija
  al catálogo (`ANALYZER_TRANSCRIPTS_DIR`).
- El prefijo `[HABLANTE]` que el writer antepone en SRT multi-hablante se separa al campo
  `hablante` (es `null` en SRT de un solo hablante, coherente con `write_output`).

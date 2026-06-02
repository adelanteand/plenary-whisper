# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Monorepo con dos componentes para trabajar con audios de plenos municipales en castellano:

- **`transcriber/`** — herramienta CLI de un solo script que transcribe + diariza audios
  largos usando Whisper (transcripción) + pyannote.audio (diarización de hablantes). Toda la
  lógica vive en `transcriber/transcribe_diarize.py`.
- **`analyzer/`** — chatbot que analiza las transcripciones generadas, construido con el
  Anthropic SDK siguiendo una arquitectura hub-spoke (un agente "hub" orquesta; los "spokes"
  especializados —aún por implementar— harán el trabajo concreto). Entrypoint:
  `python -m analyzer`. Ver `## Analyzer (chatbot)` más abajo.

Cada componente tiene su propio `requirements.txt`; comparten el venv 3.9 y el `.env` raíz.

## Comandos

- `make install` — instala las dependencias del transcriptor (`transcriber/requirements.txt`).
- `make install-analyzer` — instala las dependencias del chatbot (`analyzer/requirements.txt`).
- `make env` — crea `.env` desde `.env_template` (luego hay que rellenar `HF_TOKEN` y `ANTHROPIC_API_KEY`).
- `make download URL="https://...m3u8" OUTPUT=videos/pleno.mp4` — descarga/remux de un stream con ffmpeg (falla con error si ffmpeg no está instalado).
- Ejecución típica del transcriptor:
  `python transcriber/transcribe_diarize.py videos/pleno.mp4 --speakers 3`
- Iteración rápida (omite diarización, transcribe un solo fragmento):
  `python transcriber/transcribe_diarize.py videos/pleno.mp4 --debug-chunk 1`
- Chatbot de análisis (usa la transcripción de muestra por defecto):
  `python -m analyzer`

No hay tests ni linter configurados.

## Arquitectura (pipeline de 5 pasos en `main()`)

1. `convert_to_wav` → convierte a WAV mono 16 kHz, **cacheado** como `<stem>_16k_mono.wav` junto al archivo de origen; si existe se reutiliza (usa `--force-wav` para regenerarlo).
2. `split_audio` + `transcribe_chunks` → trocea el WAV en chunks de `--chunk-minutes` (temporales) y los transcribe con Whisper, sumando un offset global para recomponer los timestamps absolutos. **Dos niveles de caché**:
   - **Por-chunk** (reanudable): cada chunk se cachea individualmente en `<stem>_chunks/<modelo>_<idioma>_<chunk_minutes>min/chunk_NNN.json` según se transcribe. En re-ejecuciones los chunks ya hechos se reutilizan y solo se transcriben los que falten; si todos están cacheados, ni se carga el modelo Whisper (carga perezosa). La clave incluye `chunk_minutes` porque las fronteras de cada chunk dependen de ese parámetro. Usa `--force-chunks` para re-transcribir todos los chunks desde cero (implica saltar también el caché combinado).
   - **Combinado** (ruta rápida): el resultado completo se cachea en `<stem>_segments.json` (con modelo+idioma); en re-ejecuciones se reutiliza si coinciden, saltando split+transcripción por entero. Usa `--force-transcribe` para ignorarlo y reconstruirlo desde los chunks (reutilizando el caché por-chunk).
   
   El caché por-chunk evita perder el progreso si el proceso se interrumpe a mitad (crash, Ctrl-C, OOM); el combinado evita repetir todo cuando solo falla la diarización posterior. El modo `--debug-chunk` no usa el caché por-chunk (siempre transcribe fresco).
3. `diarize` → pyannote sobre el WAV completo; devuelve turnos de hablante.
4. `assign_speakers` → asigna hablante a cada segmento por mayor solapamiento temporal.
5. `write_output` → genera el TXT, el SRT sincronizado (salvo `--no-srt`), un JSON opcional y estadísticas de tiempo por hablante.

## Restricciones críticas (no romper)

- **Python 3.9.6**: el venv es 3.9. Por eso el script empieza con `from __future__ import annotations`, necesario para que la sintaxis `X | None` no rompa en 3.9. No lo quites.
- **`huggingface_hub<1.0`** (pin en `transcriber/requirements.txt`): pyannote.audio 3.4.0 llama internamente a `hf_hub_download(use_auth_token=...)`, kwarg eliminado en huggingface_hub 1.0. No actualices esa dependencia ni cambies el `use_auth_token=` en `diarize()`.
- **Idioma forzado a `es`** (flag `--language`, default `es`): el autodetect de Whisper fallaba (detectaba "Nynorsk") en silencios/aplausos. `--language auto` reactiva la detección automática.
- **`HF_TOKEN`** es obligatorio para la diarización y se carga de `.env` vía `load_dotenv()`. No se necesita con `--skip-diarization` ni con `--debug-chunk`.

## Analyzer (chatbot)

Paquete `analyzer/` — un asistente de terminal que analiza transcripciones de plenos con el
Anthropic SDK. Arquitectura **hub-spoke**: el `Orchestrator` ([analyzer/orchestrator.py](analyzer/orchestrator.py))
es el hub que mantiene el contexto y orquesta; los *spokes* (herramientas especializadas) viven
en `analyzer/spokes/` y se irán añadiendo (la iteración 1 es un **agente único** sin spokes).

Módulos: `config.py` (constantes + `.env`), `transcript.py` (ingestión de `.txt`/`.json`),
`prompts.py` (system prompt en castellano), `orchestrator.py` (hub), `repl.py` (bucle de chat),
`__main__.py` (entrypoint `python -m analyzer`).

Restricciones propias:
- **`ANTHROPIC_API_KEY`** obligatoria (en `.env`), leída por el SDK desde el entorno.
- Mismo **Python 3.9.6**: cada módulo empieza con `from __future__ import annotations`; sin
  `match/case`; sin `anthropic[mcp]` (exigen 3.10+).
- **Prompt caching**: la transcripción grande va en `system` con un breakpoint `cache_control`
  y el prefijo debe mantenerse **estable** entre turnos (nada de fecha/fichero dentro de
  `system`; los metadatos volátiles van en el primer mensaje `user`). No romper esa invariante.
- Modelo por defecto `claude-sonnet-4-6` (`ANALYZER_MODEL` / `--model` lo sobreescriben).

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Herramienta CLI de un solo script para transcribir + diarizar audios largos de plenos
municipales en castellano, usando Whisper (transcripción) + pyannote.audio (diarización de
hablantes). Toda la lógica vive en `scripts/transcribe_diarize.py`.

## Comandos

- `make install` — instala las dependencias de `requirements.txt`.
- `make env` — crea `.env` desde `.env_template` (luego hay que rellenar `HF_TOKEN`).
- `make download URL="https://...m3u8" OUTPUT=videos/pleno.mp4` — descarga/remux de un stream con ffmpeg (falla con error si ffmpeg no está instalado).
- Ejecución típica:
  `python scripts/transcribe_diarize.py videos/pleno.mp4 --speakers 3`
- Iteración rápida (omite diarización, transcribe un solo fragmento):
  `python scripts/transcribe_diarize.py videos/pleno.mp4 --debug-chunk 1`

No hay tests ni linter configurados.

## Arquitectura (pipeline de 5 pasos en `main()`)

1. `convert_to_wav` → convierte a WAV mono 16 kHz, **cacheado** como `<stem>_16k_mono.wav` junto al archivo de origen; si existe se reutiliza (usa `--force-wav` para regenerarlo).
2. `split_audio` + `transcribe_chunks` → trocea el WAV en chunks de `--chunk-minutes` (temporales) y los transcribe con Whisper, sumando un offset global para recomponer los timestamps absolutos. Los segmentos resultantes se **cachean** en `<stem>_segments.json` (con el modelo e idioma usados); en re-ejecuciones se reutilizan si modelo+idioma coinciden, saltando la transcripción (usa `--force-transcribe` para rehacerla). Esto evita repetir los ~12 min de transcripción cuando la diarización falla.
3. `diarize` → pyannote sobre el WAV completo; devuelve turnos de hablante.
4. `assign_speakers` → asigna hablante a cada segmento por mayor solapamiento temporal.
5. `write_output` → genera el TXT, el SRT sincronizado (salvo `--no-srt`), un JSON opcional y estadísticas de tiempo por hablante.

## Restricciones críticas (no romper)

- **Python 3.9.6**: el venv es 3.9. Por eso el script empieza con `from __future__ import annotations`, necesario para que la sintaxis `X | None` no rompa en 3.9. No lo quites.
- **`huggingface_hub<1.0`** (pin en `requirements.txt`): pyannote.audio 3.4.0 llama internamente a `hf_hub_download(use_auth_token=...)`, kwarg eliminado en huggingface_hub 1.0. No actualices esa dependencia ni cambies el `use_auth_token=` en `diarize()`.
- **Idioma forzado a `es`** (flag `--language`, default `es`): el autodetect de Whisper fallaba (detectaba "Nynorsk") en silencios/aplausos. `--language auto` reactiva la detección automática.
- **`HF_TOKEN`** es obligatorio para la diarización y se carga de `.env` vía `load_dotenv()`. No se necesita con `--skip-diarization` ni con `--debug-chunk`.

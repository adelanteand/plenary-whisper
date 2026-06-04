.PHONY: help install install-analyzer install-mcp analyzer mcp-serve env download transcribe diarize

.DEFAULT_GOAL := help

# URL del stream/archivo a descargar y ruta de salida.
# Uso: make download URL="https://..." OUTPUT=outputs/videos/pleno.mp4
URL ?=
OUTPUT ?= outputs/videos/descarga.mp4

# AUDIO: ruta al audio/vídeo a transcribir (mp3, wav, m4a, mp4, ogg...).
# Uso: make transcribe AUDIO=outputs/videos/pleno.mp4 ARGS="--speakers 3"
AUDIO ?=

# Argumentos opcionales (passthrough de flags al comando).
# TRANSCRIPT: ruta a la transcripción (.txt/.json); por defecto usa la muestra.
# ARGS:       flags extra, p. ej. ARGS="--model claude-opus-4-8 --debug"
# Uso: make analyzer  |  make analyzer TRANSCRIPT=outputs/videos/otro.txt ARGS="--debug"
TRANSCRIPT ?=
ARGS ?=

help: ## Muestra esta ayuda (lista de targets disponibles)
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Instala las dependencias del transcriptor
	python -m pip install -r transcriber/requirements.txt

install-analyzer: ## Crea el venv 3.10+ del chatbot (.venv-analyzer) e instala sus dependencias (incluye el SDK mcp)
	python3 -m venv .venv-analyzer
	.venv-analyzer/bin/pip install -r analyzer/requirements.txt

install-mcp: ## Crea el venv 3.10+ del servidor MCP de .srt e instala sus dependencias
	python3 -m venv .venv-mcp
	.venv-mcp/bin/pip install -r srt_mcp/requirements.txt

analyzer: ## Arranca el chatbot de análisis (vars: TRANSCRIPT, ARGS)
	.venv-analyzer/bin/python -m analyzer $(TRANSCRIPT) $(ARGS)

mcp-serve: ## Arranca el servidor MCP de .srt por stdio (requiere make install-mcp antes)
	.venv-mcp/bin/python -m srt_mcp

transcribe: ## Transcribe un audio con Whisper (añade --diarize en ARGS para identificar hablantes) (vars: AUDIO, ARGS)
	@if [ -z "$(AUDIO)" ]; then echo "[ERROR] Falta AUDIO. Uso: make transcribe AUDIO=outputs/videos/pleno.mp4 ARGS=\"--diarize --speakers 3\""; exit 1; fi
	python transcriber/transcribe_diarize.py "$(AUDIO)" $(ARGS)

diarize: ## Solo diarización (sin Whisper); cachea los turnos (vars: AUDIO, ARGS)
	@if [ -z "$(AUDIO)" ]; then echo "[ERROR] Falta AUDIO. Uso: make diarize AUDIO=outputs/videos/pleno.mp4 ARGS=\"--speakers 3\""; exit 1; fi
	python transcriber/transcribe_diarize.py "$(AUDIO)" --diarize-only $(ARGS)

download: ## Descarga/remux de un stream con ffmpeg (vars: URL, OUTPUT)
	@command -v ffmpeg >/dev/null 2>&1 || { echo "[ERROR] ffmpeg no está instalado. Instálalo con: brew install ffmpeg"; exit 1; }
	@if [ -z "$(URL)" ]; then echo "[ERROR] Falta URL. Uso: make download URL=\"https://...\" OUTPUT=outputs/videos/pleno.mp4"; exit 1; fi
	@mkdir -p $(dir $(OUTPUT))
	ffmpeg -i "$(URL)" -c copy "$(OUTPUT)"

env: ## Crea el .env desde .env_template (no sobrescribe si ya existe)
	@if [ -f .env ]; then \
		echo ".env ya existe, no se sobrescribe"; \
	else \
		cp .env_template .env && echo ".env creado desde .env_template — rellena HF_TOKEN"; \
	fi

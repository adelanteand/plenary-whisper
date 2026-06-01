.PHONY: help install install-analyzer analyzer env download

.DEFAULT_GOAL := help

# URL del stream/archivo a descargar y ruta de salida.
# Uso: make download URL="https://..." OUTPUT=videos/pleno.mp4
URL ?=
OUTPUT ?= videos/descarga.mp4

# Argumentos opcionales para el chatbot.
# TRANSCRIPT: ruta a la transcripción (.txt/.json); por defecto usa la muestra.
# ARGS:       flags extra, p. ej. ARGS="--model claude-opus-4-8 --debug"
# Uso: make analyzer  |  make analyzer TRANSCRIPT=videos/otro.txt ARGS="--debug"
TRANSCRIPT ?=
ARGS ?=

help: ## Muestra esta ayuda (lista de targets disponibles)
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Instala las dependencias del transcriptor
	python -m pip install -r transcriber/requirements.txt

install-analyzer: ## Instala las dependencias del chatbot (analyzer)
	python -m pip install -r analyzer/requirements.txt

analyzer: ## Arranca el chatbot de análisis (vars: TRANSCRIPT, ARGS)
	python -m analyzer $(TRANSCRIPT) $(ARGS)

download: ## Descarga/remux de un stream con ffmpeg (vars: URL, OUTPUT)
	@command -v ffmpeg >/dev/null 2>&1 || { echo "[ERROR] ffmpeg no está instalado. Instálalo con: brew install ffmpeg"; exit 1; }
	@if [ -z "$(URL)" ]; then echo "[ERROR] Falta URL. Uso: make download URL=\"https://...\" OUTPUT=videos/pleno.mp4"; exit 1; fi
	@mkdir -p $(dir $(OUTPUT))
	ffmpeg -i "$(URL)" -c copy "$(OUTPUT)"

env: ## Crea el .env desde .env_template (no sobrescribe si ya existe)
	@if [ -f .env ]; then \
		echo ".env ya existe, no se sobrescribe"; \
	else \
		cp .env_template .env && echo ".env creado desde .env_template — rellena HF_TOKEN"; \
	fi

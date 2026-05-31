.PHONY: install env download

# URL del stream/archivo a descargar y ruta de salida.
# Uso: make download URL="https://..." OUTPUT=videos/pleno.mp4
URL ?=
OUTPUT ?= videos/descarga.mp4

install:
	python -m pip install -r requirements.txt

download:
	@command -v ffmpeg >/dev/null 2>&1 || { echo "[ERROR] ffmpeg no está instalado. Instálalo con: brew install ffmpeg"; exit 1; }
	@if [ -z "$(URL)" ]; then echo "[ERROR] Falta URL. Uso: make download URL=\"https://...\" OUTPUT=videos/pleno.mp4"; exit 1; fi
	@mkdir -p $(dir $(OUTPUT))
	ffmpeg -i "$(URL)" -c copy "$(OUTPUT)"

env:
	@if [ -f .env ]; then \
		echo ".env ya existe, no se sobrescribe"; \
	else \
		cp .env_template .env && echo ".env creado desde .env_template — rellena HF_TOKEN"; \
	fi

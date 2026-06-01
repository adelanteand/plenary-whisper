"""Configuración y carga de entorno del asistente.

Constantes ajustables por variable de entorno y carga del `.env` raíz (donde
vive `ANTHROPIC_API_KEY`). Python 3.9: `from __future__ import annotations`.
"""

from __future__ import annotations

import os
import sys

# Carga el .env raíz si python-dotenv está disponible (busca hacia arriba desde el CWD).
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# Nombre del paquete (constante única para renombrar la carpeta con facilidad).
PACKAGE_NAME = "analyzer"

# Modelo por defecto. Sobreescribible con la variable ANALYZER_MODEL o el flag --model.
# El usuario eligió Sonnet 4.6 para iterar (1M de contexto, más barato que Opus).
DEFAULT_MODEL = "claude-sonnet-4-6"
MODEL = os.environ.get("ANALYZER_MODEL", DEFAULT_MODEL)

# Tope de tokens de salida por respuesta. Con streaming se podría subir hasta 64000.
MAX_TOKENS = int(os.environ.get("ANALYZER_MAX_TOKENS", "16000"))

# TTL del caché de prompt: "5m" (por defecto) o "1h" para sesiones con pausas largas.
CACHE_TTL = os.environ.get("ANALYZER_CACHE_TTL", "5m")

# Salvaguarda: si el contexto de la transcripción supera esto, avisamos (no truncamos).
MAX_TRANSCRIPT_TOKENS = int(os.environ.get("ANALYZER_MAX_TRANSCRIPT_TOKENS", "700000"))

# Transcripción cargada por defecto (la muestra existente del repo).
DEFAULT_TRANSCRIPT = os.environ.get(
    "ANALYZER_TRANSCRIPT", "videos/pleno_20_mayo_2026_transcripcion.txt"
)


def cache_control() -> dict:
    """Devuelve el bloque cache_control según CACHE_TTL ("5m" → ephemeral por defecto)."""
    if CACHE_TTL and CACHE_TTL.lower() not in ("5m", "5min", "ephemeral", ""):
        return {"type": "ephemeral", "ttl": CACHE_TTL}
    return {"type": "ephemeral"}


def require_api_key() -> str:
    """Devuelve ANTHROPIC_API_KEY o sale con un mensaje claro en castellano si falta.

    No imprime ni filtra la clave. El SDK la lee del entorno por su cuenta; esta
    comprobación solo sirve para dar un error legible antes de la primera llamada.
    """
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        sys.stderr.write(
            "\n[ERROR] Falta ANTHROPIC_API_KEY.\n"
            "  1. Crea el .env si no existe:  make env\n"
            "  2. Añade tu clave de API de Anthropic en el .env:\n"
            "       ANTHROPIC_API_KEY=sk-ant-...\n"
            "     (consíguela en https://console.anthropic.com/)\n\n"
        )
        sys.exit(1)
    return key

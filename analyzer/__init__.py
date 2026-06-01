"""analyzer — chatbot de análisis de transcripciones de plenos municipales.

Arquitectura hub-spoke construida sobre el Anthropic SDK. El `Orchestrator`
(hub) mantiene el contexto de la transcripción y orquesta la conversación; los
spokes (herramientas especializadas) viven en `analyzer.spokes` y se irán
añadiendo en iteraciones posteriores. La iteración 1 es un agente único.

Punto de entrada: `python -m analyzer`.
"""

from __future__ import annotations

__all__ = ["__version__"]
__version__ = "0.1.0"

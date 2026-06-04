"""Servidor MCP para operaciones sobre ficheros .srt de plenos municipales.

Expone como *tools* MCP (vía el SDK oficial `mcp`/FastMCP) operaciones de lectura y
búsqueda sobre los subtítulos `.srt` que genera el transcriptor del proyecto.

IMPORTANTE: este componente corre en su PROPIO venv con Python ≥3.10 (el SDK `mcp` lo
exige), separado del `.venv` 3.9 del transcriber. Ver el README y el CLAUDE.md del paquete.
"""

from __future__ import annotations

__version__ = "0.1.0"

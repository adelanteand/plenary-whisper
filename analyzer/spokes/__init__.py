"""Spokes — herramientas especializadas que el hub orquestará (hub-spoke).

Un spoke puede ser **externo** (un servidor MCP) o **in-process** (un módulo Python).

Las tools de SRT (`buscar_srt`, `leer_srt`) son ahora un **spoke externo**: las provee el
servidor MCP `srt_mcp/` y el hub las consume como cliente MCP real (ver
`analyzer/mcp_client.py`). Por eso ya no hay un `srt_tools.py` aquí: el analyzer no
reimplementa ni importa esa lógica, habla el protocolo MCP.

Este paquete queda reservado para futuros spokes **in-process** sobre el contexto ya
cargado (p. ej. sobre los segmentos JSON):

- estadisticas_hablantes  → tiempo/turnos por hablante (is_error si no está diarizada).
- extraer_orden_del_dia   → detecta "Punto número N, ..." con su marca de tiempo.
- resumir_por_punto       → resume intervenciones/acuerdos de un punto del orden del día.

Cualquier tool que se exponga al modelo debe definirse de forma determinista y ordenarse
por nombre para no invalidar el prefijo de caché del hub.
"""

from __future__ import annotations

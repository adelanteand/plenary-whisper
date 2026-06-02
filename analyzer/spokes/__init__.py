"""Spokes — herramientas especializadas que el hub orquestará (hub-spoke).

Vacío en la iteración 1 (agente único). En la iteración 2 vivirán aquí las
definiciones de tool-use, p. ej.:

- estadisticas_hablantes  → tiempo/turnos por hablante sobre los segmentos JSON
                            (is_error si la transcripción no está diarizada).
- extraer_orden_del_dia   → detecta "Punto número N, ..." con su marca de tiempo.
- buscar_citas            → fragmentos textuales con [H:MM:SS] para citar.
- resumir_por_punto       → resume intervenciones/acuerdos de un punto del orden del día.

Deben definirse de forma determinista y ordenarse por nombre para no invalidar
el prefijo de caché del hub.
"""

from __future__ import annotations

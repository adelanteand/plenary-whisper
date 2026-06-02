"""El hub: mantiene el contexto, hace prompt caching, streaming e historial.

Iteración 1 = agente único (una llamada al modelo por turno). La costura
hub-spoke (tool-use) está documentada al final pero no implementada todavía.

Prompt caching (invariante de prefijo estable):
- `system` es una lista de dos bloques: [marco estable] + [transcripción] con un
  breakpoint `cache_control` en el bloque de la transcripción.
- Breakpoint rodante: en cada turno se coloca un segundo breakpoint en el último
  bloque del último mensaje de usuario, de forma que el historial previo se sirve
  de caché y solo se paga a precio completo la última respuesta + la nueva pregunta.
- Total: 2 breakpoints (máximo permitido: 4). Los metadatos volátiles (fichero,
  fecha) van en el PRIMER mensaje de usuario, nunca dentro de `system`.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

import anthropic

from . import config, prompts
from .spinner import Spinner


class Orchestrator:
    """Hub que orquesta la conversación sobre una transcripción."""

    def __init__(self, client: anthropic.Anthropic, transcript, model: Optional[str] = None,
                 debug: bool = False) -> None:
        self.client = client
        self.transcript = transcript
        self.model = model or config.MODEL
        self.debug = debug
        self.messages: List[dict] = []
        self._first_turn = True
        self.system = self._build_system()
        # Uso acumulado de tokens en la sesión.
        self.usage_totals = {
            "input": 0, "output": 0, "cache_read": 0, "cache_creation": 0,
        }
        self.last_usage: Optional[dict] = None

    # ── construcción del system (prefijo estable + transcripción cacheada) ──
    def _build_system(self) -> List[dict]:
        return [
            {"type": "text", "text": prompts.SYSTEM_PROMPT},
            {
                "type": "text",
                "text": prompts.transcript_system_text(self.transcript),
                "cache_control": config.cache_control(),
            },
        ]

    def _system_plain(self) -> List[dict]:
        """system sin cache_control (para count_tokens, que no acepta el campo)."""
        return [{"type": "text", "text": b["text"]} for b in self.system]

    def _metadata_preamble(self) -> str:
        """Metadatos volátiles para el PRIMER mensaje de usuario (no van en system)."""
        t = self.transcript
        if t.speakers:
            hablantes = "{} hablante(s) identificado(s): {}".format(
                len(t.speakers), ", ".join(t.speakers)
            )
        else:
            hablantes = "sin diarización (hablantes no identificados)"
        return (
            "[Contexto de la sesión — fichero: {}; formato: {}; {}; "
            "fecha de hoy: {}]\n\n".format(
                t.path.name, t.source_format, hablantes, date.today().isoformat()
            )
        )

    # ── salvaguarda de tamaño (no truncar en silencio) ──
    def count_context_tokens(self) -> int:
        """Tokens del contexto (system + un mensaje mínimo) vía la API de conteo."""
        resp = self.client.messages.count_tokens(
            model=self.model,
            system=self._system_plain(),
            messages=[{"role": "user", "content": "."}],
        )
        return resp.input_tokens

    # ── breakpoint rodante: cachea el historial hasta el último turno de usuario ──
    def _messages_for_request(self) -> List[dict]:
        if not self.messages:
            return self.messages
        out = list(self.messages[:-1])
        last = self.messages[-1]
        content = last["content"]
        if isinstance(content, list) and content and isinstance(content[-1], dict):
            new_content = list(content[:-1])
            tail = dict(content[-1])
            tail["cache_control"] = config.cache_control()
            new_content.append(tail)
            out.append({"role": last["role"], "content": new_content})
        else:
            out.append(last)
        return out

    def _record_usage(self, usage) -> None:
        cr = getattr(usage, "cache_read_input_tokens", 0) or 0
        cc = getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.last_usage = {
            "input": usage.input_tokens,
            "output": usage.output_tokens,
            "cache_read": cr,
            "cache_creation": cc,
        }
        self.usage_totals["input"] += usage.input_tokens
        self.usage_totals["output"] += usage.output_tokens
        self.usage_totals["cache_read"] += cr
        self.usage_totals["cache_creation"] += cc

    # ── turno de conversación ──
    def ask(self, user_text: str) -> bool:
        """Envía una pregunta, hace streaming de la respuesta y actualiza el historial.

        Devuelve True si el turno se completó; False si hubo un error de API
        (el mensaje de usuario se descarta para no dejar el historial a medias).
        """
        blocks: List[dict] = []
        if self._first_turn:
            blocks.append({"type": "text", "text": self._metadata_preamble()})
        blocks.append({"type": "text", "text": user_text})
        self.messages.append({"role": "user", "content": blocks})

        spinner = Spinner("Pensando")
        spinner.start()
        first_token = True
        try:
            with self.client.messages.stream(
                model=self.model,
                max_tokens=config.MAX_TOKENS,
                system=self.system,
                messages=self._messages_for_request(),
            ) as stream:
                for text in stream.text_stream:
                    if first_token:
                        spinner.stop()  # primer token → fuera el spinner
                        first_token = False
                    print(text, end="", flush=True)
                final = stream.get_final_message()
            spinner.stop()  # por si la respuesta no tuvo tokens de texto
            print()
        except anthropic.APIConnectionError:
            spinner.stop()
            self.messages.pop()
            print("[Error de conexión con la API. Revisa tu red e inténtalo de nuevo.]")
            return False
        except anthropic.RateLimitError:
            spinner.stop()
            self.messages.pop()
            print("[Límite de peticiones alcanzado. Espera unos segundos y reinténtalo.]")
            return False
        except anthropic.APIStatusError as e:
            spinner.stop()
            self.messages.pop()
            print("[Error de la API ({}): {}]".format(e.status_code, e.message))
            return False

        # El historial guarda el contenido COMPLETO de la respuesta (no solo el texto)
        # para que la futura iteración con tool-use sea aditiva.
        self.messages.append({"role": "assistant", "content": final.content})
        self._first_turn = False
        self._record_usage(final.usage)
        return True


# ── COSTURA HUB-SPOKE (iteración 2, NO implementada aquí) ─────────────────────
# El salto a hub-spoke es aditivo: definir las herramientas (spokes) en
# analyzer/spokes/, deterministas y ordenadas por nombre (para no invalidar el
# prefijo de caché), pasarlas como `tools=[...]` en `messages.stream(...)`, y
# tras `get_final_message()` ejecutar el bucle de tool-use: si
# `final.stop_reason == "tool_use"`, añadir `final.content` al historial,
# ejecutar cada bloque tool_use, devolver los `tool_result` (con su tool_use_id)
# como mensaje de usuario, y repetir hasta `end_turn`.

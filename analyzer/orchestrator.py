"""El hub: mantiene el contexto, hace prompt caching, streaming, tool-use e historial.

Iteración 2 = hub-spoke con tool-use. Si hay un .srt asociado a la transcripción, el
hub arranca el servidor MCP `srt_mcp` (vía `analyzer/mcp_client.py`, cliente MCP real por
stdio) y expone sus tools (`buscar_srt`, `leer_srt`) al modelo. Cuando el modelo las
invoca (`stop_reason == "tool_use"`), el hub las enruta al servidor por el protocolo MCP
y le devuelve los `tool_result`, repitiendo hasta `end_turn`. Sin .srt (o si el servidor
no arranca), se comporta como un agente único. El analyzer NO importa el paquete del
servidor: todo el acceso al .srt pasa por el protocolo MCP.

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

import json
from datetime import date
from pathlib import Path
from typing import List, Optional

import anthropic

from . import config, prompts
from .mcp_client import SrtMcpClient
from .spinner import Spinner
from .transcript import sibling_srt


class Orchestrator:
    """Hub que orquesta la conversación sobre una transcripción."""

    def __init__(self, client: anthropic.Anthropic, transcript, model: Optional[str] = None,
                 debug: bool = False, srt_path: Optional[str] = None) -> None:
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

        # ── tool-use vía MCP: arranca el servidor srt_mcp como subproceso ──
        # El set de tools queda fijo durante la sesión (prefijo de caché estable).
        self.srt_path: Optional[Path] = None
        self.mcp: Optional[SrtMcpClient] = None
        self.tools: List[dict] = []
        resolved = Path(srt_path) if srt_path else sibling_srt(transcript.path)
        default_srt = resolved if (resolved is not None and resolved.exists()) else None
        catalog_dir = Path(config.TRANSCRIPTS_DIR).resolve()
        catalog_ok = catalog_dir.is_dir()
        # Arrancamos el servidor si hay un .srt por defecto O un catálogo que listar: así el
        # agente puede `listar_srt` y abrir plenos por `ruta` aun sin pleno precargado.
        if default_srt is not None or catalog_ok:
            client_mcp = SrtMcpClient(default_srt, base_dir=catalog_dir if catalog_ok else None)
            try:
                client_mcp.start()
                self.mcp = client_mcp
                self.srt_path = default_srt
                self.tools = client_mcp.tools_for_anthropic()
            except Exception:
                # Si el servidor MCP no arranca, degradamos a agente único (sin tools).
                client_mcp.close()
                self.mcp = None
                self.tools = []

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

    def _accumulate(self, acc: dict, usage) -> None:
        """Suma el uso de una llamada en `acc` (turno) y en `usage_totals` (sesión).

        Un turno puede tener varias llamadas (ronda inicial + una por cada vuelta de
        tool-use); por eso se acumula en vez de sobrescribir.
        """
        vals = {
            "input": usage.input_tokens,
            "output": usage.output_tokens,
            "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
            "cache_creation": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        }
        for k, v in vals.items():
            acc[k] += v
            self.usage_totals[k] += v

    # ── ejecución de tools (enrutadas al servidor MCP) ──
    def _run_tools(self, content) -> List[dict]:
        """Ejecuta los bloques tool_use de una respuesta y devuelve sus tool_result."""
        resultados: List[dict] = []
        for block in content:
            if getattr(block, "type", None) != "tool_use":
                continue
            entrada = block.input or {}
            if self.mcp is not None:
                salida, is_error = self.mcp.call(block.name, entrada)
            else:
                salida, is_error = ("Herramienta no disponible (sin servidor MCP).", True)
            self._print_tool_call(block.name, entrada, salida, is_error)
            resultados.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": salida,
                "is_error": is_error,
            })
        return resultados

    def _print_tool_call(self, nombre, entrada, salida, is_error) -> None:
        """Indicador conciso de que se ha usado una tool (transparencia para el usuario)."""
        if is_error:
            resumen = "error"
        else:
            resumen = ""
            try:
                data = json.loads(salida)
                if "total_coincidencias" in data:
                    resumen = "{} coincidencia(s)".format(data["total_coincidencias"])
                elif "transcripciones" in data:
                    resumen = "{} transcripción(es)".format(data.get("total", 0))
                elif "total_cues" in data:
                    resumen = "{} cue(s)".format(data.get("devueltos", 0))
            except (ValueError, TypeError):
                pass
        consulta = entrada.get("consulta")
        detalle = ' "{}"'.format(consulta) if consulta else ""
        print("  ↳ [{}]{} → {}".format(nombre, detalle, resumen))

    # ── turno de conversación (con bucle de tool-use) ──
    def ask(self, user_text: str) -> bool:
        """Envía una pregunta, hace streaming, resuelve tool-use y actualiza el historial.

        Devuelve True si el turno se completó; False si hubo un error de API (en cuyo
        caso se revierte el historial al estado previo al turno, para no dejarlo a medias).
        """
        start_len = len(self.messages)  # punto de rollback si la API falla
        blocks: List[dict] = []
        if self._first_turn:
            blocks.append({"type": "text", "text": self._metadata_preamble()})
        blocks.append({"type": "text", "text": user_text})
        self.messages.append({"role": "user", "content": blocks})

        turn_usage = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
        stream_kwargs = {
            "model": self.model,
            "max_tokens": config.MAX_TOKENS,
            "system": self.system,
        }
        if self.tools:
            stream_kwargs["tools"] = self.tools

        while True:
            spinner = Spinner("Pensando")
            spinner.start()
            first_token = True
            try:
                with self.client.messages.stream(
                    messages=self._messages_for_request(),
                    **stream_kwargs,
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
                del self.messages[start_len:]
                print("[Error de conexión con la API. Revisa tu red e inténtalo de nuevo.]")
                return False
            except anthropic.RateLimitError:
                spinner.stop()
                del self.messages[start_len:]
                print("[Límite de peticiones alcanzado. Espera unos segundos y reinténtalo.]")
                return False
            except anthropic.APIStatusError as e:
                spinner.stop()
                del self.messages[start_len:]
                print("[Error de la API ({}): {}]".format(e.status_code, e.message))
                return False

            # El historial guarda el contenido COMPLETO (texto + bloques tool_use).
            self.messages.append({"role": "assistant", "content": final.content})
            self._accumulate(turn_usage, final.usage)

            if final.stop_reason != "tool_use":
                break

            # El modelo pidió herramientas: ejecútalas y devuelve los resultados.
            tool_results = self._run_tools(final.content)
            self.messages.append({"role": "user", "content": tool_results})

        self._first_turn = False
        self.last_usage = turn_usage
        return True

    # ── cierre de recursos ──
    def close(self) -> None:
        """Cierra el cliente MCP (subproceso del servidor srt) si está activo."""
        if self.mcp is not None:
            self.mcp.close()
            self.mcp = None

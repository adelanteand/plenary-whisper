"""Bucle de chat en terminal (REPL) en castellano.

Comandos: /ayuda, /tokens, /salir. Maneja Ctrl-C y EOF sin reventar.
"""

from __future__ import annotations

from . import config

_BANNER = """\
══════════════════════════════════════════════════════════════
  Asistente de análisis de plenos
══════════════════════════════════════════════════════════════
  Transcripción : {path}
  Formato       : {fmt}
  Hablantes     : {speakers}
  Modelo        : {model}
  Contexto      : {tokens}
──────────────────────────────────────────────────────────────
  Pregunta en lenguaje natural sobre el pleno.
  Comandos: /ayuda · /tokens · /salir
══════════════════════════════════════════════════════════════
"""

_AYUDA = """\
Comandos disponibles:
  /ayuda    Muestra esta ayuda.
  /tokens   Muestra el uso de tokens acumulado en la sesión.
  /salir    Termina la sesión (también: /exit, /quit, Ctrl-D en Unix / Ctrl-Z+Enter en Windows).

Ejemplos de preguntas:
  ¿Cuáles son los puntos del orden del día de este pleno?
  Resume las intervenciones sobre el presupuesto.
  ¿En qué momento se aprueba el acta de la sesión anterior?
"""


def _format_tokens(n: int) -> str:
    if n is None:
        return "(no calculado)"
    return "{} tokens (~{}k)".format(n, round(n / 1000))


def _print_usage(orch) -> None:
    t = orch.usage_totals
    print(
        "── Uso acumulado ──\n"
        "  entrada (sin caché): {input}\n"
        "  leído de caché:      {cache_read}\n"
        "  escrito en caché:    {cache_creation}\n"
        "  salida:              {output}".format(**t)
    )


def run_repl(orch, transcript, debug: bool = False, context_tokens=None) -> None:
    speakers = (
        ", ".join(transcript.speakers) if transcript.speakers
        else "sin diarización"
    )
    print(_BANNER.format(
        path=transcript.path,
        fmt=transcript.source_format,
        speakers=speakers,
        model=orch.model,
        tokens=_format_tokens(context_tokens),
    ))

    while True:
        try:
            user_text = input("\n› ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n¡Hasta luego!")
            return

        if not user_text:
            continue

        low = user_text.lower()
        if low in ("/salir", "/exit", "/quit"):
            print("¡Hasta luego!")
            return
        if low == "/ayuda":
            print(_AYUDA)
            continue
        if low == "/tokens":
            _print_usage(orch)
            continue

        print()  # separación antes de la respuesta en streaming
        ok = orch.ask(user_text)
        if ok and debug and orch.last_usage:
            u = orch.last_usage
            print(
                "\n[debug] entrada={input} caché_leído={cache_read} "
                "caché_escrito={cache_creation} salida={output}".format(**u)
            )

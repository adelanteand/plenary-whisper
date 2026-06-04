"""Punto de entrada del asistente:  python -m analyzer [transcripción] [--model M] [--debug]

Carga la transcripción, crea el cliente de Anthropic, comprueba el tamaño del
contexto (salvaguarda) y arranca el REPL.
"""

from __future__ import annotations

import argparse
import sys

import anthropic

from . import config
from .orchestrator import Orchestrator
from .repl import run_repl
from .spinner import Spinner
from .transcript import load_transcript


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m analyzer",
        description="Chatbot de análisis de transcripciones de plenos (Anthropic SDK).",
    )
    parser.add_argument(
        "transcript",
        nargs="?",
        default=config.DEFAULT_TRANSCRIPT,
        help="Ruta a la transcripción (.txt o .json). "
             "Por defecto: {}".format(config.DEFAULT_TRANSCRIPT),
    )
    parser.add_argument(
        "--model",
        default=config.MODEL,
        help="Modelo de Claude a usar (por defecto: {}).".format(config.MODEL),
    )
    parser.add_argument(
        "--srt",
        default=config.DEFAULT_SRT or None,
        help="Ruta al .srt para las herramientas de cita. Por defecto se deriva del "
             "transcript cargado (su .srt hermano).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Muestra el uso de tokens (incl. aciertos de caché) tras cada turno.",
    )
    args = parser.parse_args()

    # Salida UTF-8 + VT/ANSI antes de imprimir el banner/spinner (clave en Windows).
    config.configure_console()

    config.require_api_key()

    try:
        transcript = load_transcript(args.transcript)
    except (FileNotFoundError, ValueError) as e:
        sys.stderr.write("[ERROR] {}\n".format(e))
        sys.exit(1)

    client = anthropic.Anthropic()
    orch = Orchestrator(client, transcript, model=args.model, debug=args.debug,
                        srt_path=args.srt)

    # Salvaguarda de tamaño: contar tokens del contexto antes del primer turno.
    context_tokens = None
    try:
        with Spinner("Calculando el tamaño del contexto"):
            context_tokens = orch.count_context_tokens()
        if context_tokens > config.MAX_TRANSCRIPT_TOKENS:
            sys.stderr.write(
                "\n[AVISO] El contexto de la transcripción ocupa ~{} tokens, por "
                "encima del umbral de {}.\nLas respuestas pueden fallar o ser caras. "
                "Opciones: usar el .txt en vez del .json, recortar la transcripción "
                "por rango temporal, o resumirla.\n\n".format(
                    context_tokens, config.MAX_TRANSCRIPT_TOKENS
                )
            )
    except anthropic.APIError as e:
        sys.stderr.write(
            "[AVISO] No se pudo contar el contexto ({}). Continúo igualmente.\n".format(e)
        )

    try:
        run_repl(orch, transcript, debug=args.debug, context_tokens=context_tokens)
    finally:
        # Reapea el subproceso del servidor MCP en salida normal, Ctrl-C/EOF o error.
        orch.close()


if __name__ == "__main__":
    main()

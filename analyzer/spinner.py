"""Spinner de terminal para indicar que el asistente está "pensando".

Gira en un hilo aparte mientras se espera (p. ej. hasta que llega el primer
token del streaming) y limpia su línea al detenerse. Si la salida no es una
terminal interactiva (tests, salida redirigida), no hace nada — así no ensucia
los logs ni los smoke tests.
"""

from __future__ import annotations

import itertools
import sys
import threading
import time
from typing import Optional


class Spinner:
    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, message: str = "Pensando", stream=None, interval: float = 0.08) -> None:
        self.message = message
        self.stream = stream if stream is not None else sys.stdout
        self.interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _spin(self) -> None:
        for frame in itertools.cycle(self.FRAMES):
            if self._stop.is_set():
                break
            self.stream.write("\r{} {}… ".format(frame, self.message))
            self.stream.flush()
            time.sleep(self.interval)

    def start(self) -> "Spinner":
        # Solo animamos en una terminal interactiva.
        if not getattr(self.stream, "isatty", lambda: False)():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join()
        self._thread = None
        # Borra la línea del spinner y deja el cursor al principio.
        self.stream.write("\r\033[K")
        self.stream.flush()

    def __enter__(self) -> "Spinner":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

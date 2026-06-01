"""Ingestión de transcripciones (.txt o .json) hacia un objeto `Transcript`.

- `.txt`: el formato legible que genera el transcriptor (`[H:MM:SS] HABLANTE:`
  seguido de líneas indentadas). Se usa tal cual como contexto.
- `.json`: el `_segments.json` estructurado (`{model, language, segments:[...]}`).
  Se renderiza al mismo formato legible para el contexto del hub y se conservan
  los segmentos crudos aparte (para los spokes cuantitativos futuros).

Degrada con elegancia cuando no hay diarización: si todos los hablantes son la
etiqueta genérica, `speakers` queda vacía para que el prompt avise al modelo.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import List, Optional

# Etiquetas que el transcriptor usa cuando NO hubo diarización real.
_PLACEHOLDER_SPEAKERS = {"HABLANTE", "DESCONOCIDO"}

# Cabecera de turno en el .txt: "[0:05:06] SPEAKER_02:"
_HEADER_RE = re.compile(r"^\[(\d+:\d{2}:\d{2})\]\s+(.+):\s*$")


@dataclass
class Transcript:
    """Una transcripción cargada, lista para alimentar al hub y a los spokes."""

    path: Path
    text: str                              # versión legible (contexto del hub)
    source_format: str                     # "txt" | "json"
    segments: Optional[List[dict]] = None  # crudos si vino de JSON; si no, None
    speakers: List[str] = field(default_factory=list)  # vacía si no hubo diarización


def _fmt_time(seconds: float) -> str:
    """Segundos → H:MM:SS (idéntico al transcriptor, vía timedelta)."""
    return str(timedelta(seconds=int(seconds)))


def _real_speakers(names: set) -> List[str]:
    """Filtra las etiquetas-placeholder; devuelve la lista ordenada de hablantes reales."""
    real = {n for n in names if n and n not in _PLACEHOLDER_SPEAKERS}
    return sorted(real)


def render_segments_to_text(segments: List[dict]) -> str:
    """Renderiza segmentos JSON al mismo formato legible que el .txt del transcriptor."""
    lines: List[str] = []
    prev_speaker = None
    for seg in segments:
        speaker = seg.get("speaker", "HABLANTE")
        ts = _fmt_time(seg.get("start", 0.0))
        if speaker != prev_speaker:
            lines.append("\n[{}] {}:".format(ts, speaker))
            prev_speaker = speaker
        lines.append("  {}".format((seg.get("text") or "").strip()))
    return "\n".join(lines)


def summarize_speakers(segments: List[dict]) -> dict:
    """Tiempo total (segundos) por hablante. Útil para un spoke cuantitativo futuro."""
    totals: dict = {}
    for seg in segments:
        sp = seg.get("speaker", "HABLANTE")
        dur = float(seg.get("end", 0.0)) - float(seg.get("start", 0.0))
        totals[sp] = totals.get(sp, 0.0) + max(0.0, dur)
    return totals


def _load_txt(path: Path) -> Transcript:
    text = path.read_text(encoding="utf-8")
    names = set()
    for line in text.splitlines():
        m = _HEADER_RE.match(line)
        if m:
            names.add(m.group(2).strip())
    return Transcript(
        path=path,
        text=text,
        source_format="txt",
        segments=None,
        speakers=_real_speakers(names),
    )


def _load_json(path: Path) -> Transcript:
    data = json.loads(path.read_text(encoding="utf-8"))
    segments = data.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError(
            "El JSON '{}' no contiene una lista 'segments' utilizable.".format(path.name)
        )
    names = {seg.get("speaker") for seg in segments if seg.get("speaker")}
    return Transcript(
        path=path,
        text=render_segments_to_text(segments),
        source_format="json",
        segments=segments,
        speakers=_real_speakers(names),
    )


def load_transcript(path) -> Transcript:
    """Carga una transcripción .txt o .json. Lanza FileNotFoundError/ValueError si falla."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError("No se encontró la transcripción: {}".format(p))
    suffix = p.suffix.lower()
    if suffix == ".json":
        return _load_json(p)
    # Por defecto tratamos cualquier otra extensión como texto plano.
    return _load_txt(p)

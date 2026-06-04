"""Parser puro (stdlib) de ficheros .srt → cues estructurados.

Es el **inverso** de `fmt_srt_time()` / `write_output()` del transcriptor
(`transcriber/transcribe_diarize.py`): reconstruye los segundos a partir del formato
`HH:MM:SS,mmm` y separa el prefijo `[HABLANTE]` que el writer antepone al texto cuando
la diarización detecta más de un hablante.

No depende de `mcp` ni de nada externo, así que se puede testear de forma aislada:

    from srt_mcp.srt_parser import parse_srt_file
    cues = parse_srt_file("outputs/videos/pleno_11_mayo_2026_transcripcion.srt")
"""

from __future__ import annotations

import re
from pathlib import Path

# Línea de tiempos de un cue SRT: "HH:MM:SS,mmm --> HH:MM:SS,mmm".
_TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)

# Prefijo de hablante que añade write_output() en SRT multi-hablante: "[NOMBRE] texto...".
_SPEAKER_RE = re.compile(r"^\[([^\]]+)\]\s*(.*)$", re.DOTALL)


def srt_time_to_seconds(t: str) -> float:
    """Convierte un timestamp SRT ("00:01:23,456") a segundos (83.456).

    Acepta tanto la coma estándar de SRT como el punto, por robustez. Lanza
    ValueError si el formato no es válido.
    """
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*", t)
    if not m:
        raise ValueError("Timestamp SRT inválido: {!r}".format(t))
    h, mn, s, ms = (int(g) for g in m.groups())
    return h * 3600 + mn * 60 + s + ms / 1000.0


def _parse_speaker(text: str) -> tuple[str | None, str]:
    """Separa el prefijo "[HABLANTE]" del texto, si existe.

    Devuelve (hablante|None, texto_sin_prefijo). El writer solo antepone el prefijo
    cuando hay diarización multi-hablante; en single-speaker no lo hay → hablante None.
    """
    m = _SPEAKER_RE.match(text)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None, text.strip()


def parse_srt_text(content: str) -> list[dict]:
    """Parsea el contenido de un .srt a una lista de cues estructurados.

    Cada cue es un dict JSON-serializable con claves en castellano:
        indice (int), inicio (str HH:MM:SS,mmm), fin (str), inicio_seg (float),
        fin_seg (float), hablante (str|None), texto (str sin el prefijo de hablante).

    Es tolerante: ignora bloques sin línea de tiempos válida y normaliza saltos de
    línea CRLF/CR. El `indice` devuelto es el del propio fichero (no se renumera).
    """
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    cues: list[dict] = []
    # Los cues se separan por una o más líneas en blanco.
    for block in re.split(r"\n\s*\n", normalized):
        lines = [ln for ln in block.split("\n") if ln.strip() != ""]
        if not lines:
            continue
        # Localiza la línea de tiempos (normalmente la 1ª o la 2ª, tras el índice).
        time_idx = next((i for i, ln in enumerate(lines) if _TIME_RE.search(ln)), None)
        if time_idx is None:
            continue  # bloque sin timing válido → se ignora
        tm = _TIME_RE.search(lines[time_idx])
        inicio = "{}:{}:{},{}".format(*tm.group(1, 2, 3, 4))
        fin = "{}:{}:{},{}".format(*tm.group(5, 6, 7, 8))

        # El índice es la línea anterior a los tiempos, si es numérica.
        indice = len(cues) + 1
        if time_idx > 0 and lines[time_idx - 1].strip().isdigit():
            indice = int(lines[time_idx - 1].strip())

        texto_crudo = "\n".join(lines[time_idx + 1 :]).strip()
        hablante, texto = _parse_speaker(texto_crudo)
        cues.append(
            {
                "indice": indice,
                "inicio": inicio,
                "fin": fin,
                "inicio_seg": round(srt_time_to_seconds(inicio), 3),
                "fin_seg": round(srt_time_to_seconds(fin), 3),
                "hablante": hablante,
                "texto": texto,
            }
        )
    return cues


def parse_srt_file(path) -> list[dict]:
    """Lee un .srt en UTF-8 y lo parsea con parse_srt_text().

    Lanza FileNotFoundError si no existe.
    """
    p = Path(path)
    return parse_srt_text(p.read_text(encoding="utf-8"))


# ── Operaciones sobre cues ya parseados ───────────────────────────────────────
# Funciones puras que respaldan las tools del servidor MCP (srt_mcp/server.py). El
# analyzer NO las importa: habla con el servidor por el protocolo MCP (ver
# analyzer/mcp_client.py), así que esta lógica vive en un único sitio, el servidor.

# Tope defensivo de cues/coincidencias por respuesta (los plenos producen miles de
# cues y devolverlos todos saturaría el contexto del cliente).
_MAX_LIMITE = 1000


def buscar_en_cues(
    cues: list[dict],
    consulta: str,
    regex: bool = False,
    ignorar_mayusculas: bool = True,
    contexto: int = 0,
    limite: int = 50,
) -> dict:
    """Busca texto en una lista de cues y devuelve las coincidencias con timestamps.

    Por defecto la búsqueda es por subcadena (con `regex=True` se interpreta como
    expresión regular). Si `contexto>0`, cada coincidencia incluye `contexto_previo`
    y `contexto_posterior` (listas de cues vecinos). Lanza ValueError si la consulta
    está vacía o el patrón regex es inválido.
    """
    if not consulta:
        raise ValueError("La consulta no puede estar vacía.")
    flags = re.IGNORECASE if ignorar_mayusculas else 0
    patron = consulta if regex else re.escape(consulta)
    try:
        compilado = re.compile(patron, flags)
    except re.error as exc:
        raise ValueError("Expresión regular inválida: {}".format(exc))

    contexto = max(0, int(contexto))
    limite = max(1, min(int(limite), _MAX_LIMITE))

    posiciones = [i for i, c in enumerate(cues) if compilado.search(c["texto"])]
    coincidencias = []
    for i in posiciones[:limite]:
        item = dict(cues[i])
        if contexto > 0:
            item["contexto_previo"] = cues[max(0, i - contexto) : i]
            item["contexto_posterior"] = cues[i + 1 : i + 1 + contexto]
        coincidencias.append(item)

    return {
        "total_coincidencias": len(posiciones),
        "devueltas": len(coincidencias),
        "coincidencias": coincidencias,
    }


def leer_cues(
    cues: list[dict],
    desde: int = 0,
    limite: int = 200,
    desde_seg: float | None = None,
    hasta_seg: float | None = None,
) -> dict:
    """Devuelve un tramo de cues, paginado por `desde`/`limite`.

    Si se pasan `desde_seg`/`hasta_seg` (segundos), primero filtra los cues que
    solapan esa ventana temporal y luego pagina sobre el resultado. `total_cues`
    refleja el total tras el filtro temporal (o el total del fichero si no hay filtro).
    """
    seleccion = cues
    if desde_seg is not None or hasta_seg is not None:
        lo = float(desde_seg) if desde_seg is not None else float("-inf")
        hi = float(hasta_seg) if hasta_seg is not None else float("inf")
        seleccion = [c for c in cues if c["inicio_seg"] <= hi and c["fin_seg"] >= lo]

    desde = max(0, int(desde))
    limite = max(1, min(int(limite), _MAX_LIMITE))
    tramo = seleccion[desde : desde + limite]
    return {
        "total_cues": len(seleccion),
        "desde": desde,
        "devueltos": len(tramo),
        "cues": tramo,
    }

"""Servidor MCP (FastMCP) que expone tools de lectura y búsqueda sobre ficheros .srt.

Transport stdio por defecto (`mcp.run()`), que es lo que usa Claude Code. Las tools
operan sobre los `.srt` que genera el transcriptor (p. ej. en `outputs/videos/`).

Las docstrings de cada tool son la descripción que ve el modelo: por eso son explícitas
sobre parámetros y forma del resultado.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from srt_mcp.srt_parser import buscar_en_cues, leer_cues, parse_srt_file

mcp = FastMCP("srt-plenos")


def _resolver_ruta(ruta: str | None) -> Path:
    """Valida la ruta a un .srt y la resuelve. Lanza ValueError/FileNotFoundError.

    Si `ruta` se omite (None/vacía), se usa la variable de entorno SRT_MCP_DEFAULT_FILE
    (el fichero por defecto con el que el cliente arranca el servidor). Si no hay ni una
    ni otra, lanza ValueError.

    Si la variable de entorno SRT_MCP_BASE_DIR está definida, restringe el acceso a
    ficheros dentro de ese directorio (evita lecturas fuera del proyecto). La contención
    se aplica SOLO a una `ruta` dada por el llamante: el fichero por defecto
    (SRT_MCP_DEFAULT_FILE) queda exento porque el cliente ya lo resolvió y aprobó (puede
    vivir fuera del catálogo, p. ej. con `--srt`).
    """
    from_default = not ruta
    if from_default:
        ruta = os.environ.get("SRT_MCP_DEFAULT_FILE", "").strip()
    if not ruta:
        raise ValueError(
            "No se indicó `ruta` y no hay SRT_MCP_DEFAULT_FILE definido: "
            "no sé qué fichero .srt leer."
        )
    p = Path(ruta).expanduser()
    base = os.environ.get("SRT_MCP_BASE_DIR", "").strip()
    if base and not from_default:
        base_dir = Path(base).expanduser().resolve()
        candidata = (base_dir / p).resolve() if not p.is_absolute() else p.resolve()
        try:
            candidata.relative_to(base_dir)
        except ValueError:
            raise ValueError(
                "Ruta fuera del directorio permitido (SRT_MCP_BASE_DIR={}): {}".format(
                    base_dir, ruta
                )
            )
        p = candidata
    if not p.exists():
        raise FileNotFoundError("No se encontró el fichero .srt: {}".format(p))
    if p.suffix.lower() != ".srt":
        raise ValueError("El fichero no es un .srt: {}".format(p))
    return p


def _resolver_directorio(directorio: str | None) -> Path:
    """Resuelve el directorio a listar por `listar_srt`. Lanza ValueError.

    Orden de resolución: `directorio` explícito → env SRT_MCP_BASE_DIR → directorio padre
    de SRT_MCP_DEFAULT_FILE. A un `directorio` explícito se le aplica la misma contención
    de SRT_MCP_BASE_DIR que a una `ruta`; el fallback (base dir / dir del default) está
    exento por ser ya aprobado.
    """
    base = os.environ.get("SRT_MCP_BASE_DIR", "").strip()
    if directorio:
        p = Path(directorio).expanduser()
        if base:
            base_dir = Path(base).expanduser().resolve()
            candidata = (base_dir / p).resolve() if not p.is_absolute() else p.resolve()
            try:
                candidata.relative_to(base_dir)
            except ValueError:
                raise ValueError(
                    "Directorio fuera del permitido (SRT_MCP_BASE_DIR={}): {}".format(
                        base_dir, directorio
                    )
                )
            p = candidata
        else:
            p = p.resolve()
    elif base:
        p = Path(base).expanduser().resolve()
    else:
        default_file = os.environ.get("SRT_MCP_DEFAULT_FILE", "").strip()
        if not default_file:
            raise ValueError(
                "No se indicó `directorio` y no hay SRT_MCP_BASE_DIR ni "
                "SRT_MCP_DEFAULT_FILE: no sé qué carpeta listar."
            )
        p = Path(default_file).expanduser().resolve().parent
    if not p.is_dir():
        raise ValueError("No es un directorio válido: {}".format(p))
    return p


@mcp.tool()
def leer_srt(
    ruta: str | None = None,
    desde: int = 0,
    limite: int = 200,
    desde_seg: float | None = None,
    hasta_seg: float | None = None,
) -> dict:
    """Lee un fichero .srt y devuelve sus cues (subtítulos) estructurados.

    Útil para inspeccionar la transcripción sincronizada de un pleno. Como los plenos
    generan miles de cues, la lectura está paginada: usa `desde`/`limite` para recorrer
    el fichero por tramos. Opcionalmente, `desde_seg`/`hasta_seg` (segundos) acotan a una
    ventana temporal antes de paginar.

    Args:
        ruta: Ruta al fichero .srt (p. ej. "outputs/videos/pleno_11_mayo_2026_transcripcion.srt").
            Si se omite, se usa el fichero por defecto (SRT_MCP_DEFAULT_FILE).
        desde: Índice (basado en 0) del primer cue a devolver. Por defecto 0.
        limite: Número máximo de cues a devolver (por defecto 200, máximo 1000).
        desde_seg: Si se indica, descarta cues que terminen antes de este segundo.
        hasta_seg: Si se indica, descarta cues que empiecen después de este segundo.

    Returns:
        dict con: total_cues (int, total tras el filtro temporal), desde (int),
        devueltos (int), y cues (lista). Cada cue: indice (int), inicio/fin
        ("HH:MM:SS,mmm"), inicio_seg/fin_seg (float, segundos), hablante (str|None),
        texto (str).
    """
    cues = parse_srt_file(_resolver_ruta(ruta))
    return leer_cues(cues, desde=desde, limite=limite, desde_seg=desde_seg, hasta_seg=hasta_seg)


@mcp.tool()
def buscar_srt(
    consulta: str,
    ruta: str | None = None,
    regex: bool = False,
    ignorar_mayusculas: bool = True,
    contexto: int = 0,
    limite: int = 50,
) -> dict:
    """Busca texto dentro de un .srt y devuelve los cues coincidentes con sus timestamps.

    Pensado para localizar intervenciones o menciones concretas en un pleno y saber en
    qué minuto ocurren. La búsqueda es por subcadena por defecto; activa `regex` para
    expresiones regulares.

    Args:
        consulta: Texto a buscar (o patrón regex si regex=True).
        ruta: Ruta al fichero .srt. Si se omite, se usa el fichero por defecto
            (SRT_MCP_DEFAULT_FILE).
        regex: Si True, `consulta` se interpreta como expresión regular. Por defecto False.
        ignorar_mayusculas: Búsqueda insensible a mayúsculas/acentos de caja. Por defecto True.
        contexto: Nº de cues vecinos (antes y después) a incluir por coincidencia. Por defecto 0.
        limite: Máximo de coincidencias a devolver (por defecto 50, máximo 1000).

    Returns:
        dict con: total_coincidencias (int), devueltas (int), y coincidencias (lista).
        Cada coincidencia es un cue (mismas claves que en leer_srt) más, si contexto>0,
        contexto_previo y contexto_posterior (listas de cues vecinos).
    """
    cues = parse_srt_file(_resolver_ruta(ruta))
    return buscar_en_cues(
        cues,
        consulta=consulta,
        regex=regex,
        ignorar_mayusculas=ignorar_mayusculas,
        contexto=contexto,
        limite=limite,
    )


@mcp.tool()
def listar_srt(directorio: str | None = None) -> dict:
    """Lista las transcripciones de plenos (.srt) disponibles en un directorio.

    Úsala para descubrir QUÉ plenos hay disponibles antes de leerlos o buscar en ellos.
    El `ruta` que devuelve cada entrada es exactamente el valor que debes pasar luego a
    `leer_srt`/`buscar_srt` para trabajar sobre ese pleno concreto.

    Args:
        directorio: Carpeta donde buscar los .srt. Si se omite, se usa el directorio por
            defecto del servidor (SRT_MCP_BASE_DIR, o la carpeta del fichero por defecto).

    Returns:
        dict con: directorio (str, carpeta escaneada), total (int) y transcripciones
        (lista, ordenada por nombre). Cada entrada: nombre (str, fichero), ruta (str, el
        valor a pasar a leer_srt/buscar_srt), tamano_bytes (int), num_cues (int|None) y
        duracion (str "H:MM:SS"|None). Si un fichero no se puede parsear, num_cues y
        duracion son null y se añade una clave error.
    """
    base_dir = _resolver_directorio(directorio)
    transcripciones = []
    for p in sorted(base_dir.glob("*.srt")):
        entrada = {
            "nombre": p.name,
            "ruta": p.name,
            "tamano_bytes": p.stat().st_size,
            "num_cues": None,
            "duracion": None,
        }
        try:
            cues = parse_srt_file(p)
            entrada["num_cues"] = len(cues)
            if cues:
                fin = max(c["fin_seg"] for c in cues)
                entrada["duracion"] = str(timedelta(seconds=int(fin)))
        except Exception as exc:  # noqa: BLE001 — un fichero corrupto no debe romper el listado
            entrada["error"] = "No se pudo parsear: {}".format(exc)
        transcripciones.append(entrada)
    return {
        "directorio": str(base_dir),
        "total": len(transcripciones),
        "transcripciones": transcripciones,
    }


def main() -> None:
    """Arranca el servidor MCP por stdio."""
    mcp.run()


if __name__ == "__main__":
    main()

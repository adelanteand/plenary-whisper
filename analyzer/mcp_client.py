"""Cliente MCP del analyzer: arranca el servidor `srt_mcp` como subproceso y habla
con él por el protocolo MCP (stdio) usando el SDK oficial `mcp`.

Antes el analyzer importaba `srt_mcp.srt_parser` in-process; ahora es un cliente MCP
real, desacoplado del paquete del servidor. El SDK `mcp` es asíncrono (anyio); como el
orquestador es síncrono, hacemos de puente con un `BlockingPortal` de anyio: un único
loop en un hilo de fondo donde UNA sola corrutina (`_serve`) mantiene abiertos
`stdio_client` + `ClientSession` durante toda la sesión. Entrar y salir de esos context
managers en la MISMA tarea evita el error "Attempted to exit cancel scope in a different
task" de anyio.

Requiere Python 3.10+ (lo exige el SDK `mcp`): por eso el analyzer pasa a su propio venv.
"""

from __future__ import annotations

import concurrent.futures
import datetime
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import anyio
from anyio.from_thread import BlockingPortal, start_blocking_portal
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

# Raíz del repo: dos niveles por encima de analyzer/mcp_client.py.
_REPO_ROOT = Path(__file__).resolve().parents[1]

# Tiempos de guarda (segundos).
_STARTUP_TIMEOUT = 30.0   # arranque del subproceso + initialize + list_tools
_CALL_TIMEOUT = 60.0      # una llamada a tool
_SHUTDOWN_TIMEOUT = 10.0  # cierre limpio


class SrtMcpClient:
    """Cliente síncrono sobre el servidor MCP `srt_mcp`, con conexión persistente.

    Uso:
        client = SrtMcpClient(srt_path)
        client.start()                      # lanza y se conecta; puede lanzar excepción
        tools = client.tools_for_anthropic()
        text, is_error = client.call("buscar_srt", {"consulta": "presupuesto"})
        client.close()
    """

    def __init__(self, srt_path, base_dir: Optional[Path] = None) -> None:
        # `srt_path` puede ser None: el servidor arranca solo para listar el catálogo y
        # abrir plenos por `ruta` (sin pleno por defecto cargado).
        self.srt_path = Path(srt_path).resolve() if srt_path else None
        # `base_dir` es el directorio del catálogo de plenos. Ahora SÍ se fija: el modelo
        # puede pasar `ruta` (la conservamos en el esquema) para abrir cualquier pleno
        # listado, así que acotamos esas lecturas a este directorio. Es también la carpeta
        # por defecto de `listar_srt`. El fichero por defecto (SRT_MCP_DEFAULT_FILE) queda
        # exento de la contención en el servidor, así que un `--srt` fuera del catálogo
        # sigue cargándose sin problema.
        self.base_dir = Path(base_dir).resolve() if base_dir else None
        self._portal_cm = None                       # context manager del portal
        self._portal: Optional[BlockingPortal] = None
        self._serve_future: Optional[concurrent.futures.Future] = None
        self._shutdown: Optional[anyio.Event] = None
        self._session: Optional[ClientSession] = None
        self._tools: List[dict] = []                 # adaptadas a formato Anthropic
        self._started = False

    # ── parámetros de arranque del subproceso ──
    def _server_params(self) -> StdioServerParameters:
        # `env` REEMPLAZA el entorno del hijo: hay que incluir todo lo necesario.
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(_REPO_ROOT),
        }
        if self.srt_path is not None:
            env["SRT_MCP_DEFAULT_FILE"] = str(self.srt_path)
        if self.base_dir is not None:
            env["SRT_MCP_BASE_DIR"] = str(self.base_dir)
        # En Windows el intérprete necesita SYSTEMROOT para arrancar.
        if "SYSTEMROOT" in os.environ:
            env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
        return StdioServerParameters(
            command=sys.executable,           # el intérprete del propio analyzer (3.10+)
            args=["-m", "srt_mcp"],
            env=env,
            cwd=str(_REPO_ROOT),
        )

    # ── corrutina de larga vida: posee los context managers toda la sesión ──
    async def _serve(self, set_ready) -> None:
        params = self._server_params()
        timeout = datetime.timedelta(seconds=_CALL_TIMEOUT)
        # Silencia el stderr del servidor (FastMCP loguea "Processing request..." en
        # cada llamada) para no ensuciar el chat. Los errores de tool igualmente vuelven
        # por el protocolo (is_error) y los de arranque por el timeout de start().
        with open(os.devnull, "w") as errlog:
            async with stdio_client(params, errlog=errlog) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=timeout) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    self._session = session
                    self._tools = _adapt_tools(result.tools)
                    set_ready()                     # señal: ya estamos listos
                    await self._shutdown.wait()      # parkear hasta close()
        # Al salir aquí (misma tarea que entró) los context managers cierran limpio.

    # ── API síncrona ──
    def start(self) -> None:
        """Arranca el subproceso y abre la sesión MCP. Bloquea hasta estar listo.

        Lanza RuntimeError/TimeoutError si el servidor no arranca o no responde a tiempo;
        el llamante debe capturarlo y degradar a 'sin tools'.
        """
        if self._started:
            return
        self._portal_cm = start_blocking_portal()
        self._portal = self._portal_cm.__enter__()

        self._shutdown = self._portal.call(anyio.Event)
        ready = self._portal.call(anyio.Event)
        self._serve_future = self._portal.start_task_soon(self._serve, ready.set)
        ready_future = self._portal.start_task_soon(ready.wait)

        done, _ = concurrent.futures.wait(
            [ready_future, self._serve_future],
            timeout=_STARTUP_TIMEOUT,
            return_when=concurrent.futures.FIRST_COMPLETED,
        )
        try:
            if self._serve_future in done:
                # _serve terminó antes de estar listo -> falló al conectar.
                exc = self._serve_future.exception()
                raise RuntimeError(
                    "El servidor MCP srt no arrancó: {}".format(
                        exc if exc else "cierre inesperado"
                    )
                )
            if ready_future not in done:
                raise TimeoutError(
                    "El servidor MCP srt no respondió en {}s.".format(int(_STARTUP_TIMEOUT))
                )
        except BaseException:
            # Limpieza si el arranque falla: no dejar el portal/subproceso colgando.
            self.close()
            raise
        self._started = True

    def tools_for_anthropic(self) -> List[dict]:
        """Tools en formato Anthropic ({name, description, input_schema}), ORDENADAS POR
        NOMBRE y fijas durante la sesión (invariante de caché de prompt). Conservan `ruta`:
        el modelo puede abrir cualquier pleno listado, acotado por SRT_MCP_BASE_DIR."""
        return self._tools

    def call(self, name: str, arguments: Optional[dict] = None) -> Tuple[str, bool]:
        """Invoca una tool por MCP. Devuelve (texto, is_error). Nunca lanza al llamante."""
        if not self._started or self._portal is None:
            return ("Cliente MCP no inicializado.", True)
        args = arguments or {}

        async def _do_call():
            result = await self._session.call_tool(name, args)
            parts = [c.text for c in result.content if getattr(c, "type", None) == "text"]
            text = "\n".join(parts) if parts else ""
            return (text, bool(result.isError))

        try:
            future = self._portal.start_task_soon(_do_call)
            return future.result(timeout=_CALL_TIMEOUT)
        except concurrent.futures.TimeoutError:
            return (
                "La herramienta {} tardó demasiado (>{}s).".format(name, int(_CALL_TIMEOUT)),
                True,
            )
        except Exception as exc:  # noqa: BLE001 — devolvemos el error al modelo, no lo propagamos
            return ("Error al ejecutar {} por MCP: {}".format(name, exc), True)

    def close(self) -> None:
        """Cierra la sesión y el subproceso de forma limpia e idempotente."""
        if self._portal is not None:
            try:
                if self._shutdown is not None:
                    # Despierta _serve para que salga de sus context managers EN SU TAREA.
                    self._portal.call(self._shutdown.set)
                if self._serve_future is not None:
                    self._serve_future.result(timeout=_SHUTDOWN_TIMEOUT)
            except Exception:
                pass  # cierre best-effort: no enmascarar la salida del programa
            finally:
                try:
                    if self._portal_cm is not None:
                        self._portal_cm.__exit__(None, None, None)
                except Exception:
                    pass
        self._portal = None
        self._portal_cm = None
        self._session = None
        self._serve_future = None
        self._shutdown = None
        self._started = False


def _adapt_tools(tools) -> List[dict]:
    """MCP Tool[] -> formato Anthropic, ORDENADO POR NOMBRE (invariante de caché de prompt).

    Se conserva `ruta`: el modelo puede dirigir leer_srt/buscar_srt a cualquier pleno
    listado por listar_srt, acotado por SRT_MCP_BASE_DIR en el servidor.
    """
    out: List[dict] = []
    for t in tools:
        out.append({
            "name": t.name,
            "description": t.description or "",
            "input_schema": dict(t.inputSchema or {}),
        })
    out.sort(key=lambda d: d["name"])
    return out

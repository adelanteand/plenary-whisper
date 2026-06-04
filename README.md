# Plenos — Transcripción, Diarización y Análisis

Monorepo con tres componentes:

- **`transcriber/`** — transcripción + diarización de audio con Whisper (OpenAI) + pyannote
  (local y gratuito). Genera `.txt`, `.srt` y, opcionalmente, `.json`. Documentado abajo.
- **`analyzer/`** — chatbot que analiza las transcripciones generadas, con el Anthropic SDK
  (arquitectura hub-spoke). Usa el servidor MCP de abajo para citar con marcas de tiempo
  exactas. Ver [Análisis con chatbot](#análisis-con-chatbot-analyzer).
- **`srt_mcp/`** — servidor MCP que expone tools de lectura y búsqueda sobre los `.srt`
  generados. Lo consumen Claude Code y el `analyzer`. Ver
  [Servidor MCP de SRT](#servidor-mcp-de-srt-srt_mcp).

> **Windows:** el `Makefile` usa shell POSIX y **no** corre en cmd.exe/PowerShell. Usa el
> equivalente `make.ps1` (mismos targets) o invoca los comandos Python directamente —
> ver [Windows](#windows). Los entrypoints ya fuerzan UTF-8 y ANSI en la consola, así que
> la salida con acentos/emojis no rompe aunque la redirijas a un fichero.

---

## Transcripción + Diarización de Audio
### Whisper (OpenAI) + pyannote-audio — local, gratuito

## ¿Qué hace?

- **Transcribe** el audio usando Whisper (funciona en español, inglés y 100+ idiomas)
- **Identifica quién habla** en cada momento (diarización) con pyannote — opcional, con `--diarize`
- Soporta archivos de cualquier duración (trocea el audio automáticamente)
- Genera un `.txt` legible y un `.srt` sincronizado (subtítulos), y opcionalmente un `.json`
  estructurado. El `.srt` es lo que consulta el [servidor MCP](#servidor-mcp-de-srt-srt_mcp).

---

## Requisitos previos

### 1. Python (3.9+ para el transcriptor)
```bash
python --version
```
> El **transcriptor** corre en Python 3.9+. El **`analyzer/`** y el **`srt_mcp/`** necesitan
> Python **3.10+** (lo exige el SDK `mcp`) y usan cada uno su propio venv —`.venv-analyzer` y
> `.venv-mcp`—, que crean sus respectivos `make install-…` (ver sus secciones más abajo).

### 2. ffmpeg
```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg

# Windows (PowerShell) — instálalo y reabre la terminal para que entre en el PATH
winget install Gyan.FFmpeg      # o: choco install ffmpeg
```

### 3. Instalar dependencias Python
```bash
pip install -r transcriber/requirements.txt
# (equivale a: pip install openai-whisper pyannote.audio pydub torch torchaudio)
```

> **Nota sobre tamaño:** `torch` pesa ~2 GB. Si tienes GPU NVIDIA, instala la versión CUDA:
> ```bash
> pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
> ```

### 4. Token de Hugging Face (solo para diarización)

Solo se necesita si vas a usar `--diarize` o `--diarize-only`. La transcripción básica no lo pide.

1. Regístrate gratis en [huggingface.co](https://huggingface.co)
2. Acepta los términos del modelo aquí: [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
3. Genera un token en [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)

---

## Uso

### Básico (solo transcripción, sin token)
La diarización está **desactivada por defecto**: esto solo transcribe y no necesita `HF_TOKEN`.
```bash
python transcriber/transcribe_diarize.py mi_audio.mp3
```

### Con diarización (identifica quién habla)
Activa la diarización con `--diarize` (requiere `HF_TOKEN`):
```bash
python transcriber/transcribe_diarize.py mi_audio.mp3 --diarize --hf-token hf_XXXXXXXX
```

### Con número de hablantes conocido (mejora la diarización)
```bash
python transcriber/transcribe_diarize.py reunion.mp3 --diarize --hf-token hf_XXXX --speakers 4
```

### Solo diarización (quién habla y cuándo, sin transcribir)
No carga Whisper. Emite los turnos en `audio_diarization.json` y el tiempo por hablante:
```bash
python transcriber/transcribe_diarize.py audio.mp3 --hf-token hf_XXXX --diarize-only --speakers 3
```
La diarización se **cachea** en `audio_diarization.json`, así que una corrida completa posterior
(con el mismo nº de hablantes) la reutiliza y se salta pyannote. Usa `--force-diarize` para
re-diarizar ignorando el caché.

### Guardar también en JSON estructurado
```bash
python transcriber/transcribe_diarize.py audio.mp3 --json resultado.json
```

### Todos los parámetros
```bash
python transcriber/transcribe_diarize.py audio.mp3 \
  --diarize \                  # Activa la diarización (identifica hablantes)
  --hf-token hf_XXXX \         # Token Hugging Face (solo con --diarize/--diarize-only)
  --model large-v3 \           # Modelo Whisper (tiny/base/small/medium/large/large-v3)
  --speakers 3 \               # Número de hablantes (opcional, solo aplica al diarizar)
  --chunk-minutes 20 \         # Tamaño de segmentos en minutos
  --output transcripcion.txt \ # Archivo de salida
  --json datos.json            # Salida estructurada adicional
```

---

## Formato de salida (TXT)

```
[00:00:05] SPEAKER_00:
  Buenos días a todos, vamos a empezar la reunión.
  Tenemos tres puntos en el orden del día.

[00:00:22] SPEAKER_01:
  Perfecto, yo empiezo con el primer punto.
  Los resultados del trimestre han sido positivos...

[00:01:45] SPEAKER_00:
  Gracias. ¿Alguien tiene preguntas?
```

Al final del proceso verás un resumen de tiempo por hablante:

```
── Tiempo por hablante ──────────────────
  SPEAKER_00             1:23:15  (34.7%)
  SPEAKER_01             1:01:42  (25.5%)
  SPEAKER_02             0:58:30  (24.2%)
  SPEAKER_03             0:20:33  (8.5%)
─────────────────────────────────────────
```

---

## Modelos disponibles

| Modelo     | Precisión | Velocidad | RAM aprox. |
|------------|-----------|-----------|------------|
| `tiny`     | Baja      | Muy rápida| ~1 GB      |
| `base`     | Media     | Rápida    | ~1 GB      |
| `small`    | Buena     | Normal    | ~2 GB      |
| `medium`   | Muy buena | Lenta     | ~5 GB      |
| `large-v3` | Excelente | Muy lenta | ~10 GB     |

> Para audio en español, `large-v3` da los mejores resultados. Para pruebas rápidas usa `small`.

---

## Tiempos estimados (CPU, sin GPU)

| Duración audio | Modelo small | Modelo large-v3 |
|----------------|-------------|-----------------|
| 1 hora         | ~20 min     | ~90 min         |
| 4 horas        | ~80 min     | ~6 horas        |

> Con GPU NVIDIA, divide estos tiempos por 5-10x.

---

## Problemas frecuentes

**`ffmpeg not found`**
→ Instala ffmpeg y reinicia el terminal.

**Error 401 / 403 de Hugging Face** (`403 ... enable access to public gated repositories`)
→ No basta con aceptar los términos del modelo: el **token** debe poder leer repos *gated*. Usa
un token de tipo **Read**, o si es *fine-grained* marca *"Read access to contents of all public
gated repos you can access"* en [settings/tokens](https://huggingface.co/settings/tokens). Acepta
además los términos de **ambos** modelos con la misma cuenta:
[speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1) y
[segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0).

**`CUDA out of memory`**
→ Usa un modelo más pequeño (`--model medium`) o procesa con CPU.

**Diarización imprecisa**
→ Especifica `--speakers N` si sabes el número exacto de personas.

---

## Windows

El `Makefile` está pensado para shell POSIX (macOS/Linux, o Git Bash/WSL en Windows). En una
PowerShell nativa usa **`make.ps1`**, que replica los mismos targets:

```powershell
.\make.ps1 install                 # dependencias del transcriptor
.\make.ps1 install-analyzer        # dependencias del chatbot
.\make.ps1 env                     # crea .env desde .env_template
.\make.ps1 transcribe -Audio outputs\videos\pleno.mp4 --diarize --speakers 3
.\make.ps1 diarize    -Audio outputs\videos\pleno.mp4 --speakers 3
.\make.ps1 analyzer   -Transcript outputs\videos\otro.txt --debug
.\make.ps1 download   -Url "https://...m3u8" -Output outputs\videos\pleno.mp4
.\make.ps1 help                    # lista de targets
```

Los flags extra (`--speakers`, `--model`, etc.) se reenvían tal cual al comando. Si PowerShell
bloquea la ejecución de scripts, invócalo sin tocar la política global:

```powershell
powershell -ExecutionPolicy Bypass -File .\make.ps1 transcribe -Audio outputs\videos\pleno.mp4
```

O, sin `make.ps1`, ejecuta los comandos Python directamente (usa `\` en las rutas):

```powershell
python transcriber\transcribe_diarize.py outputs\videos\pleno.mp4 --diarize --speakers 3
python -m analyzer
```

> **ffmpeg** debe estar en el `PATH` (lo necesita pydub para leer mp3/mp4/m4a): `winget install
> Gyan.FFmpeg` y reabre la terminal. La salida UTF-8/ANSI ya se configura sola en el arranque.

> **Python 3.10+ para `analyzer/` y `srt_mcp/`:** ambos usan el SDK `mcp`. En macOS/Linux, `make`
> les crea venvs propios (`.venv-analyzer`, `.venv-mcp`). En Windows, `make.ps1` aún instala el
> chatbot en el **Python activo** (asegúrate de que sea 3.10+) y **no** cubre el servidor MCP:
> crea su venv a mano, p. ej.
> `py -3.12 -m venv .venv-mcp; .venv-mcp\Scripts\pip install -r srt_mcp\requirements.txt`.

---

## Análisis con chatbot (`analyzer/`)

Un asistente de terminal que conversa sobre una transcripción ya generada, construido con el
**Anthropic SDK**. Arquitectura **hub-spoke**: un agente "hub" orquesta y delega en "spokes"
especializados. El hub actúa como **cliente MCP** del servidor
[`srt_mcp`](#servidor-mcp-de-srt-srt_mcp) y expone sus tools (`buscar_srt`, `leer_srt`,
`listar_srt`): puede **listar los plenos disponibles** y **abrir/buscar en cualquiera** de ellos,
y **citar con marcas de tiempo exactas** en lugar de estimarlas. La transcripción cargada va
completa en el contexto (es el pleno "actual"); los demás se consultan por tools. Sin `.srt` ni
catálogo, funciona como agente único. (Spokes in-process futuros: estadísticas por hablante, orden
del día, resúmenes por punto.)

### Requisitos

1. Crear el venv del chatbot (Python **3.10+**, propio: `.venv-analyzer`) e instalar sus deps
   —incluye el SDK `mcp` para hablar con el servidor MCP—:
   ```bash
   make install-analyzer
   ```
2. Añadir tu clave de API de Anthropic al `.env` (`make env` lo crea desde la plantilla):
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```
   Consíguela en [console.anthropic.com](https://console.anthropic.com/).

### Uso

```bash
# Usa la transcripción de muestra por defecto
make analyzer

# Indica otra transcripción (.txt o .json) y flags extra
make analyzer TRANSCRIPT=outputs/videos/otro_pleno_transcripcion.txt ARGS="--model claude-opus-4-8 --debug"

# O directamente con el intérprete del venv del chatbot
.venv-analyzer/bin/python -m analyzer outputs/videos/otro_pleno_transcripcion.txt --debug
```

El `.srt` por defecto se detecta solo (el hermano de la transcripción cargada); fuérzalo con
`--srt ruta.srt` o la variable `ANALYZER_SRT`. El catálogo de plenos que el agente puede listar y
abrir es `outputs/videos` (ajustable con `ANALYZER_TRANSCRIPTS_DIR`). Dentro del chat: pregunta en
lenguaje natural (p.ej. *"¿qué plenos tienes?"* o *"¿En qué minuto exacto se levanta la sesión?"*).
Comandos: `/ayuda`, `/tokens` (uso acumulado), `/salir`.

> **Nota:** el modelo por defecto es `claude-haiku-4-5` (barato para iterar; sobreescribible con
> `--model` o `ANALYZER_MODEL`). La transcripción se cachea en el contexto (prompt caching), así
> que cada turno es económico. Como la transcripción por defecto **no diariza**, no habrá
> identificación de hablantes y el análisis "por hablante" no estará disponible hasta regenerarla
> con `--diarize`.

---

## Servidor MCP de SRT (`srt_mcp/`)

Servidor [MCP](https://modelcontextprotocol.io) (SDK oficial `mcp`/FastMCP, transporte **stdio**,
sin puerto de red) que expone como *tools* operaciones de **lectura, búsqueda y listado** sobre los
`.srt` que genera el transcriptor. Corre en su **propio venv 3.10+** (`.venv-mcp`), aparte del
transcriptor.

Tools (`ruta` es opcional; si se omite, usa `SRT_MCP_DEFAULT_FILE`):
- `leer_srt(...)` — lee un tramo de cues (paginado o acotado a una ventana temporal).
- `buscar_srt(consulta, ...)` — busca texto y devuelve los cues coincidentes con su timestamp.
- `listar_srt(directorio=None)` — lista los `.srt` disponibles (nombre, `ruta`, tamaño, nº de cues,
  duración) para descubrir qué plenos hay antes de leerlos.

Lo consumen **dos clientes**:
- **Claude Code** — registrado vía `.mcp.json` (scope de proyecto, ya en el repo; sus paths usan
  `${CLAUDE_PROJECT_DIR:-.}`, así que es portable entre clones y no lleva rutas absolutas). Tras
  instalarlo, reinicia Claude Code en este repo y aprueba el servidor `srt` cuando lo pida.
- **El `analyzer`** — como cliente MCP, para listar plenos y citar con marcas de tiempo exactas
  (ver su sección).

### Instalación y uso manual

```bash
make install-mcp     # crea .venv-mcp (3.10+) e instala el SDK mcp
make mcp-serve       # arranca el servidor por stdio (inspección manual)
```

Variables de entorno opcionales: `SRT_MCP_DEFAULT_FILE` (fichero `.srt` por defecto cuando se
llama a `leer_srt`/`buscar_srt` sin `ruta`) y `SRT_MCP_BASE_DIR` (restringe a un directorio las
lecturas por `ruta` y es la carpeta por defecto de `listar_srt`).
Más detalles en [`srt_mcp/README.md`](srt_mcp/README.md) y [`srt_mcp/CLAUDE.md`](srt_mcp/CLAUDE.md).

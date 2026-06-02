# Plenos — Transcripción, Diarización y Análisis

Monorepo con dos componentes:

- **`transcriber/`** — transcripción + diarización de audio con Whisper (OpenAI) + pyannote
  (local y gratuito). Documentado abajo.
- **`analyzer/`** — chatbot que analiza las transcripciones generadas, con el Anthropic SDK
  (arquitectura hub-spoke). Ver [Análisis con chatbot](#análisis-con-chatbot-analyzer).

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
- Genera un `.txt` legible y opcionalmente un `.json` estructurado

---

## Requisitos previos

### 1. Python 3.9+
```bash
python --version
```

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

---

## Análisis con chatbot (`analyzer/`)

Un asistente de terminal que conversa sobre una transcripción ya generada, construido con el
**Anthropic SDK**. Arquitectura **hub-spoke**: un agente "hub" orquesta el trabajo y, en
futuras iteraciones, delega en "spokes" especializados (estadísticas por hablante, extracción
del orden del día, búsqueda de citas con marca de tiempo, resúmenes por punto). La primera
iteración es un **agente único** sobre el que iterar.

### Requisitos

1. Instalar dependencias del chatbot (en el mismo venv 3.9):
   ```bash
   make install-analyzer        # o: pip install -r analyzer/requirements.txt
   ```
2. Añadir tu clave de API de Anthropic al `.env` (`make env` lo crea desde la plantilla):
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```
   Consíguela en [console.anthropic.com](https://console.anthropic.com/).

### Uso

```bash
# Usa la transcripción de muestra por defecto
python -m analyzer

# Indica otra transcripción (.txt o .json) y modelo
python -m analyzer outputs/videos/otro_pleno_transcripcion.txt --model claude-opus-4-8 --debug
```

Dentro del chat: pregunta en lenguaje natural (p.ej. *"¿Cuáles son los puntos del orden del
día?"*). Comandos: `/ayuda`, `/tokens` (uso acumulado), `/salir`.

> **Nota:** el modelo por defecto es `claude-sonnet-4-6` (barato para iterar). La transcripción
> se cachea en el contexto (prompt caching), así que cada turno es económico. Como la
> transcripción por defecto **no diariza**, no habrá identificación de hablantes y el análisis
> "por hablante" no estará disponible hasta regenerarla con `--diarize`.

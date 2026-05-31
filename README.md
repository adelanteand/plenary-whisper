# Transcripción + Diarización de Audio
### Whisper (OpenAI) + pyannote-audio — local, gratuito

---

## ¿Qué hace?

- **Transcribe** el audio usando Whisper (funciona en español, inglés y 100+ idiomas)
- **Identifica quién habla** en cada momento (diarización) con pyannote
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

# Windows — descarga desde https://ffmpeg.org/download.html
```

### 3. Instalar dependencias Python
```bash
pip install openai-whisper pyannote.audio pydub torch torchaudio
```

> **Nota sobre tamaño:** `torch` pesa ~2 GB. Si tienes GPU NVIDIA, instala la versión CUDA:
> ```bash
> pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
> ```

### 4. Token de Hugging Face (para diarización)

1. Regístrate gratis en [huggingface.co](https://huggingface.co)
2. Acepta los términos del modelo aquí: [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
3. Genera un token en [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)

---

## Uso

### Básico
```bash
python transcribe_diarize.py mi_audio.mp3 --hf-token hf_XXXXXXXX
```

### Con número de hablantes conocido (mejora la diarización)
```bash
python transcribe_diarize.py reunion.mp3 --hf-token hf_XXXX --speakers 4
```

### Solo transcripción (sin diarización, más rápido)
```bash
python transcribe_diarize.py audio.mp3 --skip-diarization
```

### Guardar también en JSON estructurado
```bash
python transcribe_diarize.py audio.mp3 --hf-token hf_XXXX --json resultado.json
```

### Todos los parámetros
```bash
python transcribe_diarize.py audio.mp3 \
  --hf-token hf_XXXX \        # Token Hugging Face
  --model large-v3 \           # Modelo Whisper (tiny/base/small/medium/large/large-v3)
  --speakers 3 \               # Número de hablantes (opcional)
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

**Error 401 de Hugging Face**
→ Asegúrate de haber aceptado los términos en la página del modelo.

**`CUDA out of memory`**
→ Usa un modelo más pequeño (`--model medium`) o procesa con CPU.

**Diarización imprecisa**
→ Especifica `--speakers N` si sabes el número exacto de personas.

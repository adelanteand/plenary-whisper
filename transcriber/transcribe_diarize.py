#!/usr/bin/env python3
"""
transcribe_diarize.py
=====================
Transcripción + diarización de archivos de audio largos.

Dependencias:
    pip install openai-whisper pyannote.audio pydub torch torchaudio

Requisitos:
    - Token de Hugging Face con acceso a pyannote/speaker-diarization-3.1
      (registro gratuito en https://huggingface.co/pyannote/speaker-diarization-3.1)
    - ffmpeg instalado en el sistema (brew install ffmpeg / apt install ffmpeg)

Uso:
    python transcribe_diarize.py audio.mp3
    python transcribe_diarize.py audio.mp3 --hf-token hf_xxxx
    python transcribe_diarize.py audio.mp3 --model large-v3 --speakers 3
    python transcribe_diarize.py audio.mp3 --chunk-minutes 15 --output resultado.txt
"""

from __future__ import annotations

import argparse
import os
import sys
import json
import tempfile
from pathlib import Path
from datetime import timedelta

# Carga variables de entorno desde un archivo .env si python-dotenv está disponible
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# ── helpers ──────────────────────────────────────────────────────────────────

def fmt_time(seconds: float) -> str:
    """Convierte segundos a HH:MM:SS."""
    return str(timedelta(seconds=int(seconds)))


def fmt_srt_time(seconds: float) -> str:
    """Convierte segundos al formato de tiempo de SRT: HH:MM:SS,mmm."""
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ensure_deps():
    missing = []
    for pkg in ["whisper", "pyannote.audio", "pydub", "torch"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"[ERROR] Faltan dependencias: {', '.join(missing)}")
        print("Instálalas con:")
        print(f"  pip install openai-whisper pyannote.audio pydub torch torchaudio")
        sys.exit(1)


def convert_to_wav(input_path: Path, wav_path: Path, force: bool = False) -> Path:
    """Convierte el archivo a WAV mono 16kHz (formato óptimo para Whisper y pyannote).

    El WAV se cachea en disco; si ya existe se reutiliza (salta este paso) salvo
    que se pase force=True.
    """
    if wav_path.exists() and not force:
        print(f"[1/4] Reutilizando WAV en caché '{wav_path.name}' "
              f"({wav_path.stat().st_size / 1e6:.1f} MB) — conversión omitida.")
        return wav_path

    from pydub import AudioSegment
    print(f"[1/4] Convirtiendo '{input_path.name}' a WAV mono 16 kHz...")
    audio = AudioSegment.from_file(str(input_path))
    audio = audio.set_channels(1).set_frame_rate(16000)
    audio.export(str(wav_path), format="wav")
    duration_min = len(audio) / 1000 / 60
    print(f"    → Duración: {duration_min:.1f} min | Tamaño: {wav_path.stat().st_size / 1e6:.1f} MB")
    return wav_path


def split_audio(wav_path: Path, chunk_minutes: int, tmp_dir: str) -> list[Path]:
    """Divide el WAV en trozos para procesar en paralelo."""
    from pydub import AudioSegment
    audio = AudioSegment.from_wav(str(wav_path))
    chunk_ms = chunk_minutes * 60 * 1000
    total_ms = len(audio)
    chunks = []
    i = 0
    idx = 0
    while i < total_ms:
        end = min(i + chunk_ms, total_ms)
        chunk = audio[i:end]
        chunk_path = Path(tmp_dir) / f"chunk_{idx:03d}.wav"
        chunk.export(str(chunk_path), format="wav")
        chunks.append((chunk_path, i / 1000))  # (path, offset_segundos)
        i = end
        idx += 1
    print(f"    → {len(chunks)} segmento(s) de {chunk_minutes} min")
    return chunks


def transcribe_chunks(chunks: list, model_name: str, language_arg: str,
                      language: str | None, chunk_minutes: int,
                      cache_dir: Path | None = None, force: bool = False) -> list[dict]:
    """Transcribe cada chunk con Whisper y devuelve los segmentos con offset global.

    Si `cache_dir` está definido, cada chunk se cachea individualmente: los que ya
    existan se reutilizan (salvo `force=True`) y el modelo Whisper solo se carga si
    queda al menos un chunk por transcribir. Esto hace la transcripción reanudable.
    """
    model = None  # carga perezosa: solo si hay algo que transcribir
    all_segments = []
    for idx, (chunk_path, offset) in enumerate(chunks):
        if cache_dir is not None and not force:
            cached = load_cached_chunk(cache_dir, idx, model_name, language_arg, chunk_minutes)
            if cached is not None:
                print(f"    Reutilizando segmento {idx + 1}/{len(chunks)} (cacheado, "
                      f"{len(cached)} fragmentos)")
                all_segments.extend(cached)
                continue

        if model is None:
            import whisper
            print(f"\n[2/4] Cargando modelo Whisper '{model_name}'...")
            model = whisper.load_model(model_name)

        print(f"    Transcribiendo segmento {idx + 1}/{len(chunks)}...", end=" ", flush=True)
        result = model.transcribe(str(chunk_path), language=language, verbose=False)
        chunk_segments = [
            {"start": seg["start"] + offset,
             "end":   seg["end"]   + offset,
             "text":  seg["text"].strip()}
            for seg in result["segments"]
        ]
        if cache_dir is not None:
            save_chunk(cache_dir, idx, model_name, language_arg, chunk_minutes, chunk_segments)
        all_segments.extend(chunk_segments)
        print(f"OK ({len(chunk_segments)} fragmentos)")
    return all_segments


def load_cached_segments(path: Path, model_name: str, language: str) -> list[dict] | None:
    """Devuelve los segmentos cacheados si existen y coinciden modelo+idioma; si no, None."""
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if data.get("model") != model_name or data.get("language") != language:
        print(f"[2/4] Caché de transcripción '{path.name}' ignorada "
              f"(se generó con otro modelo/idioma).")
        return None
    segments = data.get("segments")
    if not segments:
        return None
    print(f"[2/4] Reutilizando transcripción en caché '{path.name}' "
          f"({len(segments)} segmento(s)) — transcripción omitida.")
    return segments


def save_segments(path: Path, model_name: str, language: str, segments: list[dict]) -> None:
    """Guarda los segmentos transcritos en disco para reutilizarlos en próximas ejecuciones."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"model": model_name, "language": language, "segments": segments},
                  f, ensure_ascii=False, indent=2)
    print(f"    → Transcripción cacheada en: {path.name}")


def chunk_cache_file(cache_dir: Path, idx: int) -> Path:
    """Ruta del JSON de caché de un chunk concreto dentro del directorio de caché."""
    return cache_dir / f"chunk_{idx:03d}.json"


def load_cached_chunk(cache_dir: Path, idx: int, model_name: str, language: str,
                      chunk_minutes: int) -> list[dict] | None:
    """Devuelve los segmentos cacheados del chunk si existen y coinciden los metadatos; si no, None."""
    path = chunk_cache_file(cache_dir, idx)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if (data.get("model") != model_name or data.get("language") != language
            or data.get("chunk_minutes") != chunk_minutes or data.get("index") != idx):
        return None
    segments = data.get("segments")
    return segments if segments is not None else None


def save_chunk(cache_dir: Path, idx: int, model_name: str, language: str,
               chunk_minutes: int, segments: list[dict]) -> None:
    """Persiste los segmentos de un chunk para poder reanudar transcripciones interrumpidas."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    with open(chunk_cache_file(cache_dir, idx), "w", encoding="utf-8") as f:
        json.dump({"model": model_name, "language": language,
                   "chunk_minutes": chunk_minutes, "index": idx, "segments": segments},
                  f, ensure_ascii=False, indent=2)


def diarize(wav_path: Path, hf_token: str, num_speakers: int | None) -> list[dict]:
    """Ejecuta la diarización con pyannote y devuelve una lista de turnos de habla."""
    from pyannote.audio import Pipeline
    import torch
    print(f"\n[3/4] Ejecutando diarización (pyannote)...")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"    → Dispositivo: {device}")
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=hf_token,
    )
    if pipeline is None:
        print("\n[ERROR] No se pudo cargar el pipeline de pyannote (devolvió None).")
        print("Casi siempre es por permisos del modelo (es 'gated'). Comprueba:")
        print("  1. Que tu HF_TOKEN es válido y tiene scope de lectura:")
        print("       https://huggingface.co/settings/tokens")
        print("  2. Que has ACEPTADO las condiciones de uso de AMBOS modelos")
        print("     (hay que aceptarlos por separado, con la misma cuenta del token):")
        print("       https://huggingface.co/pyannote/speaker-diarization-3.1")
        print("       https://huggingface.co/pyannote/segmentation-3.0")
        sys.exit(1)
    pipeline.to(device)

    kwargs = {}
    if num_speakers:
        kwargs["num_speakers"] = num_speakers

    diarization = pipeline(str(wav_path), **kwargs)

    turns = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        turns.append({
            "start":   turn.start,
            "end":     turn.end,
            "speaker": speaker,
        })
    print(f"    → {len(set(t['speaker'] for t in turns))} hablante(s) detectado(s)")
    return turns


def assign_speakers(segments: list[dict], turns: list[dict]) -> list[dict]:
    """
    Asigna un hablante a cada segmento de Whisper buscando el turno de diarización
    con mayor solapamiento temporal.
    """
    results = []
    for seg in segments:
        best_speaker = "DESCONOCIDO"
        best_overlap = 0.0
        for turn in turns:
            overlap = max(0, min(seg["end"], turn["end"]) - max(seg["start"], turn["start"]))
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = turn["speaker"]
        results.append({**seg, "speaker": best_speaker})
    return results


def write_output(results: list[dict], output_path: Path, json_path: Path | None,
                 srt_path: Path | None):
    """Escribe el resultado en TXT legible, SRT sincronizado y opcionalmente en JSON."""
    print(f"\n[4/4] Generando salida...")

    # ── TXT ──
    lines = []
    prev_speaker = None
    for r in results:
        speaker = r["speaker"]
        ts = fmt_time(r["start"])
        if speaker != prev_speaker:
            lines.append(f"\n[{ts}] {speaker}:")
            prev_speaker = speaker
        lines.append(f"  {r['text']}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"    → Transcripción guardada en: {output_path}")

    # ── SRT (subtítulos sincronizados con el vídeo) ──
    if srt_path:
        # Solo prefijamos con el hablante si la diarización aportó más de uno.
        multi_speaker = len({r["speaker"] for r in results}) > 1
        srt_lines = []
        for i, r in enumerate(results, start=1):
            text = r["text"]
            if multi_speaker:
                text = f"[{r['speaker']}] {text}"
            srt_lines.append(str(i))
            srt_lines.append(f"{fmt_srt_time(r['start'])} --> {fmt_srt_time(r['end'])}")
            srt_lines.append(text)
            srt_lines.append("")  # línea en blanco separadora
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_lines))
        print(f"    → Subtítulos SRT en:        {srt_path}")

    # ── JSON (opcional) ──
    if json_path:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"    → Datos estructurados en:   {json_path}")

    # ── Estadísticas ──
    speakers = {}
    for r in results:
        sp = r["speaker"]
        speakers[sp] = speakers.get(sp, 0) + (r["end"] - r["start"])

    print("\n── Tiempo por hablante ──────────────────")
    total = sum(speakers.values())
    for sp, secs in sorted(speakers.items(), key=lambda x: -x[1]):
        pct = secs / total * 100 if total else 0
        print(f"  {sp:20s}  {fmt_time(secs)}  ({pct:.1f}%)")
    print("─────────────────────────────────────────")


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Transcripción + diarización de audio con Whisper + pyannote"
    )
    parser.add_argument("audio", help="Archivo de audio (mp3, wav, m4a, ogg...)")
    parser.add_argument(
        "--hf-token",
        default=os.environ.get("HF_TOKEN"),
        help="Token de Hugging Face (o setea la variable HF_TOKEN)",
    )
    parser.add_argument(
        "--model",
        default="large-v3",
        choices=["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"],
        help="Modelo Whisper a usar (default: large-v3)",
    )
    parser.add_argument(
        "--language",
        default="es",
        help="Idioma del audio (ISO 639-1, p.ej. 'es', 'en'). "
             "Usa 'auto' para que Whisper lo detecte (default: es)",
    )
    parser.add_argument(
        "--speakers",
        type=int,
        default=None,
        help="Número de hablantes esperados (opcional, mejora la diarización)",
    )
    parser.add_argument(
        "--chunk-minutes",
        type=int,
        default=20,
        help="Minutos por segmento al trocear el audio (default: 20)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Archivo de salida .txt (default: <nombre_audio>_transcripcion.txt)",
    )
    parser.add_argument(
        "--json",
        default=None,
        help="Guarda también la salida en JSON estructurado",
    )
    parser.add_argument(
        "--no-srt",
        action="store_true",
        help="No generar el archivo .srt de subtítulos (por defecto sí se genera).",
    )
    parser.add_argument(
        "--skip-diarization",
        action="store_true",
        help="Solo transcribe sin identificar hablantes (más rápido)",
    )
    parser.add_argument(
        "--debug-chunk",
        type=int,
        default=None,
        metavar="N",
        help="MODO DEPURACIÓN: transcribe solo el fragmento N (1-indexado) "
             "y omite la diarización. Útil para iterar rápido.",
    )
    parser.add_argument(
        "--force-wav",
        action="store_true",
        help="Regenera el WAV en caché aunque ya exista.",
    )
    parser.add_argument(
        "--force-transcribe",
        action="store_true",
        help="Ignora el caché combinado y lo reconstruye desde los chunks "
             "(reutiliza el caché por-chunk si existe).",
    )
    parser.add_argument(
        "--force-chunks",
        action="store_true",
        help="Re-transcribe cada chunk ignorando el caché por-chunk "
             "(implica saltar también el caché combinado).",
    )
    args = parser.parse_args()

    # ── validaciones ──
    ensure_deps()

    audio_path = Path(args.audio)
    if not audio_path.exists():
        print(f"[ERROR] No se encontró el archivo: {audio_path}")
        sys.exit(1)

    if not args.skip_diarization and args.debug_chunk is None and not args.hf_token:
        print("[ERROR] Se necesita un token de Hugging Face para la diarización.")
        print("  1. Regístrate en https://huggingface.co")
        print("  2. Acepta los términos en https://huggingface.co/pyannote/speaker-diarization-3.1")
        print("  3. Genera un token en https://huggingface.co/settings/tokens")
        print("  4. Pásalo con --hf-token hf_xxxx  o  export HF_TOKEN=hf_xxxx")
        sys.exit(1)

    output_path = Path(args.output) if args.output else audio_path.with_name(
        audio_path.stem + "_transcripcion.txt"
    )
    json_path = Path(args.json) if args.json else None
    srt_path = None if args.no_srt else output_path.with_suffix(".srt")

    print(f"\n{'='*50}")
    print(f"  Audio:    {audio_path.name}")
    print(f"  Modelo:   {args.model}")
    print(f"  Salida:   {output_path.name}")
    print(f"{'='*50}\n")

    # Cachés persistentes junto al audio de origen (se reutilizan entre ejecuciones)
    cached_wav = audio_path.with_name(audio_path.stem + "_16k_mono.wav")
    cached_segments = audio_path.with_name(audio_path.stem + "_segments.json")
    # El caché por-chunk vive en un subdirectorio keyed por modelo+idioma+chunk_minutes,
    # ya que las fronteras de cada chunk dependen de chunk_minutes.
    chunk_cache_dir = (audio_path.with_name(audio_path.stem + "_chunks")
                       / f"{args.model}_{args.language}_{args.chunk_minutes}min")
    language = None if args.language.lower() == "auto" else args.language

    with tempfile.TemporaryDirectory() as tmp_dir:
        # 1. Convertir a WAV (o reutilizar el de caché)
        wav_path = convert_to_wav(audio_path, cached_wav, force=args.force_wav)

        # 2. Transcribir (con caché). En modo debug nunca se usa ni escribe el caché.
        if args.debug_chunk is not None:
            chunks = split_audio(wav_path, args.chunk_minutes, tmp_dir)
            if not (1 <= args.debug_chunk <= len(chunks)):
                print(f"[ERROR] --debug-chunk {args.debug_chunk} fuera de rango "
                      f"(hay {len(chunks)} fragmento(s)).")
                sys.exit(1)
            chunks = [chunks[args.debug_chunk - 1]]
            print(f"\n[DEBUG] Transcribiendo solo el fragmento {args.debug_chunk} "
                  f"y omitiendo la diarización.")
            # En modo debug nunca se lee ni escribe el caché por-chunk (siempre fresco).
            segments = transcribe_chunks(chunks, args.model, args.language, language,
                                         args.chunk_minutes)
        else:
            # --force-chunks implica saltar el combinado para que el forzado tenga efecto.
            use_combined = not args.force_transcribe and not args.force_chunks
            segments = (load_cached_segments(cached_segments, args.model, args.language)
                        if use_combined else None)
            if segments is None:
                chunks = split_audio(wav_path, args.chunk_minutes, tmp_dir)
                segments = transcribe_chunks(chunks, args.model, args.language, language,
                                             args.chunk_minutes, cache_dir=chunk_cache_dir,
                                             force=args.force_chunks)
                save_segments(cached_segments, args.model, args.language, segments)

        if args.skip_diarization or args.debug_chunk is not None:
            results = [{**s, "speaker": "HABLANTE"} for s in segments]
        else:
            # 3. Diarizar sobre el WAV completo
            turns = diarize(wav_path, args.hf_token, args.speakers)
            # 4. Fusionar
            results = assign_speakers(segments, turns)

    # 5. Escribir salida
    write_output(results, output_path, json_path, srt_path)
    print(f"\n✓ Proceso completado.\n")


if __name__ == "__main__":
    main()

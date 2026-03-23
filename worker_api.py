"""
worker_api.py — Subtitle Pipeline Worker
Recibe un video, genera subtítulos ASS con brand styles y quema con FFmpeg.

Endpoint: POST /subtitle-video
  - multipart/form-data: campo "video" (archivo .mp4)
  - Retorna: video procesado como binary (video/mp4)
"""

import os
import sys
import json
import uuid
import subprocess
import tempfile
import shutil
import requests
from flask import Flask, request, send_file, jsonify

# Importar el generador de subtítulos
sys.path.insert(0, os.path.dirname(__file__))
from generate_ass import main as generate_ass_main

app = Flask(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
WORKER_SECRET  = os.environ.get("WORKER_SECRET", "")   # opcional: proteger el endpoint


def extract_audio(video_path: str, audio_path: str):
    """Extrae audio del video en formato MP3 a 16kHz mono para Whisper."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn", "-ar", "16000", "-ac", "1", "-f", "mp3",
        audio_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg audio extract error:\n{result.stderr}")


def transcribe_whisper(audio_path: str) -> dict:
    """Llama a Whisper API con word-level timestamps."""
    url = "https://api.openai.com/v1/audio/transcriptions"
    with open(audio_path, "rb") as f:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            files={"file": ("audio.mp3", f, "audio/mpeg")},
            data={
                "model": "whisper-1",
                "language": "es",
                "response_format": "verbose_json",
                "timestamp_granularities[]": "word",
            },
            timeout=120,
        )
    response.raise_for_status()
    return response.json()


def detect_keywords(transcript_text: str) -> list:
    """Llama a GPT-4o-mini para detectar keywords de alto impacto."""
    system_prompt = (
        "Eres un extractor de palabras clave para contenido de salud, "
        "nutrición ancestral y entrenamiento de fuerza en español.\n"
        "Devuelve ÚNICAMENTE un array JSON válido de strings en minúsculas. "
        "Sin explicación. Sin markdown.\n"
        "Ejemplo: [\"cetosis\",\"insulina\",\"músculo\"]\n"
        "Si no hay palabras clave, devuelve: []"
    )
    url = "https://api.openai.com/v1/chat/completions"
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": transcript_text or ""},
        ],
        "max_tokens": 300,
        "temperature": 0,
    }
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    try:
        keywords = json.loads(content)
        return keywords if isinstance(keywords, list) else []
    except json.JSONDecodeError:
        return []


def burn_subtitles(video_path: str, ass_path: str, output_path: str, width: int = 0, height: int = 0):
    """Quema el archivo ASS en el video con FFmpeg, preservando resolución y aspecto original."""
    # NO usar scale filter — el filtro ass ya escala internamente via PlayResX/PlayResY
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", f"ass={ass_path}",
        "-c:v", "libx264",
        "-crf", "18",
        "-preset", "veryfast",
        "-c:a", "copy",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg burn error:\n{result.stderr}")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "subtitle-worker"})


@app.route("/subtitle-video", methods=["POST"])
def subtitle_video():
    # Verificación de secret opcional
    if WORKER_SECRET:
        auth = request.headers.get("X-Worker-Secret", "")
        if auth != WORKER_SECRET:
            return jsonify({"error": "Unauthorized"}), 401

    # Recibir video
    if "video" not in request.files:
        return jsonify({"error": "Campo 'video' requerido en multipart/form-data"}), 400

    video_file = request.files["video"]

    # Estilo opcional (A, B o C) — si no se pasa, se elige aleatoriamente
    import random
    style_id = request.form.get("style_id", random.choice(["A", "B"])).upper()
    if style_id not in ("A", "B"):
        style_id = "A"

    # Directorio de trabajo temporal único por request
    job_dir = os.path.join(tempfile.gettempdir(), f"subtitle_job_{uuid.uuid4().hex}")
    os.makedirs(job_dir, exist_ok=True)

    video_in  = os.path.join(job_dir, "input.mp4")
    audio_mp3 = os.path.join(job_dir, "audio.mp3")
    ass_file  = os.path.join(job_dir, "subtitles.ass")
    video_out = os.path.join(job_dir, "output.mp4")

    try:
        # 1. Guardar video recibido
        video_file.save(video_in)
        app.logger.info(f"[{job_dir}] Video guardado ({os.path.getsize(video_in)} bytes)")

        # 2. Extraer audio
        extract_audio(video_in, audio_mp3)
        app.logger.info(f"[{job_dir}] Audio extraído")

        # 3. Transcribir con Whisper
        whisper_result = transcribe_whisper(audio_mp3)
        app.logger.info(f"[{job_dir}] Whisper: {len(whisper_result.get('words', []))} palabras")

        # 4. Detectar keywords con GPT
        transcript_text = whisper_result.get("text", "")
        keywords = detect_keywords(transcript_text)
        app.logger.info(f"[{job_dir}] Keywords: {keywords}")

        # 5. Detectar resolución real del video con ffprobe
        probe = subprocess.run([
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0", video_in
        ], capture_output=True, text=True)
        try:
            w_str, h_str = probe.stdout.strip().split(",")
            video_w, video_h = int(w_str), int(h_str)
        except Exception:
            video_w, video_h = 1080, 1920
        app.logger.info(f"[{job_dir}] Resolución detectada: {video_w}x{video_h}")

        # 6. Generar archivo ASS
        os.environ["WHISPER_RESULT"]   = json.dumps(whisper_result)
        os.environ["KEYWORDS_RESULT"]  = json.dumps(keywords)
        os.environ["STYLE_ID"]         = style_id
        os.environ["VIDEO_WIDTH"]      = str(video_w)
        os.environ["VIDEO_HEIGHT"]     = str(video_h)
        os.environ["OUTPUT_PATH"]      = ass_file
        generate_ass_main()
        app.logger.info(f"[{job_dir}] ASS generado con estilo {style_id}")

        # 6. Quemar subtítulos
        burn_subtitles(video_in, ass_file, video_out, video_w, video_h)
        app.logger.info(f"[{job_dir}] Video procesado ({os.path.getsize(video_out)} bytes)")

        # 7. Devolver video procesado
        return send_file(
            video_out,
            mimetype="video/mp4",
            as_attachment=True,
            download_name=f"subtitulado_estilo_{style_id}.mp4",
        )

    except Exception as e:
        app.logger.error(f"[{job_dir}] Error: {e}")
        return jsonify({"error": str(e)}), 500

    finally:
        # Limpiar archivos temporales
        shutil.rmtree(job_dir, ignore_errors=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False)

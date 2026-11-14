from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import tempfile
import os
import glob
import logging
from urllib.parse import urlparse

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)

# Adicionado o instagram.com para não bloquear seus testes
ALLOWED_DOMAINS = {
    "youtube.com",
    "www.youtube.com",
    "youtu.be",
    "vimeo.com",
    "www.vimeo.com",
    "instagram.com",
    "www.instagram.com",
}

def validate_url(url):
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = (parsed.hostname or "").lower()
        return any(
            hostname == domain or hostname.endswith("." + domain)
            for domain in ALLOWED_DOMAINS
        )
    except Exception:
        return False

# Rota corrigida para /api/extract para bater com o frontend do seu Netlify
@app.route("/api/extract", methods=["POST"])
def download_video():
    data = request.get_json(silent=True) or {}
    video_url = data.get("url", "").strip()

    if not video_url:
        return jsonify({
            "success": False,
            "error": "URL não fornecida"
        }), 400

    if not validate_url(video_url):
        return jsonify({
            "success": False,
            "error": "Site não permitido ou URL inválida"
        }), 400

    temp_dir = tempfile.TemporaryDirectory()

    ydl_opts = {
        "format": "best",
        "outtmpl": os.path.join(temp_dir.name, "video.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 3,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                video_url,
                download=True
            )
            title = info.get("title", "video")
            duration = info.get("duration", 0)

        files = glob.glob(
            os.path.join(temp_dir.name, "video.*")
        )

        if not files:
            temp_dir.cleanup()
            return jsonify({
                "success": False,
                "error": "Arquivo não encontrado após o download"
            }), 500

        filepath = files[0]
        extension = os.path.splitext(filepath)[1]

        response = send_file(
            filepath,
            as_attachment=True,
            download_name=f"video{extension}",
            mimetype="application/octet-stream"
        )

        response.call_on_close(temp_dir.cleanup)
        return response

    except Exception:
        logging.exception("Erro ao baixar vídeo")
        temp_dir.cleanup()
        return jsonify({
            "success": False,
            "error": "Não foi possível baixar o vídeo."
        }), 500

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )

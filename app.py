from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import tempfile
import os
import threading
import uuid
import re
import shutil
import logging
import ipaddress
import socket
from urllib.parse import urlparse

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)

DOWNLOADS = {}
LOCK = threading.Lock()

MAX_DOWNLOAD_SIZE = 500 * 1024 * 1024  # 500 MB

QUALIDADES = {
    "360": "bestvideo[height<=360]+bestaudio/best[height<=360]/best",
    "480": "bestvideo[height<=480]+bestaudio/best[height<=480]/best",
    "720": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
    "1080": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
    "best": "bestvideo+bestaudio/best"
}


def validar_url(url):
    try:
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            return False

        host = parsed.hostname

        if not host:
            return False

        host = host.lower()

        if host == "localhost" or host.endswith(".local"):
            return False

        # Verifica IPs locais e privados.
        try:
            ip = ipaddress.ip_address(host)
            if not ip.is_global:
                return False
        except ValueError:
            pass

        # Bloqueia nomes que resolvam para endereços não públicos.
        try:
            resultados = socket.getaddrinfo(
                host, None, type=socket.SOCK_STREAM
            )

            if not resultados:
                return False

            for resultado in resultados:
                endereco = ipaddress.ip_address(
                    resultado[4][0].split("%")[0]
                )

                if not endereco.is_global:
                    return False

        except (socket.gaierror, ValueError):
            return False

        return True

    except Exception:
        return False


def limpar_nome(nome):
    nome = re.sub(r'[\\/*?:"<>|]', "", nome)
    return nome[:100] or "video"


def obter_opcoes(pasta, qualidade="best"):
    return {
        "format": QUALIDADES.get(qualidade, QUALIDADES["best"]),
        "outtmpl": os.path.join(
            pasta, "%(title).100s.%(ext)s"
        ),
        "noplaylist": True,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "max_filesize": MAX_DOWNLOAD_SIZE,
        "restrictfilenames": True,
    }


@app.route("/")
def inicio():
    return app.send_static_file("index.html")


@app.route("/api/info", methods=["POST"])
def informacoes():

    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()

    if not validar_url(url):
        return jsonify({
            "success": False,
            "error": "URL inválida ou endereço não permitido."
        }), 400

    try:
        opcoes = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 20
        }

        with yt_dlp.YoutubeDL(opcoes) as ydl:
            info = ydl.extract_info(url, download=False)

        formatos = []

        for formato in info.get("formats", []):
            if formato.get("vcodec") != "none":
                altura = formato.get("height")

                if altura:
                    formatos.append(altura)

        return jsonify({
            "success": True,
            "title": info.get("title", "Vídeo"),
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "platform": info.get("extractor_key", "Desconhecida"),
            "formats": sorted(set(formatos), reverse=True)
        })

    except Exception:
        logging.exception("Erro ao analisar vídeo")

        return jsonify({
            "success": False,
            "error": "Não foi possível acessar esse vídeo. Verifique o link e as permissões."
        }), 400


@app.route("/api/download", methods=["POST"])
def baixar():

    data = request.get_json(silent=True) or {}

    url = data.get("url", "").strip()
    qualidade = data.get("quality", "best")

    if not validar_url(url):
        return jsonify({
            "success": False,
            "error": "URL inválida."
        }), 400

    if qualidade not in QUALIDADES:
        return jsonify({
            "success": False,
            "error": "Qualidade inválida."
        }), 400

    pasta = tempfile.mkdtemp(prefix="baixador_")

    try:
        opcoes = obter_opcoes(pasta, qualidade)

        with yt_dlp.YoutubeDL(opcoes) as ydl:
            info = ydl.extract_info(url, download=True)
            arquivo = ydl.prepare_filename(info)

        # Localiza o arquivo final, inclusive após conversão.
        base = os.path.splitext(arquivo)[0]

        if not os.path.isfile(arquivo):
            candidatos = [
                base + ".mp4",
                base + ".mkv",
                base + ".webm",
                base + ".mov"
            ]

            arquivo = next(
                (f for f in candidatos if os.path.isfile(f)),
                None
            )

        if not arquivo or not os.path.isfile(arquivo):
            raise FileNotFoundError(
                "Arquivo não encontrado após o download."
            )

        tamanho = os.path.getsize(arquivo)

        if tamanho > MAX_DOWNLOAD_SIZE:
            raise ValueError(
                "O vídeo excede o limite de 500 MB."
            )

        token = str(uuid.uuid4())

        with LOCK:
            DOWNLOADS[token] = {
                "path": arquivo,
                "folder": pasta,
                "title": limpar_nome(
                    info.get("title", "video")
                )
            }

        return jsonify({
            "success": True,
            "token": token,
            "title": info.get("title", "Vídeo"),
            "duration": info.get("duration", 0),
            "size": tamanho
        })

    except Exception:
        logging.exception("Erro no download")

        shutil.rmtree(pasta, ignore_errors=True)

        return jsonify({
            "success": False,
            "error": "Não foi possível baixar o vídeo. Verifique a disponibilidade e as permissões."
        }), 500


@app.route("/api/file/<token>", methods=["GET"])
def enviar_arquivo(token):

    with LOCK:
        item = DOWNLOADS.pop(token, None)

    if not item:
        return jsonify({
            "success": False,
            "error": "Download não encontrado ou já utilizado."
        }), 404

    try:
        response = send_file(
            item["path"],
            as_attachment=True,
            download_name=(
                item["title"] +
                os.path.splitext(item["path"])[1]
            ),
            mimetype="application/octet-stream"
        )

        response.call_on_close(
            lambda: shutil.rmtree(
                item["folder"],
                ignore_errors=True
            )
        )

        return response

    except Exception:
        shutil.rmtree(item["folder"], ignore_errors=True)
        raise


if __name__ == "__main__":

    os.makedirs("static", exist_ok=True)

    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        threaded=True
    )

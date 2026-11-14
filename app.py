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
from urllib.parse import urlparse

app = Flask(__name__, static_folder="static")
CORS(app)

logging.basicConfig(level=logging.INFO)

DOWNLOADS = {}
LOCK = threading.Lock()

MAX_DOWNLOAD_SIZE = 500 * 1024 * 1024
MIN_DOWNLOAD_SIZE = 1024

QUALIDADES = {
    "360": "bv*[height<=360]+ba/b[height<=360]/b",
    "480": "bv*[height<=480]+ba/b[height<=480]/b",
    "720": "bv*[height<=720]+ba/b[height<=720]/b",
    "1080": "bv*[height<=1080]+ba/b[height<=1080]/b",
    "best": "bv*+ba/b"
}


def validar_url(url):
    try:
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            return False

        host = parsed.hostname

        if not host:
            return False

        if parsed.username or parsed.password:
            return False

        if host.lower() in ("localhost",) or host.lower().endswith(".local"):
            return False

        try:
            ip = ipaddress.ip_address(host)

            if not ip.is_global:
                return False

        except ValueError:
            pass

        return True

    except Exception:
        return False


def limpar_nome(nome):
    nome = re.sub(r'[\\/*?:"<>|]', "", str(nome))
    return nome[:100] or "video"


def localizar_arquivo(pasta):
    arquivos = []

    extensoes = (
        ".mp4", ".mkv", ".webm", ".mov",
        ".avi", ".m4v", ".flv", ".3gp"
    )

    for raiz, diretorios, nomes in os.walk(pasta):
        for nome in nomes:

            caminho = os.path.join(raiz, nome)

            if nome.endswith((".part", ".ytdl", ".temp")):
                continue

            if nome.lower().endswith(extensoes):
                if os.path.isfile(caminho):
                    tamanho = os.path.getsize(caminho)

                    if tamanho >= MIN_DOWNLOAD_SIZE:
                        arquivos.append(caminho)

    if not arquivos:
        return None

    # Seleciona o maior arquivo de mídia encontrado.
    return max(arquivos, key=os.path.getsize)


def opcoes_download(pasta, qualidade):
    return {
        "format": QUALIDADES[qualidade],
        "outtmpl": os.path.join(
            pasta, "%(title).100s.%(ext)s"
        ),
        "noplaylist": True,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 5,
        "fragment_retries": 5,
        "file_access_retries": 3,
        "max_filesize": MAX_DOWNLOAD_SIZE,
        "restrictfilenames": True,
        "overwrites": True,
        "continuedl": True,
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
            "error": "Link inválido."
        }), 400

    try:
        with yt_dlp.YoutubeDL({
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 30
        }) as ydl:

            info = ydl.extract_info(url, download=False)

        formatos = sorted(set(
            f["height"]
            for f in info.get("formats", [])
            if f.get("height") and f.get("vcodec") != "none"
        ), reverse=True)

        return jsonify({
            "success": True,
            "title": info.get("title", "Vídeo"),
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "platform": info.get("extractor_key", "Desconhecida"),
            "formats": formatos
        })

    except Exception:
        logging.exception("Falha na análise")

        return jsonify({
            "success": False,
            "error": "Não foi possível analisar este vídeo."
        }), 400


@app.route("/api/download", methods=["POST"])
def baixar():

    data = request.get_json(silent=True) or {}

    url = data.get("url", "").strip()
    qualidade = data.get("quality", "best")

    if not validar_url(url):
        return jsonify({
            "success": False,
            "error": "Link inválido."
        }), 400

    if qualidade not in QUALIDADES:
        return jsonify({
            "success": False,
            "error": "Qualidade não reconhecida."
        }), 400

    pasta = tempfile.mkdtemp(prefix="baixador_")

    try:

        logging.info("Iniciando download: %s", url)

        with yt_dlp.YoutubeDL(
            opcoes_download(pasta, qualidade)
        ) as ydl:

            info = ydl.extract_info(url, download=True)

        arquivo = localizar_arquivo(pasta)

        if not arquivo:
            raise Exception(
                "Nenhum arquivo de vídeo válido foi produzido. "
                "Verifique o FFmpeg e os formatos disponíveis."
            )

        tamanho = os.path.getsize(arquivo)

        if tamanho > MAX_DOWNLOAD_SIZE:
            raise Exception("Arquivo excede o limite de 500 MB.")

        token = str(uuid.uuid4())

        with LOCK:
            DOWNLOADS[token] = {
                "path": arquivo,
                "folder": pasta,
                "title": limpar_nome(info.get("title", "video"))
            }

        logging.info(
            "Download concluído: %s (%s bytes)",
            arquivo, tamanho
        )

        return jsonify({
            "success": True,
            "token": token,
            "title": info.get("title", "Vídeo"),
            "duration": info.get("duration", 0),
            "size": tamanho
        })

    except Exception as erro:

        logging.exception("Erro no download")

        shutil.rmtree(pasta, ignore_errors=True)

        return jsonify({
            "success": False,
            "error": str(erro)[:500]
        }), 500


@app.route("/api/file/<token>", methods=["GET"])
def enviar_arquivo(token):

    with LOCK:
        item = DOWNLOADS.get(token)

    if not item:
        return jsonify({
            "success": False,
            "error": "Arquivo não encontrado. Faça o download novamente."
        }), 404

    try:

        caminho = item["path"]

        if not os.path.isfile(caminho):
            raise FileNotFoundError("Arquivo não existe.")

        tamanho = os.path.getsize(caminho)

        if tamanho < MIN_DOWNLOAD_SIZE:
            raise ValueError("Arquivo vazio ou incompleto.")

        response = send_file(
            caminho,
            as_attachment=True,
            download_name=(
                item["title"] +
                os.path.splitext(caminho)[1]
            ),
            mimetype="application/octet-stream",
            conditional=False
        )

        def finalizar():
            with LOCK:
                DOWNLOADS.pop(token, None)

            shutil.rmtree(
                item["folder"],
                ignore_errors=True
            )

        response.call_on_close(finalizar)

        return response

    except Exception:
        logging.exception("Erro ao enviar arquivo")

        with LOCK:
            DOWNLOADS.pop(token, None)

        shutil.rmtree(item["folder"], ignore_errors=True)

        return jsonify({
            "success": False,
            "error": "Falha ao enviar o arquivo."
        }), 500


if __name__ == "__main__":

    os.makedirs("static", exist_ok=True)

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        threaded=True
    )

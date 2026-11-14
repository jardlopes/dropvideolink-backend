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
import time
from urllib.parse import urlparse

app = Flask(__name__, static_folder="static")

# expose_headers permite que o front leia o nome do arquivo (Content-Disposition)
CORS(app, expose_headers=["Content-Disposition", "Content-Length"])

logging.basicConfig(level=logging.INFO)

# Cada download vive em DOWNLOAD_ROOT/<token>/ . O token é o próprio nome da
# pasta, então NÃO depende de memória do processo (funciona com vários workers
# do gunicorn e sobrevive a reinícios do worker).
DOWNLOAD_ROOT = os.path.join(tempfile.gettempdir(), "baixador")
os.makedirs(DOWNLOAD_ROOT, exist_ok=True)

MAX_DOWNLOAD_SIZE = 500 * 1024 * 1024
MIN_DOWNLOAD_SIZE = 10 * 1024          # 10 KB: abaixo disso é erro/HTML, não vídeo
TTL_SEGUNDOS = 30 * 60                 # limpeza de arquivos esquecidos

# Cookies opcionais (Instagram e YouTube costumam exigir em servidores cloud).
# Defina a variável de ambiente COOKIES_FILE com o caminho de um cookies.txt.
COOKIES_FILE = os.environ.get("COOKIES_FILE")

TEM_FFMPEG = shutil.which("ffmpeg") is not None

if TEM_FFMPEG:
    QUALIDADES = {
        "360": "bv*[height<=360]+ba/b[height<=360]/b",
        "480": "bv*[height<=480]+ba/b[height<=480]/b",
        "720": "bv*[height<=720]+ba/b[height<=720]/b",
        "1080": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "best": "bv*+ba/b",
    }
else:
    # Sem FFmpeg não dá para juntar vídeo+áudio: usa só arquivos já combinados.
    logging.warning("FFmpeg não encontrado: usando formatos progressivos.")
    QUALIDADES = {
        "360": "b[height<=360][ext=mp4]/b[height<=360]/b",
        "480": "b[height<=480][ext=mp4]/b[height<=480]/b",
        "720": "b[height<=720][ext=mp4]/b[height<=720]/b",
        "1080": "b[height<=1080][ext=mp4]/b[height<=1080]/b",
        "best": "b[ext=mp4]/b",
    }

EXTENSOES = (".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".flv", ".3gp")


def validar_url(url):
    """Aceita só http(s) público. Resolve o DNS para bloquear IPs internos (SSRF)."""
    try:
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            return False

        host = parsed.hostname
        if not host or parsed.username or parsed.password:
            return False

        if host.lower() == "localhost" or host.lower().endswith(".local"):
            return False

        try:
            ips = [ipaddress.ip_address(host)]
        except ValueError:
            infos = socket.getaddrinfo(host, None)
            ips = [ipaddress.ip_address(i[4][0]) for i in infos]

        return all(ip.is_global for ip in ips)

    except Exception:
        return False


def token_valido(token):
    try:
        return str(uuid.UUID(token)) == token
    except (ValueError, AttributeError):
        return False


def localizar_arquivo(pasta):
    candidatos = []

    for raiz, _, nomes in os.walk(pasta):
        for nome in nomes:
            if nome.endswith((".part", ".ytdl", ".temp")):
                continue
            if not nome.lower().endswith(EXTENSOES):
                continue

            caminho = os.path.join(raiz, nome)
            if os.path.isfile(caminho) and os.path.getsize(caminho) >= MIN_DOWNLOAD_SIZE:
                candidatos.append(caminho)

    return max(candidatos, key=os.path.getsize) if candidatos else None


def opcoes_base():
    opcoes = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 30,
    }
    if COOKIES_FILE and os.path.isfile(COOKIES_FILE):
        opcoes["cookiefile"] = COOKIES_FILE
    return opcoes


def opcoes_download(pasta, qualidade):
    opcoes = opcoes_base()
    opcoes.update({
        "format": QUALIDADES[qualidade],
        "outtmpl": os.path.join(pasta, "%(title).80B.%(ext)s"),
        "restrictfilenames": True,
        "overwrites": True,
        "continuedl": True,
        "retries": 5,
        "fragment_retries": 5,
        "file_access_retries": 3,
        "max_filesize": MAX_DOWNLOAD_SIZE,
    })
    if TEM_FFMPEG:
        opcoes["merge_output_format"] = "mp4"
    return opcoes


def mensagem_erro(erro):
    texto = str(erro)
    texto = re.sub(r"\x1b\[[0-9;]*m", "", texto)  # remove cores ANSI do yt-dlp
    baixo = texto.lower()

    if "sign in" in baixo or "login" in baixo or "cookies" in baixo or "bot" in baixo:
        return ("A plataforma exigiu login/verificação (comum em servidores na nuvem). "
                "Configure um cookies.txt no servidor (COOKIES_FILE).")
    if "private" in baixo:
        return "Este vídeo é privado."
    if "unsupported url" in baixo:
        return "Link não suportado."
    return texto[:300]


def limpar_antigos():
    agora = time.time()
    try:
        for nome in os.listdir(DOWNLOAD_ROOT):
            caminho = os.path.join(DOWNLOAD_ROOT, nome)
            if os.path.isdir(caminho) and agora - os.path.getmtime(caminho) > TTL_SEGUNDOS:
                shutil.rmtree(caminho, ignore_errors=True)
    except Exception:
        logging.exception("Falha na limpeza")


def loop_limpeza():
    while True:
        time.sleep(300)
        limpar_antigos()


threading.Thread(target=loop_limpeza, daemon=True).start()


@app.route("/")
def inicio():
    return app.send_static_file("index.html")


@app.route("/api/health")
def saude():
    return jsonify({
        "ok": True,
        "ffmpeg": TEM_FFMPEG,
        "yt_dlp": yt_dlp.version.__version__,
    })


@app.route("/api/info", methods=["POST"])
def informacoes():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url", "")).strip()

    if not validar_url(url):
        return jsonify({"success": False, "error": "Link inválido."}), 400

    try:
        with yt_dlp.YoutubeDL(opcoes_base()) as ydl:
            info = ydl.extract_info(url, download=False)

        formatos = sorted({
            f["height"]
            for f in info.get("formats", [])
            if f.get("height") and f.get("vcodec") != "none"
        }, reverse=True)

        return jsonify({
            "success": True,
            "title": info.get("title", "Vídeo"),
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "platform": info.get("extractor_key", "Desconhecida"),
            "formats": formatos,
        })

    except Exception as erro:
        logging.exception("Falha na análise")
        return jsonify({"success": False, "error": mensagem_erro(erro)}), 400


@app.route("/api/download", methods=["POST"])
def baixar():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url", "")).strip()
    qualidade = data.get("quality", "best")

    if not validar_url(url):
        return jsonify({"success": False, "error": "Link inválido."}), 400

    if qualidade not in QUALIDADES:
        return jsonify({"success": False, "error": "Qualidade não reconhecida."}), 400

    token = str(uuid.uuid4())
    pasta = os.path.join(DOWNLOAD_ROOT, token)
    os.makedirs(pasta, exist_ok=True)

    try:
        logging.info("Iniciando download: %s", url)

        with yt_dlp.YoutubeDL(opcoes_download(pasta, qualidade)) as ydl:
            info = ydl.extract_info(url, download=True)

        arquivo = localizar_arquivo(pasta)

        if not arquivo:
            raise Exception(
                "Nenhum vídeo válido foi gerado (a plataforma pode ter bloqueado "
                "o servidor, o vídeo passou de 500 MB ou falta o FFmpeg)."
            )

        tamanho = os.path.getsize(arquivo)
        logging.info("Download concluído: %s (%s bytes)", arquivo, tamanho)

        return jsonify({
            "success": True,
            "token": token,
            "title": info.get("title", "Vídeo"),
            "duration": info.get("duration", 0),
            "size": tamanho,
        })

    except Exception as erro:
        logging.exception("Erro no download")
        shutil.rmtree(pasta, ignore_errors=True)
        return jsonify({"success": False, "error": mensagem_erro(erro)}), 500


@app.route("/api/file/<token>", methods=["GET"])
def enviar_arquivo(token):
    if not token_valido(token):
        return jsonify({"success": False, "error": "Token inválido."}), 400

    pasta = os.path.join(DOWNLOAD_ROOT, token)
    arquivo = localizar_arquivo(pasta) if os.path.isdir(pasta) else None

    if not arquivo:
        return jsonify({
            "success": False,
            "error": "Arquivo não encontrado ou expirado. Faça o download novamente.",
        }), 404

    response = send_file(
        arquivo,
        as_attachment=True,
        download_name=os.path.basename(arquivo),
        mimetype="video/mp4" if arquivo.lower().endswith(".mp4") else "application/octet-stream",
    )

    response.call_on_close(lambda: shutil.rmtree(pasta, ignore_errors=True))
    return response


if __name__ == "__main__":
    os.makedirs("static", exist_ok=True)
    porta = int(os.environ.get("PORT", 5000))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    app.run(host=host, port=porta, debug=False, threaded=True)

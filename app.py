from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

@app.route('/')
def home():
    return "DropVideoLink Backend Operacional!"

@app.route('/api/extract', methods=['POST'])
def extract_video():
    data = request.get_json()
    url = data.get('url')
    
    if not url:
        return jsonify({'error': 'URL não informada'}), 400

    ydl_opts = {
        'format': 'best',
        'quiet': True,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extrai os dados do vídeo sem baixar o arquivo inteiro para o servidor (economiza memória)
            info = ydl.extract_info(url, download=False)
            
            # Pega o link direto de streaming/download do vídeo ou o melhor formato
            formats = info.get('formats', [])
            direct_url = None
            
            # Procura um formato que tenha vídeo e áudio juntos ou o melhor disponível
            for f in formats:
                if f.get('url') and f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                    direct_url = f.get('url')
                    break
            
            if not direct_url and formats:
                direct_url = formats[0].get('url')

            return jsonify({
                'success': True,
                'title': info.get('title', 'Vídeo sem título'),
                'duration': info.get('duration_string', '00:00'),
                'thumbnail': info.get('thumbnail', ''),
                'download_url': direct_url,
                'ext': info.get('ext', 'mp4')
            })
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

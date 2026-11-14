from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

@app.route('/api/extract', methods=['POST'])
def extract_video():
    data = request.get_json()
    video_url = data.get('url')
    
    if not video_url:
        return jsonify({'success': False, 'error': 'URL não fornecida'}), 400

    ydl_opts = {
        'format': 'best',
        'noplaylist': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            
            # Pega o link de download direto extraído pelo yt-dlp
            download_url = info.get('url')
            title = info.get('title', 'video')
            duration = info.get('duration', 0)

            if not download_url:
                return jsonify({'success': False, 'error': 'Não foi possível extrair o link direto'}), 500

            return jsonify({
                'success': True,
                'title': title,
                'duration': duration,
                'download_url': download_url
            })
            
    except Exception as e:
        print(f"Erro na extração: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

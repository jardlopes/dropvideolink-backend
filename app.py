import os
import tempfile
from flask import Flask, request, jsonify, send_file
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

    # Cria um diretório temporário seguro para baixar o vídeo
    temp_dir = tempfile.mkdtemp()
    output_template = os.path.join(temp_dir, '%(id)s.%(ext)s')

    ydl_opts = {
        'format': 'best',
        'outtmpl': output_template,
        'noplaylist': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            filename = ydl.prepare_filename(info)
            
            # Retorna o arquivo binário real para o frontend
            return send_file(
                filename,
                as_attachment=True,
                download_name=f"{info.get('title', 'video')}.mp4"
            )
    except Exception as e:
        print(f"Erro no download: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

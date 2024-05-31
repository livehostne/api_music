from flask import Flask, request, Response, jsonify, render_template, redirect, url_for, session
from yt_dlp import YoutubeDL
import requests
import logging
import urllib.parse
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime, timedelta
import jwt
import pytz
import bcrypt

# Desativar logs do yt-dlp
logging.basicConfig(level=logging.ERROR)

app = Flask(__name__)
app.config['SECRET_KEY'] = '9agos2010'

# Configurações do downloader
ydl_opts = {
    'format': 'bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
    'noplaylist': True,
    'quiet': True,  # Suprime a saída de log do yt-dlp
    'no_warnings': True  # Suprime avisos
}

# Configurar o fuso horário de São Paulo
tz = pytz.timezone('America/Sao_Paulo')

# Configuração do MongoDB
client = MongoClient("mongodb+srv://server1:9agos2010@tokens.hlnd5wn.mongodb.net/?retryWrites=true&w=majority&appName=tokens")
db = client['token_db']
tokens_collection = db['tokens']

# Usuário e senha admin
ADMIN_USERNAME = 'ardems37'
ADMIN_PASSWORD_HASH = bcrypt.hashpw('9agos2010'.encode('utf-8'), bcrypt.gensalt())

def check_password(password, hashed):
    return bcrypt.checkpw(password.encode('utf-8'), hashed)

# Função para obter URL do stream de áudio
def get_audio_stream_url(musica: str):
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch:{musica}", download=False)
        url = info['entries'][0]['url']
        return url

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == ADMIN_USERNAME and check_password(password, ADMIN_PASSWORD_HASH):
            session['logged_in'] = True
            return redirect(url_for('admin'))
        else:
            return 'Invalid credentials', 401
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/admin')
def admin():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    tokens = list(tokens_collection.find())
    tokens = [
        {
            **token,
            'expiration': token['expiration'].astimezone(tz)
        } for token in tokens
    ]
    return render_template('admin.html', tokens=tokens)

@app.route('/admin/create_token', methods=['POST'])
def create_token():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    data = request.form
    token_type = data['tokenType']

    if token_type == 'test':
        expiration_time = datetime.now(tz) + timedelta(days=1)
        max_usage = 50
    else:
        expiration_days = int(data['expiration'])
        expiration_time = datetime.now(tz) + timedelta(days=expiration_days)
        max_usage = int(data['max_usage'])

    token = jwt.encode({
        'username': data['username'],
        'exp': expiration_time
    }, app.config['SECRET_KEY'], algorithm="HS256")

    token_data = {
        'token': token,
        'expiration': expiration_time,
        'max_usage': max_usage,
        'usage_count': 0
    }

    tokens_collection.insert_one(token_data)
    return redirect(url_for('admin'))

@app.route('/admin/delete_token/<id>')
def delete_token(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    tokens_collection.delete_one({'_id': ObjectId(id)})
    return redirect(url_for('admin'))

@app.route('/api/msc/', methods=['GET'])
def download_musica():
    token = request.args.get('token')
    musica = request.args.get('musica')

    if not token:
        return jsonify({"error": "Token é obrigatório"}), 400
    if not musica:
        return jsonify({"error": "Parâmetro 'musica' é obrigatório"}), 400

    try:
        decoded = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expirou"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Token inválido entre em contato com @ardems37, telegram"}), 401

    token_entry = tokens_collection.find_one({'token': token})
    if token_entry is None:
        return jsonify({"error": "Token inválido"}), 401

    if token_entry['usage_count'] >= token_entry['max_usage']:
        return jsonify({"error": "Token atingiu o limite de uso"}), 403

    tokens_collection.update_one({'_id': token_entry['_id']}, {'$inc': {'usage_count': 1}})

    # Substitui "+" por " " nos espaços da música
    musica = urllib.parse.unquote_plus(musica)

    try:
        audio_url = get_audio_stream_url(musica)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    def generate():
        with requests.get(audio_url, stream=True) as r:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk

    headers = {
        'Content-Disposition': f'attachment; filename="{musica}.mp3"',
        'Content-Type': 'audio/mpeg',
    }

    return Response(generate(), headers=headers)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)

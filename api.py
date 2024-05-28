from flask import Flask, request, Response, jsonify, render_template, redirect, url_for, session
from yt_dlp import YoutubeDL
import requests
import logging
import urllib.parse
import sqlite3
from datetime import datetime, timedelta
import jwt
import pytz

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

def init_db():
    conn = sqlite3.connect('tokens.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tokens
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT, expiration DATETIME, max_usage INTEGER, usage_count INTEGER)''')
    conn.commit()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect('tokens.db')
    conn.row_factory = sqlite3.Row
    return conn

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
        if username == 'ardems37' and password == '9agos2010':
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
    conn = get_db_connection()
    tokens = conn.execute('SELECT * FROM tokens').fetchall()
    tokens = [
        {
            **token,
            'expiration': datetime.strptime(token['expiration'].split('.')[0], '%Y-%m-%d %H:%M:%S').astimezone(tz)
        } for token in tokens
    ]
    conn.close()
    return render_template('admin.html', tokens=tokens)

@app.route('/admin/create_token', methods=['POST'])
def create_token():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    data = request.form
    token_type = data['tokenType']
    
    if token_type == 'test':
        expiration_time = datetime.now(tz) + timedelta(hours=1)
        max_usage = 20
    else:
        expiration_minutes = int(data['expiration'])
        expiration_time = datetime.now(tz) + timedelta(minutes=expiration_minutes)
        max_usage = int(data['max_usage'])
    
    token = jwt.encode({
        'username': data['username'],
        'exp': expiration_time
    }, app.config['SECRET_KEY'], algorithm="HS256")

    conn = get_db_connection()
    conn.execute('INSERT INTO tokens (token, expiration, max_usage, usage_count) VALUES (?, ?, ?, ?)',
                 (token, expiration_time.strftime('%Y-%m-%d %H:%M:%S.%f'), max_usage, 0))
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))

@app.route('/admin/delete_token/<int:id>')
def delete_token(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    conn = get_db_connection()
    conn.execute('DELETE FROM tokens WHERE id = ?', (id,))
    conn.commit()
    conn.close()
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

    conn = get_db_connection()
    token_entry = conn.execute('SELECT * FROM tokens WHERE token = ?', (token,)).fetchone()
    if token_entry is None:
        conn.close()
        return jsonify({"error": "Token inválido"}), 401

    if token_entry['usage_count'] >= token_entry['max_usage']:
        conn.close()
        return jsonify({"error": "Token atingiu o limite de uso"}), 403

    conn.execute('UPDATE tokens SET usage_count = usage_count + 1 WHERE token = ?', (token,))
    conn.commit()
    conn.close()

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
    init_db()
    app.run(host='0.0.0.0', port=8000)

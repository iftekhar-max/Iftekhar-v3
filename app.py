from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file
from flask_socketio import SocketIO, emit
import os
import subprocess
import sys
import threading
import time
import json
import shutil
import zipfile
import uuid
from datetime import datetime
import psutil
import signal

app = Flask(__name__)
app.secret_key = 'iftekhar-hosting-secret-key-2024'
socketio = SocketIO(app, cors_allowed_origins="*")

# কনফিগারেশন
UPLOAD_FOLDER = 'user_uploads'
ALLOWED_EXTENSIONS = {'py', 'txt', 'json', 'html', 'css', 'js', 'zip'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ইউজার ডাটা
USERS_FILE = 'users.json'
PROJECTS_FILE = 'projects.json'

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f)

def load_projects():
    if os.path.exists(PROJECTS_FILE):
        with open(PROJECTS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_projects(projects):
    with open(PROJECTS_FILE, 'w') as f:
        json.dump(projects, f)

# রানিং প্রসেস ট্র্যাকিং
running_processes = {}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        users = load_users()
        username = request.json.get('username')
        password = request.json.get('password')
        email = request.json.get('email')
        
        if username in users:
            return jsonify({'success': False, 'message': 'Username already exists'})
        
        users[username] = {
            'password': password,
            'email': email,
            'created_at': datetime.now().isoformat(),
            'projects': []
        }
        save_users(users)
        
        # ইউজারের ফোল্ডার তৈরি
        user_folder = os.path.join(UPLOAD_FOLDER, username)
        os.makedirs(user_folder, exist_ok=True)
        
        return jsonify({'success': True, 'message': 'Registration successful'})
    
    return render_template('register.html')

@app.route('/login', methods=['POST'])
def login():
    users = load_users()
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    if username in users and users[username]['password'] == password:
        session['username'] = username
        return jsonify({'success': True, 'message': 'Login successful'})
    
    return jsonify({'success': False, 'message': 'Invalid credentials'})

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('index'))
    return render_template('dashboard.html', username=session['username'])

@app.route('/file-manager')
def file_manager():
    if 'username' not in session:
        return redirect(url_for('index'))
    return render_template('file_manager.html', username=session['username'])

@app.route('/api/files', methods=['GET'])
def get_files():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    username = session['username']
    user_folder = os.path.join(UPLOAD_FOLDER, username)
    
    files = []
    if os.path.exists(user_folder):
        for item in os.listdir(user_folder):
            item_path = os.path.join(user_folder, item)
            files.append({
                'name': item,
                'type': 'folder' if os.path.isdir(item_path) else 'file',
                'size': os.path.getsize(item_path) if os.path.isfile(item_path) else 0,
                'path': item,
                'modified': datetime.fromtimestamp(os.path.getmtime(item_path)).isoformat()
            })
    
    return jsonify(files)

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    
    file = request.files['file']
    username = session['username']
    user_folder = os.path.join(UPLOAD_FOLDER, username)
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    filename = file.filename
    filepath = os.path.join(user_folder, filename)
    
    # ZIP ফাইল আনজিপ
    if filename.endswith('.zip'):
        file.save(filepath)
        with zipfile.ZipFile(filepath, 'r') as zip_ref:
            zip_ref.extractall(user_folder)
        os.remove(filepath)
        return jsonify({'success': True, 'message': 'ZIP extracted successfully'})
    else:
        file.save(filepath)
        return jsonify({'success': True, 'message': 'File uploaded successfully'})

@app.route('/api/delete', methods=['POST'])
def delete_file():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    filename = data.get('filename')
    username = session['username']
    filepath = os.path.join(UPLOAD_FOLDER, username, filename)
    
    if os.path.exists(filepath):
        if os.path.isdir(filepath):
            shutil.rmtree(filepath)
        else:
            os.remove(filepath)
        return jsonify({'success': True})
    
    return jsonify({'error': 'File not found'}), 404

@app.route('/api/run', methods=['POST'])
def run_code():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    filename = data.get('filename')
    username = session['username']
    filepath = os.path.join(UPLOAD_FOLDER, username, filename)
    
    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404
    
    # আগের প্রসেস বন্ধ
    if username in running_processes:
        try:
            os.kill(running_processes[username].pid, signal.SIGTERM)
        except:
            pass
    
    try:
        process_id = str(uuid.uuid4())[:8]
        
        def run_script(username):
            username = session.get('username')
            user_folder = os.path.join(UPLOAD_FOLDER, username)
            process = subprocess.Popen(
                [sys.executable, filename],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=user_folder
            )
            running_processes[username] = process
            
            output, error = process.communicate(timeout=30)
            
            result = {
                'output': output,
                'error': error,
                'return_code': process.returncode
            }
            
            socketio.emit('run_result', {
            'user': username,
            'result': result,
            'process_id': process_id
        })
            
        if username in running_processes:
            del running_processes[username]
        
        thread = threading.Thread(target=run_script, args=(username,)}
        thread.start()
        
        return jsonify({'success': True, 'process_id': process_id, 'message': 'Code running...'})
    
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Execution timeout (30s)'}), 408
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stop', methods=['POST'])
def stop_code():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    username = session['username']
    
    if username in running_processes:
        try:
            running_processes[username].terminate()
            time.sleep(1)
            if running_processes[username].poll() is None:
                running_processes[username].kill()
            del running_processes[username]
            return jsonify({'success': True, 'message': 'Process stopped'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    return jsonify({'message': 'No process running'})

@app.route('/api/save', methods=['POST'])
def save_file():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    filename = data.get('filename')
    content = data.get('content')
    username = session['username']
    filepath = os.path.join(UPLOAD_FOLDER, username, filename)
    
    # ফোল্ডার তৈরি
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return jsonify({'success': True, 'message': 'File saved'})

@app.route('/api/file-content', methods=['POST'])
def get_file_content():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    filename = data.get('filename')
    username = session['username']
    filepath = os.path.join(UPLOAD_FOLDER, username, filename)
    
    if os.path.exists(filepath) and os.path.isfile(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        return jsonify({'content': content})
    
    return jsonify({'error': 'File not found'}), 404

@app.route('/api/system-stats', methods=['GET'])
def system_stats():
    return jsonify({
        'cpu': psutil.cpu_percent(),
        'memory': psutil.virtual_memory().percent,
        'disk': psutil.disk_usage('/').percent
    })

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@socketio.on('connect')
def handle_connect():
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)

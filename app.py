# app.py
# ইফতেখার হোস্টিং বোর্ড - ব্যাকএন্ড লজিক

from flask import Flask, request, jsonify, session, send_from_directory, render_template_string
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import json
import uuid
import shutil
import zipfile
import threading
import time
import random
import subprocess
import signal
import psutil
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = 'iftekhar_hosting_board_secret_key_2025'
CORS(app)

# কনফিগারেশন
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_DIR = os.path.join(BASE_DIR, 'users')
FILES_DIR = os.path.join(BASE_DIR, 'user_files')
ALLOWED_EXTENSIONS = {'zip'}

# ডিরেক্টরি তৈরি
os.makedirs(USERS_DIR, exist_ok=True)
os.makedirs(FILES_DIR, exist_ok=True)

# ইউজার ডাটাবেস সিমুলেশন
users_db = {}
user_sessions = {}
server_processes = {}
server_status = {}
user_file_systems = {}
user_main_files = {}

# হেল্পার ফাংশন
def load_users():
    """ইউজার ডাটাবেস লোড করা"""
    global users_db
    users_file = os.path.join(USERS_DIR, 'users.json')
    if os.path.exists(users_file):
        with open(users_file, 'r', encoding='utf-8') as f:
            users_db = json.load(f)
    else:
        # ডিফল্ট ইউজার
        users_db = {
            'admin': {
                'password': generate_password_hash('admin123'),
                'email': 'admin@iftekhar.com',
                'created_at': datetime.now().isoformat()
            },
            'iftekhar': {
                'password': generate_password_hash('iftekhar123'),
                'email': 'iftekhar@hosting.com',
                'created_at': datetime.now().isoformat()
            },
            'guest': {
                'password': generate_password_hash('guest123'),
                'email': 'guest@example.com',
                'created_at': datetime.now().isoformat()
            }
        }
        save_users()

def save_users():
    """ইউজার ডাটাবেস সেভ করা"""
    users_file = os.path.join(USERS_DIR, 'users.json')
    with open(users_file, 'w', encoding='utf-8') as f:
        json.dump(users_db, f, indent=2, ensure_ascii=False)

def get_user_dir(username):
    """ইউজারের ফাইল ডিরেক্টরি পাওয়া"""
    user_dir = os.path.join(FILES_DIR, username)
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

def load_user_files(username):
    """ইউজারের ফাইল সিস্টেম লোড করা"""
    if username not in user_file_systems:
        user_file_systems[username] = {}
    
    user_dir = get_user_dir(username)
    file_system = {}
    
    def build_tree(path, relative_path=""):
        tree = {}
        try:
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                relative_item_path = os.path.join(relative_path, item) if relative_path else item
                
                if os.path.isdir(item_path):
                    tree[item] = {
                        'type': 'folder',
                        'name': item,
                        'path': relative_item_path,
                        'children': build_tree(item_path, relative_item_path),
                        'fileCount': sum(1 for f in os.listdir(item_path) if os.path.isfile(os.path.join(item_path, f)))
                    }
                else:
                    file_stat = os.stat(item_path)
                    with open(item_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    
                    tree[item] = {
                        'type': 'file',
                        'name': item,
                        'path': relative_item_path,
                        'content': content,
                        'size': format_file_size(file_stat.st_size),
                        'uploadDate': datetime.fromtimestamp(file_stat.st_mtime).isoformat()
                    }
        except Exception as e:
            print(f"Error building tree: {e}")
        return tree
    
    user_file_systems[username] = build_tree(user_dir)
    return user_file_systems[username]

def format_file_size(size_bytes):
    """ফাইল সাইজ ফরম্যাট করা"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

def save_file_to_system(username, file_path, content):
    """ফাইল সিস্টেমে ফাইল সেভ করা"""
    user_dir = get_user_dir(username)
    full_path = os.path.join(user_dir, file_path)
    
    # ডিরেক্টরি তৈরি
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    
    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    # ফাইল সিস্টেম রিলোড
    load_user_files(username)
    return True

def delete_file_from_system(username, file_path):
    """ফাইল সিস্টেম থেকে ফাইল ডিলিট করা"""
    user_dir = get_user_dir(username)
    full_path = os.path.join(user_dir, file_path)
    
    if os.path.exists(full_path):
        os.remove(full_path)
        load_user_files(username)
        return True
    return False

def extract_zip_to_user(username, zip_file):
    """ZIP ফাইল এক্সট্র্যাক্ট করা"""
    user_dir = get_user_dir(username)
    
    try:
        with zipfile.ZipFile(zip_file, 'r') as zip_ref:
            zip_ref.extractall(user_dir)
        
        load_user_files(username)
        return True
    except Exception as e:
        print(f"Error extracting zip: {e}")
        return False

# ডেকোরেটর: লগইন প্রয়োজন
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return jsonify({'error': 'Unauthorized', 'message': 'প্লিজ লগইন করুন'}), 401
        return f(*args, **kwargs)
    return decorated_function

# API রাউটস

@app.route('/')
def index():
    """হোম পেজ"""
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ইফতেখার হোস্টিং বোর্ড</title>
        <style>
            body { font-family: Arial, sans-serif; background: linear-gradient(135deg, #0a0a0a, #0a0515); color: white; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
            .login-container { background: rgba(15, 20, 45, 0.4); backdrop-filter: blur(10px); padding: 40px; border-radius: 20px; border: 1px solid rgba(255,77,77,0.3); width: 350px; }
            h2 { text-align: center; color: #ff4d4d; }
            input { width: 100%; padding: 12px; margin: 10px 0; background: rgba(255,255,255,0.1); border: 1px solid rgba(255,77,77,0.3); border-radius: 8px; color: white; }
            button { width: 100%; padding: 12px; background: linear-gradient(135deg, #ff4d4d, #4d4dff); border: none; border-radius: 8px; color: white; cursor: pointer; font-size: 16px; }
            button:hover { transform: scale(1.02); }
            .error { color: #ff4444; text-align: center; margin-top: 10px; }
            .info { color: #00ff00; text-align: center; margin-top: 10px; }
        </style>
    </head>
    <body>
        <div class="login-container">
            <h2>🔐 ইফতেখার হোস্টিং বোর্ড</h2>
            <form id="loginForm">
                <input type="text" id="username" placeholder="ইউজারনেম" required>
                <input type="password" id="password" placeholder="পাসওয়ার্ড" required>
                <button type="submit">লগইন করুন</button>
            </form>
            <div id="message"></div>
            <div style="text-align: center; margin-top: 20px; font-size: 12px; color: #aaa;">
                ডেমো ইউজার: iftekhar / iftekhar123 <br>
                অথবা admin / admin123
            </div>
        </div>
        <script>
            document.getElementById('loginForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                const username = document.getElementById('username').value;
                const password = document.getElementById('password').value;
                
                const response = await fetch('/api/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                });
                
                const data = await response.json();
                if (response.ok) {
                    document.getElementById('message').innerHTML = '<div class="info">✅ লগইন সফল! রিডাইরেক্ট হচ্ছে...</div>';
                    setTimeout(() => {
                        window.location.href = '/dashboard';
                    }, 1000);
                } else {
                    document.getElementById('message').innerHTML = '<div class="error">❌ ' + data.message + '</div>';
                }
            });
        </script>
    </body>
    </html>
    """)

@app.route('/dashboard')
def dashboard():
    """ড্যাশবোর্ড পেজ"""
    if 'username' not in session:
        return redirect('/')
    return send_from_directory('.', 'dashboard.html')

@app.route('/api/login', methods=['POST'])
def login():
    """লগইন API"""
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    load_users()
    
    if username in users_db and check_password_hash(users_db[username]['password'], password):
        session['username'] = username
        session.permanent = True
        
        # ইউজারের ফাইল সিস্টেম লোড
        load_user_files(username)
        
        return jsonify({
            'success': True,
            'username': username,
            'message': 'লগইন সফল'
        })
    
    return jsonify({'error': 'Invalid credentials', 'message': 'ভুল ইউজারনেম বা পাসওয়ার্ড'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    """লগআউট API"""
    session.clear()
    return jsonify({'success': True, 'message': 'লগআউট সফল'})

@app.route('/api/register', methods=['POST'])
def register():
    """রেজিস্ট্রেশন API"""
    data = request.json
    username = data.get('username')
    password = data.get('password')
    email = data.get('email')
    
    load_users()
    
    if username in users_db:
        return jsonify({'error': 'User exists', 'message': 'এই ইউজারনেম ইতিমধ্যে নেওয়া হয়েছে'}), 400
    
    users_db[username] = {
        'password': generate_password_hash(password),
        'email': email,
        'created_at': datetime.now().isoformat()
    }
    save_users()
    
    return jsonify({'success': True, 'message': 'রেজিস্ট্রেশন সফল! এখন লগইন করুন'})

@app.route('/api/user/info', methods=['GET'])
@login_required
def get_user_info():
    """ইউজার ইনফো পাওয়া"""
    return jsonify({
        'username': session['username'],
        'email': users_db.get(session['username'], {}).get('email', ''),
        'created_at': users_db.get(session['username'], {}).get('created_at', '')
    })

# ফাইল ম্যানেজমেন্ট API

@app.route('/api/files/list', methods=['GET'])
@login_required
def list_files():
    """ফাইল লিস্ট API"""
    username = session['username']
    file_system = load_user_files(username)
    return jsonify({
        'success': True,
        'files': file_system,
        'main_file': user_main_files.get(username)
    })

@app.route('/api/files/upload', methods=['POST'])
@login_required
def upload_file():
    """জিপ ফাইল আপলোড API"""
    username = session['username']
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file', 'message': 'কোন ফাইল পাঠানো হয়নি'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'Empty filename', 'message': 'ফাইলের নাম খালি'}), 400
    
    if not file.filename.endswith('.zip'):
        return jsonify({'error': 'Invalid format', 'message': 'শুধুমাত্র ZIP ফাইল সাপোর্ট করে'}), 400
    
    # টেম্প ফাইল সেভ
    temp_path = os.path.join(get_user_dir(username), f'temp_{uuid.uuid4().hex}.zip')
    file.save(temp_path)
    
    # জিপ এক্সট্র্যাক্ট
    success = extract_zip_to_user(username, temp_path)
    
    # টেম্প ফাইল ডিলিট
    os.remove(temp_path)
    
    if success:
        return jsonify({'success': True, 'message': 'ZIP ফাইল সফলভাবে আপলোড ও এক্সট্র্যাক্ট করা হয়েছে'})
    else:
        return jsonify({'error': 'Extraction failed', 'message': 'ZIP ফাইল এক্সট্র্যাক্ট করতে ব্যর্থ'}), 500

@app.route('/api/files/save', methods=['POST'])
@login_required
def save_file():
    """ফাইল সেভ API"""
    username = session['username']
    data = request.json
    file_path = data.get('path')
    content = data.get('content')
    
    if not file_path:
        return jsonify({'error': 'No path', 'message': 'ফাইলের পাথ প্রয়োজন'}), 400
    
    try:
        save_file_to_system(username, file_path, content)
        return jsonify({'success': True, 'message': 'ফাইল সফলভাবে সেভ করা হয়েছে'})
    except Exception as e:
        return jsonify({'error': 'Save failed', 'message': str(e)}), 500

@app.route('/api/files/delete', methods=['POST'])
@login_required
def delete_file():
    """ফাইল ডিলিট API"""
    username = session['username']
    data = request.json
    file_path = data.get('path')
    
    if not file_path:
        return jsonify({'error': 'No path', 'message': 'ফাইলের পাথ প্রয়োজন'}), 400
    
    if delete_file_from_system(username, file_path):
        # মেইন ফাইল আনসেট
        if user_main_files.get(username) == file_path:
            del user_main_files[username]
        return jsonify({'success': True, 'message': 'ফাইল ডিলিট করা হয়েছে'})
    else:
        return jsonify({'error': 'Delete failed', 'message': 'ফাইল ডিলিট করতে ব্যর্থ'}), 500

@app.route('/api/files/set-main', methods=['POST'])
@login_required
def set_main_file():
    """মেইন ফাইল সেট API"""
    username = session['username']
    data = request.json
    file_path = data.get('path')
    
    user_main_files[username] = file_path
    return jsonify({'success': True, 'message': f'মেইন ফাইল সেট করা হয়েছে: {file_path}'})

@app.route('/api/files/content', methods=['GET'])
@login_required
def get_file_content():
    """ফাইল কন্টেন্ট পাওয়া"""
    username = session['username']
    file_path = request.args.get('path')
    
    user_dir = get_user_dir(username)
    full_path = os.path.join(user_dir, file_path)
    
    if os.path.exists(full_path):
        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        return jsonify({'success': True, 'content': content})
    else:
        return jsonify({'error': 'File not found', 'message': 'ফাইল পাওয়া যায়নি'}), 404

# সার্ভার ম্যানেজমেন্ট API

@app.route('/api/server/start', methods=['POST'])
@login_required
def start_server():
    """সার্ভার স্টার্ট API"""
    username = session['username']
    
    if username in server_status and server_status[username].get('running', False):
        return jsonify({'success': False, 'message': 'সার্ভার ইতিমধ্যে চলছে'})
    
    # ইউজারের ফাইল ডিরেক্টরি
    user_dir = get_user_dir(username)
    main_file = user_main_files.get(username)
    
    if not main_file:
        return jsonify({'success': False, 'message': 'কোন মেইন ফাইল সেট করা নেই'}), 400
    
    main_file_path = os.path.join(user_dir, main_file)
    
    if not os.path.exists(main_file_path):
        return jsonify({'success': False, 'message': 'মেইন ফাইল পাওয়া যায়নি'}), 404
    
    try:
        # পাইথন স্ক্রিপ্ট রান (যদি .py ফাইল হয়)
        if main_file.endswith('.py'):
            process = subprocess.Popen(
                ['python', main_file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=user_dir
            )
            server_processes[username] = process
            server_status[username] = {
                'running': True,
                'pid': process.pid,
                'started_at': datetime.now().isoformat(),
                'main_file': main_file
            }
            return jsonify({'success': True, 'message': f'সার্ভার স্টার্ট হয়েছে (PID: {process.pid})'})
        else:
            return jsonify({'success': False, 'message': 'শুধুমাত্র .py ফাইল রান করা যায়'}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/server/stop', methods=['POST'])
@login_required
def stop_server():
    """সার্ভার স্টপ API"""
    username = session['username']
    
    if username not in server_status or not server_status[username].get('running', False):
        return jsonify({'success': False, 'message': 'সার্ভার চলছে না'})
    
    try:
        process = server_processes.get(username)
        if process:
            process.terminate()
            process.wait(timeout=5)
            server_status[username]['running'] = False
            return jsonify({'success': True, 'message': 'সার্ভার বন্ধ করা হয়েছে'})
        else:
            return jsonify({'success': False, 'message': 'প্রসেস পাওয়া যায়নি'}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/server/restart', methods=['POST'])
@login_required
def restart_server():
    """সার্ভার রিস্টার্ট API"""
    stop_result = stop_server()
    if stop_result[1] == 200:
        time.sleep(1)
        return start_server()
    return stop_result

@app.route('/api/server/status', methods=['GET'])
@login_required
def get_server_status():
    """সার্ভার স্ট্যাটাস API"""
    username = session['username']
    
    status = server_status.get(username, {'running': False})
    
    # CPU এবং RAM লোড সিমুলেট
    if status.get('running', False):
        cpu_load = random.randint(10, 40)
        ram_load = random.randint(20, 60)
    else:
        cpu_load = 0
        ram_load = 0
    
    return jsonify({
        'running': status.get('running', False),
        'pid': status.get('pid'),
        'started_at': status.get('started_at'),
        'main_file': status.get('main_file'),
        'cpu_load': cpu_load,
        'ram_load': ram_load
    })

@app.route('/api/server/logs', methods=['GET'])
@login_required
def get_server_logs():
    """সার্ভার লগ API (সিমুলেটেড)"""
    username = session['username']
    
    logs = [
        {'time': datetime.now().strftime('%H:%M:%S'), 'message': 'API রিকোয়েস্ট প্রসেস করা হয়েছে', 'type': 'info'},
        {'time': datetime.now().strftime('%H:%M:%S'), 'message': 'ডাটাবেস কোয়েরি এক্সিকিউট', 'type': 'success'},
        {'time': datetime.now().strftime('%H:%M:%S'), 'message': 'ক্যাশে আপডেট সম্পূর্ণ', 'type': 'info'},
    ]
    
    return jsonify({'success': True, 'logs': logs})

# হেল্পার রিডাইরেক্ট
from flask import redirect

if __name__ == '__main__':
    load_users()
    print("""
    ╔════════════════════════════════════════╗
    ║   ইফতেখার হোস্টিং বোর্ড - ব্যাকএন্ড   ║
    ║                                        ║
    ║   🚀 সার্ভার রানিং অন পোর্ট: 5000      ║
    ║   🌐 http://localhost:5000            ║
    ║                                        ║
    ║   ডিফল্ট ইউজার: iftekhar             ║
    ║   পাসওয়ার্ড: iftekhar123             ║
    ╚════════════════════════════════════════╝
    """)
    app.run(debug=True, host='0.0.0.0', port=5000)
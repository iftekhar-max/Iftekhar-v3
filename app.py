from flask import Flask, render_template, request, redirect, url_for, session, jsonify
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
import signal
import re

app = Flask(__name__)
app.secret_key = 'iftekhar-hosting-secret-key-2024'
socketio = SocketIO(app, cors_allowed_origins="*")

# কনফিগারেশন
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'user_uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ইউজার ডাটা
USERS_FILE = os.path.join(BASE_DIR, 'users.json')

def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f)

# রানিং প্রসেস ট্র্যাকিং
running_processes = {}
installing_modules = {}

# কমন পাইথন মডিউলের লিস্ট
COMMON_MODULES = {
    'web': ['requests', 'flask', 'django', 'fastapi', 'aiohttp', 'httpx'],
    'data': ['numpy', 'pandas', 'matplotlib', 'scipy', 'scikit-learn'],
    'database': ['psycopg2', 'pymongo', 'redis', 'sqlalchemy', 'pymysql'],
    'security': ['jwt', 'cryptography', 'bcrypt', 'passlib'],
    'other': ['pillow', 'openpyxl', 'beautifulsoup4', 'selenium', 'pytelegrambotapi']
}

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
            'projects': [],
            'installed_modules': []
        }
        save_users(users)
        
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
            if item == '.keep':
                continue
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
    
    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else user_folder, exist_ok=True)
    
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

# মডিউল ইনস্টল করার API
@app.route('/api/install-module', methods=['POST'])
def install_module():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    module_name = data.get('module_name')
    username = session['username']
    
    if not module_name:
        return jsonify({'error': 'Module name required'}), 400
    
    # মডিউল নাম ভ্যালিডেশন
    if not re.match(r'^[a-zA-Z0-9\-_.]+$', module_name):
        return jsonify({'error': 'Invalid module name format'}), 400
    
    if username in installing_modules and installing_modules[username]:
        return jsonify({'error': 'Already installing a module. Please wait.'}), 429
    
    def install():
        try:
            installing_modules[username] = True
            
            # পিপ ইনস্টল
            process = subprocess.Popen(
                [sys.executable, '-m', 'pip', 'install', module_name, '--no-cache-dir'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            output, error = process.communicate(timeout=120)
            
            result = {
                'success': process.returncode == 0,
                'module': module_name,
                'output': output,
                'error': error,
                'return_code': process.returncode
            }
            
            if result['success']:
                # ইউজারের ইনস্টলড মডিউল লিস্ট আপডেট
                users = load_users()
                if username in users:
                    if 'installed_modules' not in users[username]:
                        users[username]['installed_modules'] = []
                    if module_name not in users[username]['installed_modules']:
                        users[username]['installed_modules'].append(module_name)
                    save_users(users)
            
            socketio.emit('install_result', {
                'user': username,
                'result': result
            })
            
        except subprocess.TimeoutExpired:
            process.kill()
            socketio.emit('install_result', {
                'user': username,
                'result': {
                    'success': False,
                    'module': module_name,
                    'error': 'Installation timeout (120s)',
                    'return_code': -1
                }
            })
        except Exception as e:
            socketio.emit('install_result', {
                'user': username,
                'result': {
                    'success': False,
                    'module': module_name,
                    'error': str(e),
                    'return_code': -1
                }
            })
        finally:
            installing_modules[username] = False
    
    thread = threading.Thread(target=install)
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'message': f'Installing {module_name}...'})

# মডিউল আনইনস্টল করার API
@app.route('/api/uninstall-module', methods=['POST'])
def uninstall_module():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    module_name = data.get('module_name')
    username = session['username']
    
    if not module_name:
        return jsonify({'error': 'Module name required'}), 400
    
    try:
        process = subprocess.run(
            [sys.executable, '-m', 'pip', 'uninstall', module_name, '-y'],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if process.returncode == 0:
            # ইউজারের লিস্ট থেকে রিমুভ
            users = load_users()
            if username in users and 'installed_modules' in users[username]:
                if module_name in users[username]['installed_modules']:
                    users[username]['installed_modules'].remove(module_name)
                save_users(users)
            
            return jsonify({'success': True, 'message': f'{module_name} uninstalled successfully'})
        else:
            return jsonify({'success': False, 'error': process.stderr})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ইনস্টল করা মডিউলের লিস্ট দেখার API
@app.route('/api/installed-modules', methods=['GET'])
def get_installed_modules():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'list'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        modules = []
        lines = result.stdout.split('\n')
        for line in lines[2:]:
            if line.strip():
                parts = line.split()
                if len(parts) >= 2:
                    modules.append({
                        'name': parts[0],
                        'version': parts[1]
                    })
        
        return jsonify({'modules': modules})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# সার্চ মডিউল API
@app.route('/api/search-modules', methods=['POST'])
def search_modules():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    query = data.get('query', '').lower()
    
    results = []
    for category, modules in COMMON_MODULES.items():
        for module in modules:
            if query in module.lower():
                results.append({
                    'name': module,
                    'category': category
                })
    
    return jsonify({'results': results})

@app.route('/api/run', methods=['POST'])
def run_code():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    filename = data.get('filename')
    username = session['username']
    
    user_folder = os.path.join(UPLOAD_FOLDER, username)
    filepath = os.path.join(user_folder, filename)
    
    if not os.path.exists(filepath):
        return jsonify({'error': f'File not found: {filename}'}), 404
    
    if username in running_processes:
        try:
            if running_processes[username].poll() is None:
                running_processes[username].terminate()
                time.sleep(1)
                if running_processes[username].poll() is None:
                    running_processes[username].kill()
            del running_processes[username]
        except:
            pass
    
    try:
        process_id = str(uuid.uuid4())[:8]
        
        def run_script():
            try:
                # PYTHONPATH সেট করা
                env = os.environ.copy()
                env['PYTHONPATH'] = user_folder
                
                process = subprocess.Popen(
                    [sys.executable, filepath],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=user_folder,
                    env=env
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
                    
            except subprocess.TimeoutExpired:
                socketio.emit('run_result', {
                    'user': username,
                    'result': {'error': 'Execution timeout (30s)', 'output': '', 'return_code': -1},
                    'process_id': process_id
                })
                if username in running_processes:
                    del running_processes[username]
            except Exception as e:
                socketio.emit('run_result', {
                    'user': username,
                    'result': {'error': str(e), 'output': '', 'return_code': -1},
                    'process_id': process_id
                })
                if username in running_processes:
                    del running_processes[username]
        
        thread = threading.Thread(target=run_script)
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'process_id': process_id, 'message': 'Code running...'})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stop', methods=['POST'])
def stop_code():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    username = session['username']
    
    if username in running_processes:
        try:
            if running_processes[username].poll() is None:
                running_processes[username].terminate()
                time.sleep(1)
                if running_processes[username].poll() is None:
                    running_processes[username].kill()
            del running_processes[username]
            return jsonify({'success': True, 'message': 'Process stopped'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    return jsonify({'success': False, 'message': 'No process running'})

@app.route('/api/save', methods=['POST'])
def save_file():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    filename = data.get('filename')
    content = data.get('content')
    username = session['username']
    user_folder = os.path.join(UPLOAD_FOLDER, username)
    filepath = os.path.join(user_folder, filename)
    
    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else user_folder, exist_ok=True)
    
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
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            return jsonify({'content': content})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    return jsonify({'error': 'File not found'}), 404

@app.route('/api/system-stats', methods=['GET'])
def system_stats():
    try:
        import psutil
        return jsonify({
            'cpu': psutil.cpu_percent(),
            'memory': psutil.virtual_memory().percent,
            'disk': psutil.disk_usage('/').percent
        })
    except:
        return jsonify({
            'cpu': 0,
            'memory': 0,
            'disk': 0
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
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=True)
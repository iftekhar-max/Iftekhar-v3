from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO, emit
from process_manager import process_manager
import os
import zipfile
import json
import uuid
from werkzeug.utils import secure_filename
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'iftikhar-hosting-secret-key-2024')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

socketio = SocketIO(app, cors_allowed_origins="*")

# ফোল্ডার তৈরি
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('processes', exist_ok=True)
os.makedirs('logs', exist_ok=True)

USERS_FILE = 'users.json'

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

# ডেমো ইউজার
users = load_users()
if 'demo' not in users:
    users['demo'] = {
        'password': 'demo123',
        'user_id': str(uuid.uuid4()),
        'name': 'Demo User',
        'created_at': datetime.now().isoformat()
    }
    save_users(users)

def get_current_user():
    return session.get('user_id')

# ==================== পেজ রাউট ====================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register')
def register_page():
    return render_template('register.html')

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

# ==================== API রাউট ====================

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    users = load_users()
    
    if username in users and users[username]['password'] == password:
        session['user_id'] = users[username]['user_id']
        session['username'] = username
        return jsonify({
            'success': True,
            'user_id': users[username]['user_id'],
            'username': username
        })
    
    return jsonify({'success': False, 'message': 'ইউজারনেম বা পাসওয়ার্ড ভুল'})

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    
    if not username or not email or not password:
        return jsonify({'success': False, 'message': 'সব ফিল্ড পূরণ করুন'})
    
    if len(password) < 6:
        return jsonify({'success': False, 'message': 'পাসওয়ার্ড কমপক্ষে 6 অক্ষরের হতে হবে'})
    
    users = load_users()
    
    if username in users:
        return jsonify({'success': False, 'message': 'এই ইউজারনেম ইতিমধ্যে নেওয়া হয়েছে'})
    
    users[username] = {
        'password': password,
        'email': email,
        'user_id': str(uuid.uuid4()),
        'name': username,
        'created_at': datetime.now().isoformat()
    }
    save_users(users)
    
    return jsonify({'success': True, 'message': 'রেজিস্ট্রেশন সফল! এখন লগইন করুন'})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/upload', methods=['POST'])
def upload_file():
    user_id = get_current_user()
    if not user_id:
        return jsonify({'success': False, 'message': 'প্লিজ লগইন করুন'})
    
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'কোন ফাইল নেই'})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'ফাইল সিলেক্ট করুন'})
    
    if not file.filename.endswith('.zip'):
        return jsonify({'success': False, 'message': 'শুধুমাত্র ZIP ফাইল সাপোর্ট করে'})
    
    try:
        user_folder = os.path.join(app.config['UPLOAD_FOLDER'], user_id)
        os.makedirs(user_folder, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = secure_filename(f"{timestamp}_{file.filename}")
        file_path = os.path.join(user_folder, filename)
        file.save(file_path)
        
        extract_folder = os.path.join(user_folder, filename.replace('.zip', ''))
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            zip_ref.extractall(extract_folder)
        
        python_files = []
        all_files = []
        
        for root, dirs, files in os.walk(extract_folder):
            for f in files:
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, extract_folder)
                file_info = {
                    'name': f,
                    'path': rel_path,
                    'full_path': full_path,
                    'is_python': f.endswith('.py')
                }
                all_files.append(file_info)
                if f.endswith('.py'):
                    python_files.append(file_info)
        
        socketio.emit('file_uploaded', {
            'user_id': user_id,
            'filename': filename,
            'python_files': python_files,
            'total_files': len(all_files)
        }, namespace='/')
        
        return jsonify({
            'success': True,
            'message': f'ফাইল আপলোড সফল! {len(python_files)} টি পাইথন ফাইল পাওয়া গেছে',
            'extract_path': extract_folder,
            'python_files': python_files,
            'all_files': all_files
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'এরর: {str(e)}'})

@app.route('/api/start-script', methods=['POST'])
def start_script():
    user_id = get_current_user()
    if not user_id:
        return jsonify({'success': False, 'message': 'প্লিজ লগইন করুন'})
    
    data = request.json
    script_path = data.get('script_path')
    script_name = data.get('script_name', 'script.py')
    
    if not script_path or not os.path.exists(script_path):
        return jsonify({'success': False, 'message': 'স্ক্রিপ্ট ফাইল পাওয়া যায়নি'})
    
    if not script_path.endswith('.py'):
        return jsonify({'success': False, 'message': 'শুধুমাত্র পাইথন (.py) ফাইল রান করা যায়'})
    
    process_data = process_manager.start_script(script_path, user_id, script_name)
    
    if process_data:
        socketio.emit('script_started', {
            'user_id': user_id,
            'process_id': process_data['process_id'],
            'script_name': script_name,
            'pid': process_data['pid']
        }, namespace='/')
        
        return jsonify({
            'success': True,
            'message': f'"{script_name}" সফলভাবে স্টার্ট হয়েছে (PID: {process_data["pid"]})',
            'process': {
                'process_id': process_data['process_id'],
                'pid': process_data['pid'],
                'script_name': process_data['script_name'],
                'status': process_data['status'],
                'start_time': process_data['start_time'].isoformat() if hasattr(process_data['start_time'], 'isoformat') else str(process_data['start_time'])
            }
        })
    
    return jsonify({'success': False, 'message': 'স্ক্রিপ্ট স্টার্ট করতে ব্যর্থ'})

@app.route('/api/stop-script', methods=['POST'])
def stop_script():
    user_id = get_current_user()
    if not user_id:
        return jsonify({'success': False, 'message': 'প্লিজ লগইন করুন'})
    
    data = request.json
    process_id = data.get('process_id')
    
    if process_manager.stop_process(process_id):
        socketio.emit('script_stopped', {
            'user_id': user_id,
            'process_id': process_id
        }, namespace='/')
        return jsonify({'success': True, 'message': 'স্ক্রিপ্ট বন্ধ করা হয়েছে'})
    
    return jsonify({'success': False, 'message': 'স্ক্রিপ্ট বন্ধ করতে ব্যর্থ'})

@app.route('/api/restart-script', methods=['POST'])
def restart_script():
    user_id = get_current_user()
    if not user_id:
        return jsonify({'success': False, 'message': 'প্লিজ লগইন করুন'})
    
    data = request.json
    process_id = data.get('process_id')
    
    new_process = process_manager.restart_process(process_id)
    
    if new_process:
        socketio.emit('script_restarted', {
            'user_id': user_id,
            'old_id': process_id,
            'new_id': new_process['process_id']
        }, namespace='/')
        return jsonify({
            'success': True,
            'message': 'স্ক্রিপ্ট রিস্টার্ট হয়েছে',
            'process': {
                'process_id': new_process['process_id'],
                'pid': new_process['pid'],
                'script_name': new_process['script_name'],
                'status': new_process['status']
            }
        })
    
    return jsonify({'success': False, 'message': 'রিস্টার্ট ব্যর্থ'})

@app.route('/api/my-scripts', methods=['GET'])
def get_my_scripts():
    user_id = get_current_user()
    if not user_id:
        return jsonify({'success': False, 'message': 'প্লিজ লগইন করুন'})
    
    processes = process_manager.get_user_processes(user_id)
    
    formatted_processes = []
    for proc in processes:
        formatted_processes.append({
            'process_id': proc['process_id'],
            'pid': proc.get('pid', 'N/A'),
            'script_name': proc['script_name'],
            'script_path': proc['script_path'],
            'status': proc['status'],
            'start_time': proc['start_time'].isoformat() if hasattr(proc['start_time'], 'isoformat') else str(proc['start_time'])
        })
    
    return jsonify({'success': True, 'processes': formatted_processes})

@app.route('/api/script-log/<process_id>', methods=['GET'])
def get_script_log(process_id):
    user_id = get_current_user()
    if not user_id:
        return jsonify({'success': False, 'message': 'প্লিজ লগইন করুন'})
    
    lines = request.args.get('lines', 100, type=int)
    log = process_manager.get_process_log(process_id, lines)
    status = process_manager.get_process_status(process_id)
    
    return jsonify({
        'success': True,
        'log': log,
        'status': status,
        'process_id': process_id
    })

@app.route('/api/get-uploaded-files', methods=['GET'])
def get_uploaded_files():
    user_id = get_current_user()
    if not user_id:
        return jsonify({'success': False, 'message': 'প্লিজ লগইন করুন'})
    
    user_folder = os.path.join(app.config['UPLOAD_FOLDER'], user_id)
    python_files = []
    
    if os.path.exists(user_folder):
        for root, dirs, files in os.walk(user_folder):
            for f in files:
                if f.endswith('.py'):
                    full_path = os.path.join(root, f)
                    rel_path = os.path.relpath(full_path, user_folder)
                    python_files.append({
                        'name': f,
                        'path': rel_path,
                        'full_path': full_path
                    })
    
    return jsonify({'success': True, 'files': python_files})

# ==================== সকেট ইভেন্ট ====================

@socketio.on('connect')
def handle_connect():
    print(f'✅ Client connected: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    print(f'❌ Client disconnected: {request.sid}')

# ==================== মেইন ====================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
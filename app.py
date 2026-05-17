from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO
import os
import zipfile
import json
import uuid
import shutil
from datetime import datetime
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'iftikhar-hosting-secret-key'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

socketio = SocketIO(app, cors_allowed_origins="*")

# ফোল্ডার তৈরি
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

USERS_FILE = 'users.json'

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    return {'demo': {'password': 'demo123', 'user_id': 'user_001', 'name': 'Demo User'}}

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

users = load_users()

def get_current_user():
    return session.get('user_id')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register')
def register_page():
    return render_template('register.html')

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if username in users and users[username]['password'] == password:
        session['user_id'] = users[username]['user_id']
        session['username'] = username
        return jsonify({'success': True, 'username': username})
    return jsonify({'success': False, 'message': 'ইউজারনেম বা পাসওয়ার্ড ভুল'})

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    
    if len(password) < 6:
        return jsonify({'success': False, 'message': 'পাসওয়ার্ড কমপক্ষে 6 অক্ষরের হতে হবে'})
    
    if username in users:
        return jsonify({'success': False, 'message': 'ইউজারনেম ইতিমধ্যে নেওয়া হয়েছে'})
    
    users[username] = {
        'password': password,
        'email': email,
        'user_id': str(uuid.uuid4()),
        'name': username,
        'created_at': datetime.now().isoformat()
    }
    save_users(users)
    return jsonify({'success': True, 'message': 'রেজিস্ট্রেশন সফল!'})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/upload', methods=['POST'])
def upload_file():
    print("=" * 50)
    print("📤 UPLOAD CALLED")
    
    user_id = get_current_user()
    if not user_id:
        return jsonify({'success': False, 'message': 'লগইন করুন'})
    
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
        print(f"Saved: {file_path}")
        
        extract_folder = os.path.join(user_folder, filename.replace('.zip', ''))
        if os.path.exists(extract_folder):
            shutil.rmtree(extract_folder)
        
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            zip_ref.extractall(extract_folder)
        print(f"Extracted to: {extract_folder}")
        
        # ফাইল ট্রি তৈরি
        file_tree = []
        for item in os.listdir(extract_folder):
            item_path = os.path.join(extract_folder, item)
            if os.path.isdir(item_path):
                file_tree.append({
                    'type': 'folder',
                    'name': item,
                    'full_path': item_path,
                    'children': []
                })
            else:
                file_tree.append({
                    'type': 'file',
                    'name': item,
                    'full_path': item_path,
                    'size': os.path.getsize(item_path),
                    'is_editable': item.endswith(('.py', '.txt', '.html', '.css', '.js'))
                })
        
        print("Upload Success!")
        return jsonify({
            'success': True,
            'message': 'ফাইল আপলোড সফল!',
            'file_tree': file_tree
        })
        
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/get-files', methods=['GET'])
def get_files():
    user_id = get_current_user()
    if not user_id:
        return jsonify({'success': False, 'message': 'লগইন করুন'})
    
    user_folder = os.path.join(app.config['UPLOAD_FOLDER'], user_id)
    file_tree = []
    
    if os.path.exists(user_folder):
        folders = [f for f in os.listdir(user_folder) if os.path.isdir(os.path.join(user_folder, f))]
        if folders:
            latest = max(folders, key=lambda f: os.path.getmtime(os.path.join(user_folder, f)))
            extract_path = os.path.join(user_folder, latest)
            for item in os.listdir(extract_path):
                item_path = os.path.join(extract_path, item)
                if os.path.isdir(item_path):
                    file_tree.append({'type': 'folder', 'name': item, 'full_path': item_path, 'children': []})
                else:
                    file_tree.append({
                        'type': 'file', 'name': item, 'full_path': item_path,
                        'size': os.path.getsize(item_path),
                        'is_editable': item.endswith(('.py', '.txt', '.html', '.css', '.js'))
                    })
    
    return jsonify({'success': True, 'file_tree': file_tree})

@app.route('/api/get-file-content', methods=['GET'])
def get_file_content():
    file_path = request.args.get('path')
    if not file_path or not os.path.exists(file_path):
        return jsonify({'success': False, 'message': 'ফাইল নেই'})
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return jsonify({'success': True, 'content': f.read()})
    except:
        return jsonify({'success': False, 'message': 'ফাইল পড়া যাচ্ছে না'})

@app.route('/api/save-file', methods=['POST'])
def save_file():
    data = request.get_json()
    file_path = data.get('file_path')
    content = data.get('content')
    if not file_path or not os.path.exists(file_path):
        return jsonify({'success': False, 'message': 'ফাইল নেই'})
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return jsonify({'success': True, 'message': 'সেভ হয়েছে'})

@app.route('/api/delete-file', methods=['POST'])
def delete_file():
    data = request.get_json()
    file_path = data.get('file_path')
    if not file_path or not os.path.exists(file_path):
        return jsonify({'success': False, 'message': 'ফাইল নেই'})
    if os.path.isdir(file_path):
        shutil.rmtree(file_path)
    else:
        os.remove(file_path)
    return jsonify({'success': True, 'message': 'ডিলিট হয়েছে'})

@app.route('/api/set-main-file', methods=['POST'])
def set_main_file():
    data = request.get_json()
    file_path = data.get('file_path')
    session['main_file_path'] = file_path
    session['main_file_name'] = os.path.basename(file_path)
    return jsonify({'success': True, 'message': f'মেইন ফাইল সেট করা হয়েছে'})

@app.route('/api/get-main-file', methods=['GET'])
def get_main_file():
    return jsonify({
        'success': True,
        'main_file_path': session.get('main_file_path'),
        'main_file_name': session.get('main_file_name')
    })

@app.route('/api/start-script', methods=['POST'])
def start_script():
    return jsonify({'success': True, 'message': 'স্ক্রিপ্ট স্টার্ট হয়েছে'})

@app.route('/api/stop-script', methods=['POST'])
def stop_script():
    return jsonify({'success': True, 'message': 'স্ক্রিপ্ট স্টপ হয়েছে'})

@app.route('/api/restart-script', methods=['POST'])
def restart_script():
    return jsonify({'success': True, 'message': 'স্ক্রিপ্ট রিস্টার্ট হয়েছে'})

@app.route('/api/my-scripts', methods=['GET'])
def my_scripts():
    return jsonify({'success': True, 'processes': []})

@app.route('/api/script-log/<process_id>', methods=['GET'])
def script_log(process_id):
    return jsonify({'success': True, 'log': 'লগ নেই', 'status': 'stopped'})

if __name__ == '__main__':
    print("""
    ╔════════════════════════════════════════════════╗
    ║   ইফতেখার হোস্টিং - সার্ভার স্টার্ট হয়েছে    ║
    ║   http://localhost:5000                        ║
    ║   demo / demo123                               ║
    ╚════════════════════════════════════════════════╝
    """)
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
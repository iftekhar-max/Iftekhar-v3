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
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB

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
    return {'demo': {'password': 'demo123', 'user_id': 'user_001', 'name': 'Demo User'}}

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

users = load_users()

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
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        if username in users and users[username]['password'] == password:
            session['user_id'] = users[username]['user_id']
            session['username'] = username
            return jsonify({'success': True, 'username': username})
        
        return jsonify({'success': False, 'message': 'ইউজারনেম বা পাসওয়ার্ড ভুল'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        
        if not username or not email or not password:
            return jsonify({'success': False, 'message': 'সব ফিল্ড পূরণ করুন'})
        
        if len(password) < 6:
            return jsonify({'success': False, 'message': 'পাসওয়ার্ড কমপক্ষে 6 অক্ষরের হতে হবে'})
        
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
        
        return jsonify({'success': True, 'message': 'রেজিস্ট্রেশন সফল!'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

# ==================== ফাইল ট্রি তৈরি (ফোল্ডার স্ট্রাকচার সহ) ====================

def build_file_tree(folder_path, base_path):
    """ফোল্ডার স্ট্রাকচার সহ ফাইল ট্রি তৈরি করে"""
    tree = []
    try:
        for item in sorted(os.listdir(folder_path)):
            item_path = os.path.join(folder_path, item)
            rel_path = os.path.relpath(item_path, base_path)
            
            if os.path.isdir(item_path):
                # ফোল্ডার হলে
                children = build_file_tree(item_path, base_path)
                file_count = sum(1 for f in os.listdir(item_path) if os.path.isfile(os.path.join(item_path, f)))
                tree.append({
                    'type': 'folder',
                    'name': item,
                    'path': rel_path,
                    'full_path': item_path,
                    'children': children,
                    'fileCount': len(children)
                })
            else:
                # ফাইল হলে
                content = None
                try:
                    if item.endswith(('.py', '.txt', '.html', '.css', '.js', '.json', '.md')):
                        with open(item_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                except:
                    pass
                
                tree.append({
                    'type': 'file',
                    'name': item,
                    'path': rel_path,
                    'full_path': item_path,
                    'size': os.path.getsize(item_path),
                    'content': content,
                    'is_editable': item.endswith(('.py', '.txt', '.html', '.css', '.js', '.json', '.md'))
                })
    except Exception as e:
        print(f"Error building tree: {e}")
    return tree

# ==================== ফাইল আপলোড API ====================

@app.route('/api/upload', methods=['POST'])
def upload_file():
    print("=" * 50)
    print("📤 আপলোড রিকোয়েস্ট এসেছে")
    
    try:
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
        
        user_folder = os.path.join(app.config['UPLOAD_FOLDER'], user_id)
        os.makedirs(user_folder, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = secure_filename(f"{timestamp}_{file.filename}")
        file_path = os.path.join(user_folder, filename)
        file.save(file_path)
        print(f"💾 ফাইল সেভ: {file_path}")
        
        extract_folder = os.path.join(user_folder, filename.replace('.zip', ''))
        
        if os.path.exists(extract_folder):
            shutil.rmtree(extract_folder)
        
        # ZIP এক্সট্র্যাক্ট - ফোল্ডার স্ট্রাকচার সহ
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            zip_ref.extractall(extract_folder)
        print(f"📦 এক্সট্র্যাক্ট: {extract_folder}")
        
        # ফাইল ট্রি তৈরি
        file_tree = build_file_tree(extract_folder, extract_folder)
        
        # সেশনে এক্সট্র্যাক্ট পাথ সংরক্ষণ
        session['current_extract_path'] = extract_folder
        
        print(f"✅ সফল! {len(file_tree)} টি রুট আইটেম")
        print("=" * 50)
        
        return jsonify({
            'success': True,
            'message': f'ফাইল আপলোড সফল!',
            'file_tree': file_tree
        })
        
    except Exception as e:
        print(f"❌ এরর: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'এরর: {str(e)}'})

# ==================== ফাইল লিস্ট API ====================

@app.route('/api/get-files', methods=['GET'])
def get_files():
    try:
        user_id = get_current_user()
        if not user_id:
            return jsonify({'success': False, 'message': 'প্লিজ লগইন করুন'})
        
        user_folder = os.path.join(app.config['UPLOAD_FOLDER'], user_id)
        file_tree = []
        
        if os.path.exists(user_folder):
            # সবচেয়ে নতুন এক্সট্র্যাক্ট ফোল্ডার খুঁজে বের করা
            folders = [f for f in os.listdir(user_folder) if os.path.isdir(os.path.join(user_folder, f))]
            if folders:
                latest_folder = max(folders, key=lambda f: os.path.getmtime(os.path.join(user_folder, f)))
                extract_path = os.path.join(user_folder, latest_folder)
                file_tree = build_file_tree(extract_path, extract_path)
        
        return jsonify({'success': True, 'file_tree': file_tree})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# ==================== ফাইল কন্টেন্ট API ====================

@app.route('/api/get-file-content', methods=['GET'])
def get_file_content():
    try:
        user_id = get_current_user()
        if not user_id:
            return jsonify({'success': False, 'message': 'প্লিজ লগইন করুন'})
        
        file_path = request.args.get('path')
        if not file_path or not os.path.exists(file_path):
            return jsonify({'success': False, 'message': 'ফাইল পাওয়া যায়নি'})
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return jsonify({'success': True, 'content': content})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# ==================== ফাইল সেভ API ====================

@app.route('/api/save-file', methods=['POST'])
def save_file():
    try:
        user_id = get_current_user()
        if not user_id:
            return jsonify({'success': False, 'message': 'প্লিজ লগইন করুন'})
        
        data = request.get_json()
        file_path = data.get('file_path')
        content = data.get('content')
        
        if not file_path or not os.path.exists(file_path):
            return jsonify({'success': False, 'message': 'ফাইল পাওয়া যায়নি'})
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return jsonify({'success': True, 'message': 'ফাইল সেভ করা হয়েছে'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# ==================== ফাইল ডিলিট API ====================

@app.route('/api/delete-file', methods=['POST'])
def delete_file():
    try:
        user_id = get_current_user()
        if not user_id:
            return jsonify({'success': False, 'message': 'প্লিজ লগইন করুন'})
        
        data = request.get_json()
        file_path = data.get('file_path')
        
        if not file_path or not os.path.exists(file_path):
            return jsonify({'success': False, 'message': 'ফাইল পাওয়া যায়নি'})
        
        if os.path.isdir(file_path):
            shutil.rmtree(file_path)
        else:
            os.remove(file_path)
        
        return jsonify({'success': True, 'message': 'ডিলিট করা হয়েছে'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# ==================== মেইন ফাইল সিলেক্ট API ====================

@app.route('/api/set-main-file', methods=['POST'])
def set_main_file():
    try:
        user_id = get_current_user()
        if not user_id:
            return jsonify({'success': False, 'message': 'প্লিজ লগইন করুন'})
        
        data = request.get_json()
        file_path = data.get('file_path')
        
        if not file_path or not os.path.exists(file_path):
            return jsonify({'success': False, 'message': 'ফাইল পাওয়া যায়নি'})
        
        session['main_file_path'] = file_path
        session['main_file_name'] = os.path.basename(file_path)
        
        return jsonify({
            'success': True,
            'message': f'"{session["main_file_name"]}" কে মেইন ফাইল হিসেবে সিলেক্ট করা হয়েছে',
            'main_file': session['main_file_path']
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/get-main-file', methods=['GET'])
def get_main_file():
    try:
        user_id = get_current_user()
        if not user_id:
            return jsonify({'success': False, 'message': 'প্লিজ লগইন করুন'})
        
        return jsonify({
            'success': True,
            'main_file_path': session.get('main_file_path'),
            'main_file_name': session.get('main_file_name')
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# ==================== স্ক্রিপ্ট রান API (সিম্পল) ====================

@app.route('/api/start-script', methods=['POST'])
def start_script():
    user_id = get_current_user()
    if not user_id:
        return jsonify({'success': False, 'message': 'প্লিজ লগইন করুন'})
    
    data = request.get_json()
    script_path = data.get('script_path')
    script_name = data.get('script_name', 'script.py')
    
    if not script_path or not os.path.exists(script_path):
        return jsonify({'success': False, 'message': 'স্ক্রিপ্ট ফাইল পাওয়া যায়নি'})
    
    # সিম্পল রেসপন্স (প্রয়োজন অনুযায়ী বাড়ানো যাবে)
    return jsonify({'success': True, 'message': f'"{script_name}" স্টার্ট হয়েছে'})

@app.route('/api/stop-script', methods=['POST'])
def stop_script():
    return jsonify({'success': True, 'message': 'স্ক্রিপ্ট বন্ধ করা হয়েছে'})

@app.route('/api/restart-script', methods=['POST'])
def restart_script():
    return jsonify({'success': True, 'message': 'স্ক্রিপ্ট রিস্টার্ট হয়েছে'})

@app.route('/api/my-scripts', methods=['GET'])
def get_my_scripts():
    return jsonify({'success': True, 'processes': []})

@app.route('/api/script-log/<process_id>', methods=['GET'])
def get_script_log(process_id):
    return jsonify({'success': True, 'log': 'লগ পাওয়া যায়নি', 'status': 'stopped'})

# ==================== সকেট ইভেন্ট ====================

@socketio.on('connect')
def handle_connect():
    print(f'✅ Client connected: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    print(f'❌ Client disconnected: {request.sid}')

# ==================== মেইন ====================

if __name__ == '__main__':
    print("""
    ╔══════════════════════════════════════════════════════════════════╗
    ║                                                                  ║
    ║     ██╗███████╗████████╗███████╗██╗  ██╗███████╗ █████╗ ██████╗  ║
    ║     ██║██╔════╝╚══██╔══╝██╔════╝██║  ██║██╔════╝██╔══██╗██╔══██╗ ║
    ║     ██║█████╗     ██║   █████╗  ███████║█████╗  ███████║██████╔╝ ║
    ║     ██║██╔══╝     ██║   ██╔══╝  ██╔══██║██╔══╝  ██╔══██║██╔══██╗ ║
    ║     ██║██║        ██║   ███████╗██║  ██║██║     ██║  ██║██║  ██║ ║
    ║     ╚═╝╚═╝        ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝ ║
    ║                                                                  ║
    ║              ইফতেখার হোস্টিং বোর্ড - ব্যাকএন্ড                 ║
    ║                                                                  ║
    ║     ✅ ফোল্ডার স্ট্রাকচার সংরক্ষিত থাকবে                        ║
    ║     ✅ জিপ ফাইল আপলোড ও এক্সট্র্যাক্ট সাপোর্ট                   ║
    ║     ✅ ফাইল এডিট, ডিলিট, মেইন ফাইল সিলেক্ট                      ║
    ║     📍 http://localhost:5000                                    ║
    ║     👤 ডেমো লগইন: demo / demo123                               ║
    ║                                                                  ║
    ╚══════════════════════════════════════════════════════════════════╝
    """)
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
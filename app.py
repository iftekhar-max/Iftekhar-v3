from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
import subprocess
import tempfile
import os
import json
import hashlib
import secrets
from datetime import datetime, timedelta
import threading
import time

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
CORS(app)

# ইউজার ডাটাবেস (সিম্পল ফাইল বেসড - প্রোডাকশনে PostgreSQL ব্যবহার করো)
USERS_FILE = 'users.json'
DEPLOYMENTS_FILE = 'deployments.json'

def init_files():
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'w') as f:
            json.dump({}, f)
    if not os.path.exists(DEPLOYMENTS_FILE):
        with open(DEPLOYMENTS_FILE, 'w') as f:
            json.dump([], f)

init_files()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def save_user(username, password):
    with open(USERS_FILE, 'r') as f:
        users = json.load(f)
    users[username] = hash_password(password)
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f)

def verify_user(username, password):
    with open(USERS_FILE, 'r') as f:
        users = json.load(f)
    return users.get(username) == hash_password(password)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'success': False, 'msg': 'Username and password required'})
    
    with open(USERS_FILE, 'r') as f:
        users = json.load(f)
    
    if username in users:
        return jsonify({'success': False, 'msg': 'Username already exists'})
    
    save_user(username, password)
    return jsonify({'success': True, 'msg': 'Registration successful'})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    if verify_user(username, password):
        session['user'] = username
        session.permanent = True
        app.permanent_session_lifetime = timedelta(days=7)
        return jsonify({'success': True, 'msg': 'Login successful'})
    
    return jsonify({'success': False, 'msg': 'Invalid credentials'})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('user', None)
    return jsonify({'success': True})

@app.route('/api/check_auth', methods=['GET'])
def check_auth():
    return jsonify({'authenticated': 'user' in session, 'user': session.get('user')})

@app.route('/api/run_python', methods=['POST'])
def run_python():
    if 'user' not in session:
        return jsonify({'success': False, 'msg': 'Unauthorized'})
    
    code = request.json.get('code', '')
    
    # টেম্পোরারি ফাইল তৈরি
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(code)
        temp_file = f.name
    
    try:
        # রিয়েল পাইথন এক্সিকিউশন
        result = subprocess.run(
            ['python3', temp_file],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        output = result.stdout
        if result.stderr:
            output += f"\n[ERROR]: {result.stderr}"
        
        return jsonify({
            'success': True,
            'output': output,
            'return_code': result.returncode
        })
    
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'output': 'Execution timeout (10 seconds)'})
    
    except Exception as e:
        return jsonify({'success': False, 'output': f'Error: {str(e)}'})
    
    finally:
        os.unlink(temp_file)

@app.route('/api/deploy', methods=['POST'])
def deploy():
    if 'user' not in session:
        return jsonify({'success': False, 'msg': 'Unauthorized'})
    
    # ডিপ্লয়মেন্ট সিমুলেশন (আসল Railway API সংযোগের জন্য প্রিপার্ড)
    deployment_id = secrets.token_hex(8)
    
    # প্রকৃত ডিপ্লয়মেন্টের জন্য Railway API key লাগবে
    # এটা শুধু ডেমো রেসপন্স
    with open(DEPLOYMENTS_FILE, 'r') as f:
        deployments = json.load(f)
    
    deployments.append({
        'id': deployment_id,
        'user': session['user'],
        'timestamp': datetime.now().isoformat(),
        'status': 'deployed'
    })
    
    with open(DEPLOYMENTS_FILE, 'w') as f:
        json.dump(deployments, f)
    
    return jsonify({
        'success': True,
        'msg': f'Deployment #{len(deployments)} initiated',
        'url': f'https://{deployment_id}.railway.app',
        'deployment_id': deployment_id
    })

@app.route('/api/deployments', methods=['GET'])
def get_deployments():
    if 'user' not in session:
        return jsonify([])
    
    with open(DEPLOYMENTS_FILE, 'r') as f:
        deployments = json.load(f)
    
    user_deployments = [d for d in deployments if d['user'] == session['user']]
    return jsonify(user_deployments)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
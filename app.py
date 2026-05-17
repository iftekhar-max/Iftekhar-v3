import os
import zipfile
import shutil
import psutil
import time
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit

app = Flask(__name__, template_folder='.') # html ফাইল একই ফোল্ডারে রাখার জন্য
app.config['SECRET_KEY'] = 'iftekhar_secret_123'
socketio = SocketIO(app, cors_allowed_origins="*")

# যে ফোল্ডারে ফাইল এক্সট্র্যাক্ট হবে
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'user_files')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

SERVER_STATUS = {"running": True}

@app.route('/')
def index():
    return render_template('dashboard.html')

# ZIP আপলোড ও এক্সট্র্যাক্ট API
@app.route('/api/upload', methods=['POST'])
def upload_zip():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    if file and file.filename.endswith('.zip'):
        zip_path = os.path.join(UPLOAD_FOLDER, file.filename)
        file.save(zip_path)
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(UPLOAD_FOLDER)
            os.remove(zip_path)
            send_log(f"ZIP ফাইল '{file.filename}' সফলভাবে এক্সট্র্যাক্ট করা হয়েছে।", "success")
            return jsonify({"success": True})
        except Exception as e:
            send_log(f"ZIP এক্সট্র্যাক্ট ব্যর্থ: {str(e)}", "error")
            return jsonify({"error": str(e)}), 500
            
    return jsonify({"error": "Only ZIP files allowed"}), 400

# ফাইল সেভ ও ডিলিট API
@app.route('/api/files', methods=['POST', 'DELETE'])
def file_manager_api():
    if request.method == 'DELETE':
        file_path = request.args.get('path')
        full_path = os.path.join(UPLOAD_FOLDER, file_path)
        if os.path.exists(full_path):
            os.remove(full_path)
            send_log(f"'{file_path}' ফাইলটি ডিলিট করা হয়েছে।", "error")
            return jsonify({"success": True})
        return jsonify({"error": "File not found"}), 404

    if request.method == 'POST':
        data = request.json
        file_path = data.get('path')
        content = data.get('content')
        full_path = os.path.join(UPLOAD_FOLDER, file_path)
        
        try:
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
            send_log(f"'{file_path}' ফাইলের কন্টেন্ট সেভ করা হয়েছে।", "success")
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

# সকেট কন্ট্রোল
@socketio.on('connect')
def handle_connect():
    emit_status()

@socketio.on('server_control')
def handle_control(data):
    action = data.get('action')
    if action == 'start':
        SERVER_STATUS["running"] = True
        send_log("🚀 সার্ভার স্টার্ট করা হয়েছে", "success")
    elif action == 'stop':
        SERVER_STATUS["running"] = False
        send_log("🛑 সার্ভার স্টপ করা হয়েছে", "error")
    elif action == 'restart':
        SERVER_STATUS["running"] = False
        send_log("🔄 সার্ভার রিস্টার্ট শুরু...", "warning")
        time.sleep(1.5)
        SERVER_STATUS["running"] = True
        send_log("✅ রিস্টার্ট সম্পূর্ণ ও সার্ভার অনলাইন!", "success")
    emit_status()

def emit_status():
    cpu = psutil.cpu_percent() if SERVER_STATUS["running"] else 0
    ram = psutil.virtual_memory().percent if SERVER_STATUS["running"] else 0
    status_text = "সার্ভার অনলাইন" if SERVER_STATUS["running"] else "সার্ভার অফলাইন"
    
    socketio.emit('status_update', {
        "running": SERVER_STATUS["running"],
        "status_text": status_text,
        "cpu": cpu,
        "ram": ram
    })

def send_log(message, log_type="info"):
    socketio.emit('new_log', {"message": message, "type": log_type})

def background_monitor():
    while True:
        if SERVER_STATUS["running"]:
            emit_status()
        socketio.sleep(3)

if __name__ == '__main__':
    socketio.start_background_task(background_monitor)
    socketio.run(app, debug=True, port=5000)

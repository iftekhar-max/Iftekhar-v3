import os
import sqlite3
import zipfile
import subprocess
import signal
import shutil
import psutil
import time
import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory, send_file
from werkzeug.utils import secure_filename
from flask_socketio import SocketIO, emit
import threading

# Global process tracker
running_procs = {}
start_times = {}

# Initialize SocketIO
socketio = SocketIO()

def get_db():
    # Railway persistent storage handling
    storage_path = os.environ.get('RAILWAY_VOLUME_MOUNT_PATH', os.getcwd())
    db_path = os.path.join(storage_path, 'storage', 'nehost.db')
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    # Create storage directories
    storage_path = os.environ.get('RAILWAY_VOLUME_MOUNT_PATH', os.getcwd())
    storage_dir = os.path.join(storage_path, 'storage')
    instances_dir = os.path.join(storage_dir, 'instances')
    uploads_dir = os.path.join(storage_path, 'static', 'uploads')
    
    os.makedirs(storage_dir, exist_ok=True)
    os.makedirs(instances_dir, exist_ok=True)
    os.makedirs(uploads_dir, exist_ok=True)
    
    db = get_db()
    
    # User Table
    db.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        fname TEXT, lname TEXT, username TEXT, email TEXT, password TEXT, 
        pfp TEXT DEFAULT 'default.png',
        role TEXT DEFAULT 'free', 
        status TEXT DEFAULT 'active',
        server_limit INTEGER DEFAULT 1,
        notifications TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Server Table
    db.execute('''CREATE TABLE IF NOT EXISTS servers (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        user_id INTEGER, name TEXT, folder TEXT, 
        status TEXT, startup TEXT, pid INTEGER,
        server_status TEXT DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )''')
    
    # Support Ticket Table
    db.execute('''CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, subject TEXT, message TEXT, 
        status TEXT DEFAULT 'open', 
        admin_reply TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )''')
    
    # Admin Settings Table
    db.execute('''CREATE TABLE IF NOT EXISTS admin_settings (
        id INTEGER PRIMARY KEY, 
        username TEXT, password TEXT,
        popup_title TEXT, popup_msg TEXT, popup_img TEXT, 
        show_popup INTEGER DEFAULT 0
    )''')
    
    # Create default admin if not exists
    admin_exists = db.execute('SELECT * FROM admin_settings WHERE id=1').fetchone()
    if not admin_exists:
        db.execute('INSERT INTO admin_settings (id, username, password) VALUES (1, "neverexits", "1100")')
    
    db.commit()
    db.close()

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'nehost_ultra_pro_max_99_changed_for_production'
    
    # Use Railway volume for persistent storage if available
    base_storage = os.environ.get('RAILWAY_VOLUME_MOUNT_PATH', os.getcwd())
    app.config['BASE_STORAGE'] = os.path.join(base_storage, 'storage/instances')
    app.config['UPLOAD_FOLDER'] = os.path.join(base_storage, 'static/uploads')
    
    os.makedirs(app.config['BASE_STORAGE'], exist_ok=True)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    init_db()
    socketio.init_app(app, cors_allowed_origins="*")

    def get_precise_uptime(start_timestamp):
        if not start_timestamp: 
            return "Offline"
        diff = int(time.time() - start_timestamp)
        months, rem = divmod(diff, 2592000)
        days, rem = divmod(rem, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, _ = divmod(rem, 60)
        
        parts = []
        if months > 0: 
            parts.append(f"{months}mo")
        if days > 0: 
            parts.append(f"{days}d")
        if hours > 0: 
            parts.append(f"{hours}h")
        parts.append(f"{minutes}m")
        return " ".join(parts)
    
    # ==================== ROUTES ====================
    
    @app.route('/')
    def home():
        return render_template('index.html')
    
    @app.route('/logout')
    def logout():
        session.clear()
        return redirect(url_for('home'))
    
    @app.route('/signup', methods=['GET', 'POST'])
    def signup():
        if request.method == 'POST':
            fname = request.form.get('fname')
            lname = request.form.get('lname')
            username = request.form.get('username')
            email = request.form.get('email')
            pwd = request.form.get('password')
            cpwd = request.form.get('confirm_password')
            pfp = request.files.get('pfp')
            
            if pwd != cpwd:
                return jsonify({'status': 'error', 'msg': 'Passwords do not match!'}), 400
            
            db = get_db()
            existing_user = db.execute('SELECT id FROM users WHERE email=? OR username=?', (email, username)).fetchone()
            if existing_user:
                db.close()
                return jsonify({'status': 'error', 'msg': 'Email or Username already taken!'}), 400
            
            pfp_name = 'default.png'
            if pfp and pfp.filename:
                pfp_name = secure_filename(f"{int(time.time())}_{pfp.filename}")
                pfp.save(os.path.join(app.config['UPLOAD_FOLDER'], pfp_name))
            
            db.execute('''INSERT INTO users 
                (fname, lname, username, email, password, pfp, server_limit, role, status) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (fname, lname, username, email, pwd, pfp_name, 1, 'free', 'active'))
            
            db.commit()
            db.close()
            return jsonify({'status': 'success', 'url': url_for('login')})
        
        return render_template('web/signup.html')
    
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            email = request.form.get('email')
            pwd = request.form.get('password')
            db = get_db()
            user = db.execute('SELECT * FROM users WHERE (email=? OR username=?) AND password=?', (email, email, pwd)).fetchone()
            db.close()
            
            if user:
                if user['status'] == 'banned':
                    return jsonify({'status': 'banned', 'msg': 'Your account has been suspended!'}), 403
                session['user_id'] = user['id']
                session['username'] = user['username']
                return jsonify({'status': 'success', 'url': url_for('dashboard')}), 200
            else:
                return jsonify({'status': 'error', 'msg': 'Invalid credentials!'}), 401
        return render_template('web/login.html')
    
    @app.route('/dashboard')
    def dashboard():
        if 'user_id' not in session:
            return redirect(url_for('login'))
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
        db.close()
        if not user or user['status'] != 'active':
            session.clear()
            return redirect(url_for('login'))
        return render_template('web/dashboard.html', user=user)
    
    @app.route('/profile/update', methods=['POST'])
    def update_profile():
        if 'user_id' not in session:
            return jsonify({'status': 'error', 'msg': 'Not logged in'})
        uid = session['user_id']
        fname = request.form.get('fname')
        lname = request.form.get('lname')
        pwd = request.form.get('password')
        db = get_db()
        if pwd:
            db.execute('UPDATE users SET fname=?, lname=?, password=? WHERE id=?', (fname, lname, pwd, uid))
        else:
            db.execute('UPDATE users SET fname=?, lname=? WHERE id=?', (fname, lname, uid))
        db.commit()
        db.close()
        return jsonify({'status': 'success'})
    
    @app.route('/ticket/create', methods=['POST'])
    def create_ticket():
        if 'user_id' not in session:
            return jsonify({'status': 'error', 'msg': 'Not logged in'})
        data = request.json
        db = get_db()
        db.execute('INSERT INTO tickets (user_id, subject, message) VALUES (?,?,?)', 
                   (session['user_id'], data.get('subject'), data.get('message')))
        db.commit()
        db.close()
        return jsonify({'status': 'success'})
    
    @app.route('/api/announcement')
    def get_announcement():
        db = get_db()
        conf = db.execute('SELECT popup_title, popup_msg, popup_img, show_popup FROM admin_settings WHERE id=1').fetchone()
        db.close()
        return jsonify(dict(conf) if conf else {'show_popup': 0})
    
    # ==================== ADMIN ROUTES ====================
    
    @app.route('/admin-login', methods=['GET', 'POST'])
    def admin_login():
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            db = get_db()
            admin = db.execute('SELECT * FROM admin_settings WHERE username=? AND password=?', (username, password)).fetchone()
            db.close()
            if admin:
                session['admin_logged'] = True
                return redirect(url_for('admin_panel'))
            return render_template('web/admin_login.html', error=True)
        return render_template('web/admin_login.html')
    
    @app.route('/admin/panel')
    def admin_panel():
        if not session.get('admin_logged'):
            return redirect(url_for('admin_login'))
        return render_template('web/admin_panel.html')
    
    @app.route('/admin/stats')
    def admin_stats():
        if not session.get('admin_logged'):
            return jsonify({})
        db = get_db()
        users = db.execute('SELECT * FROM users').fetchall()
        user_list = []
        total_cpu = psutil.cpu_percent(interval=0.5)
        total_ram = psutil.virtual_memory().percent
        
        for u in users:
            srvs = db.execute('SELECT * FROM servers WHERE user_id=?', (u['id'],)).fetchall()
            active_srvs = 0
            for s in srvs:
                is_on = False
                if s['pid'] and psutil.pid_exists(s['pid']):
                    try:
                        proc = psutil.Process(s['pid'])
                        if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                            is_on = True
                    except:
                        pass
                elif s['folder'] in running_procs and running_procs[s['folder']].poll() is None:
                    is_on = True
                if is_on:
                    active_srvs += 1
            user_list.append({
                'id': u['id'], 'fname': u['fname'], 'email': u['email'], 
                'srv_count': len(srvs), 'active_srvs': active_srvs,
                'status': u['status'], 'role': u['role'], 'server_limit': u['server_limit']
            })
        db.close()
        return jsonify({'users': user_list, 'sys_cpu': f"{total_cpu}%", 'sys_ram': f"{total_ram}%"})
    
    @app.route('/admin/user/update', methods=['POST'])
    def update_user():
        if not session.get('admin_logged'):
            return jsonify({'status': 'error'})
        data = request.json
        db = get_db()
        db.execute('UPDATE users SET role=?, status=?, server_limit=? WHERE id=?', 
                   (data['role'], data['status'], data['limit'], data['user_id']))
        db.commit()
        db.close()
        return jsonify({'status': 'success'})
    
    @app.route('/admin/set-popup', methods=['POST'])
    def set_popup():
        if not session.get('admin_logged'):
            return jsonify({'status': 'error'})
        title = request.form.get('title')
        msg = request.form.get('msg')
        show = request.form.get('show')
        img = request.files.get('image')
        db = get_db()
        old_data = db.execute('SELECT popup_img FROM admin_settings WHERE id=1').fetchone()
        img_name = old_data['popup_img'] if old_data else None
        if img and img.filename:
            img_name = secure_filename(f"popup_{int(time.time())}_{img.filename}")
            img.save(os.path.join(app.config['UPLOAD_FOLDER'], img_name))
        db.execute('UPDATE admin_settings SET popup_title=?, popup_msg=?, popup_img=?, show_popup=? WHERE id=1', 
                   (title, msg, img_name, 1 if show == 'true' else 0))
        db.commit()
        db.close()
        return jsonify({'status': 'success'})
    
    @app.route('/admin/send-warning', methods=['POST'])
    def send_warning():
        if not session.get('admin_logged'):
            return jsonify({'status': 'error'})
        data = request.json
        db = get_db()
        db.execute('UPDATE users SET notifications=? WHERE id=?', (data['message'], data['user_id']))
        db.commit()
        db.close()
        return jsonify({'status': 'success'})
    
    @app.route('/admin/login-as/<int:uid>')
    def login_as(uid):
        if not session.get('admin_logged'):
            return redirect(url_for('admin_login'))
        session['user_id'] = uid
        return redirect(url_for('dashboard'))
    
    @app.route('/admin/manage-user/<int:uid>')
    def admin_manage_user_servers(uid):
        if not session.get('admin_logged'):
            return redirect(url_for('admin_login'))
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
        rows = db.execute('SELECT * FROM servers WHERE user_id=?', (uid,)).fetchall()
        db.close()
        servers = []
        for r in rows:
            f = r['folder']
            online = (f in running_procs and running_procs[f].poll() is None) or (r['pid'] and psutil.pid_exists(r['pid']))
            servers.append({'id': r['id'], 'name': r['name'], 'folder': f, 'online': online, 'status': r['server_status']})
        return render_template('web/admin_manage_user.html', user=user, servers=servers)
    
    @app.route('/admin/suspend-server/<int:sid>', methods=['POST'])
    def admin_suspend_server(sid):
        if not session.get('admin_logged'):
            return jsonify({'status': 'error'})
        status = request.json.get('status')
        db = get_db()
        db.execute('UPDATE servers SET server_status=? WHERE id=?', (status, sid))
        db.commit()
        db.close()
        return jsonify({'status': 'success'})
    
    @app.route('/admin/delete-server/<int:sid>', methods=['POST'])
    def admin_delete_server(sid):
        if not session.get('admin_logged'):
            return jsonify({'status': 'error'})
        db = get_db()
        srv = db.execute('SELECT folder FROM servers WHERE id=?', (sid,)).fetchone()
        if srv:
            folder = srv['folder']
            if folder in running_procs:
                try:
                    os.killpg(os.getpgid(running_procs[folder].pid), signal.SIGKILL)
                except:
                    pass
                del running_procs[folder]
            db.execute('DELETE FROM servers WHERE id=?', (sid,))
            db.commit()
            path = os.path.join(app.config['BASE_STORAGE'], folder)
            if os.path.exists(path):
                shutil.rmtree(path)
            db.close()
            return jsonify({'status': 'deleted'})
        db.close()
        return jsonify({'status': 'error', 'msg': 'Server not found'})
    
    @app.route('/admin/create-user', methods=['POST'])
    def admin_create_user():
        if not session.get('admin_logged'):
            return jsonify({'status': 'error'})
        data = request.json
        db = get_db()
        limit = data.get('limit', 1)
        db.execute('INSERT INTO users (fname, email, password, server_limit, username) VALUES (?,?,?,?,?)', 
                   (data['name'], data['email'], data['pass'], limit, data['email'].split('@')[0]))
        db.commit()
        db.close()
        return jsonify({'status': 'success'})
    
    @app.route('/admin/delete-user/<int:uid>', methods=['POST'])
    def delete_user(uid):
        if not session.get('admin_logged'):
            return jsonify({'status': 'error'})
        db = get_db()
        srvs = db.execute('SELECT folder FROM servers WHERE user_id=?', (uid,)).fetchall()
        for s in srvs:
            path = os.path.join(app.config['BASE_STORAGE'], s['folder'])
            if os.path.exists(path):
                shutil.rmtree(path)
        db.execute('DELETE FROM servers WHERE user_id=?', (uid,))
        db.execute('DELETE FROM users WHERE id=?', (uid,))
        db.commit()
        db.close()
        return jsonify({'status': 'deleted'})
    
    @app.route('/admin/files/<folder>')
    def admin_browse_files(folder):
        if not session.get('admin_logged'):
            return redirect(url_for('admin_login'))
        return render_template('web/dashboard.html', user={'fname': 'Admin'}, is_admin_view=True, admin_folder=folder)
    
    # ==================== FILE MANAGEMENT ROUTES ====================
    
    @app.route('/files/list/<folder>')
    def flist(folder):
        sub_path = request.args.get('path', '')
        full_path = os.path.normpath(os.path.join(app.config['BASE_STORAGE'], folder, sub_path))
        if not full_path.startswith(app.config['BASE_STORAGE']):
            return jsonify([])
        if not os.path.exists(full_path):
            return jsonify([])
        items = []
        for f in sorted(os.listdir(full_path)):
            if f == 'console.log':
                continue
            p = os.path.join(full_path, f)
            items.append({
                'name': f, 
                'is_dir': os.path.isdir(p), 
                'is_zip': f.lower().endswith('.zip'), 
                'rel_path': os.path.join(sub_path, f) if sub_path else f
            })
        return jsonify(items)
    
    @app.route('/files/read/<folder>')
    def fread(folder):
        name = request.args.get('name')
        sub_path = request.args.get('path', '')
        p = os.path.join(app.config['BASE_STORAGE'], folder, sub_path, name)
        try:
            with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                return jsonify({'content': f.read()})
        except Exception as e:
            return jsonify({'content': f'Error reading file: {str(e)}'})
    
    @app.route('/files/save/<folder>', methods=['POST'])
    def fsave(folder):
        data = request.json
        name = data.get('name')
        content = data.get('content')
        sub_path = data.get('path', '')
        p = os.path.join(app.config['BASE_STORAGE'], folder, sub_path, name)
        try:
            with open(p, 'w', encoding='utf-8') as f:
                f.write(content)
            return jsonify({'status': 'saved'})
        except Exception as e:
            return jsonify({'status': 'error', 'msg': str(e)})
    
    @app.route('/files/delete-bulk/<folder>', methods=['POST'])
    def delete_bulk(folder):
        data = request.json
        sub_path = data.get('path', '')
        names = data.get('names', [])
        base = os.path.join(app.config['BASE_STORAGE'], folder, sub_path)
        if not names:
            names = [f for f in os.listdir(base) if f != 'console.log']
        for name in names:
            p = os.path.join(base, name)
            if name == 'console.log':
                continue
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p)
                elif os.path.exists(p):
                    os.remove(p)
            except Exception as e:
                print(f"Error deleting {p}: {e}")
        return jsonify({"status": "ok"})
    
    @app.route('/files/create-file/<folder>', methods=['POST'])
    def create_file(folder):
        data = request.json
        p = os.path.join(app.config['BASE_STORAGE'], folder, data.get('path', ''), secure_filename(data.get('name')))
        with open(p, 'w') as f:
            f.write("")
        return jsonify({'status': 'success'})
    
    @app.route('/files/create-folder/<folder>', methods=['POST'])
    def create_folder(folder):
        data = request.json
        p = os.path.join(app.config['BASE_STORAGE'], folder, data.get('path', ''), secure_filename(data.get('name')))
        os.makedirs(p, exist_ok=True)
        return jsonify({'status': 'success'})
    
    @app.route('/files/upload/<folder>', methods=['POST'])
    def upload_file(folder):
        sub_path = request.form.get('path', '')
        file = request.files['file']
        dest = os.path.join(app.config['BASE_STORAGE'], folder, sub_path)
        os.makedirs(dest, exist_ok=True)
        file.save(os.path.join(dest, secure_filename(file.filename)))
        return jsonify({'status': 'success'})
    
    @app.route('/files/rename/<folder>', methods=['POST'])
    def rename_file(folder):
        data = request.json
        base = os.path.join(app.config['BASE_STORAGE'], folder, data.get('path', ''))
        old_path = os.path.join(base, data['old'])
        new_path = os.path.join(base, data['new'])
        os.rename(old_path, new_path)
        return jsonify({'status': 'success'})
    
    @app.route('/files/download/<folder>/<name>')
    def download_file(folder, name):
        sub_path = request.args.get('path', '')
        p = os.path.normpath(os.path.join(app.config['BASE_STORAGE'], folder, sub_path, name))
        if not p.startswith(app.config['BASE_STORAGE']):
            return "Access Denied", 403
        return send_file(p, as_attachment=True)
    
    @app.route('/files/zip-bulk/<folder>', methods=['POST'])
    def zip_bulk(folder):
        data = request.json
        names = data.get('names', [])
        sub_path = data.get('path', '')
        base = os.path.join(app.config['BASE_STORAGE'], folder, sub_path)
        if not names:
            names = [f for f in os.listdir(base) if f != 'console.log']
        zip_name = f"archive_{int(time.time())}.zip"
        zip_path = os.path.join(base, zip_name)
        with zipfile.ZipFile(zip_path, 'w') as z:
            for n in names:
                p = os.path.join(base, n)
                if n == zip_name:
                    continue
                if os.path.isdir(p):
                    for root, dirs, files in os.walk(p):
                        for file in files:
                            full_p = os.path.join(root, file)
                            z.write(full_p, os.path.relpath(full_p, base))
                elif os.path.exists(p):
                    z.write(p, n)
        return jsonify({'status': 'success', 'zip': zip_name})
    
    @app.route('/files/unzip/<folder>', methods=['POST'])
    def unzip_file(folder):
        data = request.json
        zip_name = data.get('name')
        sub_path = data.get('path', '')
        base = os.path.join(app.config['BASE_STORAGE'], folder, sub_path)
        zip_path = os.path.join(base, zip_name)
        
        if os.path.exists(zip_path) and zipfile.is_zipfile(zip_path):
            try:
                with zipfile.ZipFile(zip_path, 'r') as z:
                    z.extractall(base)
                return jsonify({'status': 'success'})
            except Exception as e:
                return jsonify({'status': 'error', 'msg': str(e)})
        return jsonify({'status': 'error', 'msg': 'Invalid zip file'})
    
    # ==================== SERVER MANAGEMENT ROUTES ====================
    
    @app.route('/server/action/<folder>/<act>', methods=['POST'])
    def server_action(folder, act):
        db = get_db()
        srv_data = db.execute('SELECT server_status, pid, startup FROM servers WHERE folder=?', (folder,)).fetchone()
        
        if srv_data and srv_data['server_status'] == 'suspended':
            db.close()
            return jsonify({'status': 'error', 'msg': 'This server is suspended by Admin.'})
        
        path = os.path.join(app.config['BASE_STORAGE'], folder)
        log_file_path = os.path.join(path, 'console.log')
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        if act == 'install':
            req_path = os.path.join(path, 'requirements.txt')
            if os.path.exists(req_path):
                with open(log_file_path, 'a') as f_log:
                    f_log.write(f"\n[{now}] 📦 Package Installation Started...\n")
                subprocess.Popen(['pip', 'install', '-r', 'requirements.txt'], 
                               cwd=path, stdout=open(log_file_path, 'a'), stderr=open(log_file_path, 'a'))
                db.close()
                return jsonify({'status': 'installing'})
            db.close()
            return jsonify({'status': 'error', 'msg': 'requirements.txt missing'})
        
        if act in ['start', 'restart']:
            # Kill existing process if any
            if folder in running_procs:
                try:
                    os.killpg(os.getpgid(running_procs[folder].pid), signal.SIGKILL)
                except:
                    pass
                del running_procs[folder]
            elif srv_data and srv_data['pid'] and psutil.pid_exists(srv_data['pid']):
                try:
                    os.killpg(os.getpgid(srv_data['pid']), signal.SIGKILL)
                except:
                    pass
            
            startup_file = srv_data['startup'] if srv_data and srv_data['startup'] else 'main.py'
            
            with open(log_file_path, 'a') as f_log:
                f_log.write(f"\n[{now}] 🚀 Instance {act.upper()}ED Successfully\n")
            
            proc = subprocess.Popen(['python3', startup_file], cwd=path, 
                                   stdout=open(log_file_path, 'a'), 
                                   stderr=open(log_file_path, 'a'),
                                   preexec_fn=os.setsid if hasattr(os, 'setsid') else None)
            
            running_procs[folder] = proc
            start_times[folder] = time.time()
            db.execute('UPDATE servers SET pid=? WHERE folder=?', (proc.pid, folder))
            db.commit()
            db.close()
            return jsonify({'status': 'started'})
        
        elif act == 'stop':
            if folder in running_procs:
                try:
                    os.killpg(os.getpgid(running_procs[folder].pid), signal.SIGKILL)
                except:
                    pass
                del running_procs[folder]
            elif srv_data and srv_data['pid'] and psutil.pid_exists(srv_data['pid']):
                try:
                    os.killpg(os.getpgid(srv_data['pid']), signal.SIGKILL)
                except:
                    pass
            
            db.execute('UPDATE servers SET pid=NULL WHERE folder=?', (folder,))
            db.commit()
            db.close()
            
            with open(log_file_path, 'a') as f:
                f.write(f"\n[{now}] 🛑 Instance STOPPED\n")
            return jsonify({'status': 'stopped'})
        
        db.close()
        return jsonify({'status': 'ok'})
    
    @app.route('/server/log/<folder>')
    def server_log(folder):
        path = os.path.join(app.config['BASE_STORAGE'], folder, 'console.log')
        online = folder in running_procs and running_procs[folder].poll() is None
        uptime = get_precise_uptime(start_times.get(folder)) if online else None
        if os.path.exists(path):
            with open(path, 'r') as f:
                return jsonify({'log': f.read()[-5000:], 'online': online, 'uptime': uptime})
        return jsonify({'log': 'Waiting for logs...', 'online': online, 'uptime': uptime})
    
    @app.route('/server/set-startup/<folder>', methods=['POST'])
    def set_startup(folder):
        cmd = request.json.get('file')
        db = get_db()
        db.execute('UPDATE servers SET startup=? WHERE folder=?', (cmd, folder))
        db.commit()
        db.close()
        return jsonify({'status': 'success'})
    
    @app.route('/server/delete/<folder>', methods=['POST'])
    def delete_server(folder):
        if 'user_id' not in session:
            return jsonify({'status': 'error', 'msg': 'Not logged in'})
        
        db = get_db()
        srv_data = db.execute('SELECT server_status, pid, user_id FROM servers WHERE folder=?', (folder,)).fetchone()
        
        if not srv_data:
            db.close()
            return jsonify({'status': 'error', 'msg': 'Server not found'})
        
        if srv_data['user_id'] != session['user_id']:
            db.close()
            return jsonify({'status': 'error', 'msg': 'Access denied'})
        
        if srv_data and srv_data['server_status'] == 'suspended':
            db.close()
            return jsonify({'status': 'error', 'msg': 'Suspended servers cannot be deleted! Contact admin.'})
        
        if folder in running_procs:
            try:
                os.killpg(os.getpgid(running_procs[folder].pid), signal.SIGKILL)
            except:
                pass
            del running_procs[folder]
        
        db.execute('DELETE FROM servers WHERE folder=?', (folder,))
        db.commit()
        db.close()
        
        path = os.path.join(app.config['BASE_STORAGE'], folder)
        if os.path.exists(path):
            shutil.rmtree(path)
        
        return jsonify({'status': 'deleted'})
    
    @app.route('/servers')
    def list_servers():
        if 'user_id' not in session:
            return jsonify({'servers': []})
        db = get_db()
        rows = db.execute('SELECT * FROM servers WHERE user_id=?', (session['user_id'],)).fetchall()
        db.close()
        srvs = []
        for r in rows:
            f = r['folder']
            saved_pid = r['pid']
            online = False
            
            if f in running_procs and running_procs[f].poll() is None:
                online = True
            elif saved_pid and psutil.pid_exists(saved_pid):
                try:
                    p = psutil.Process(saved_pid)
                    if p.is_running() and p.status() != psutil.STATUS_ZOMBIE:
                        online = True
                except:
                    pass
            
            uptime = get_precise_uptime(start_times.get(f)) if online and f in start_times else ("Online" if online else "Offline")
            cpu = "0%"
            ram = "0MB"
            
            if online:
                try:
                    p_pid = running_procs[f].pid if f in running_procs else saved_pid
                    if p_pid:
                        process = psutil.Process(p_pid)
                        cpu = f"{process.cpu_percent(interval=0.1)}%"
                        ram = f"{process.memory_info().rss / (1024 * 1024):.1f}MB"
                except:
                    pass
            
            srvs.append({
                'name': r['name'], 
                'folder': f, 
                'online': online, 
                'startup': r['startup'], 
                'uptime': uptime, 
                'cpu': cpu, 
                'ram': ram, 
                'status': r['server_status']
            })
        return jsonify({'servers': srvs})
    
    @app.route('/add', methods=['POST'])
    def add_srv():
        if 'user_id' not in session:
            return jsonify({'status': 'error', 'msg': 'Not logged in'})
        
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
        count = db.execute('SELECT COUNT(*) as count FROM servers WHERE user_id=?', (session['user_id'],)).fetchone()['count']
        
        if count >= user['server_limit']:
            db.close()
            return jsonify({'status': 'error', 'msg': f"Server limit reached! Max: {user['server_limit']}"})
        
        name = request.json.get('name')
        if not name:
            db.close()
            return jsonify({'status': 'error', 'msg': 'Server name required'})
        
        folder = secure_filename(name).lower() + "_" + str(int(time.time()))
        db.execute('INSERT INTO servers (user_id, name, folder, status, startup) VALUES (?,?,?,?,?)', 
                   (session['user_id'], name, folder, 'Offline', 'main.py'))
        db.commit()
        db.close()
        
        server_path = os.path.join(app.config['BASE_STORAGE'], folder)
        os.makedirs(server_path, exist_ok=True)
        
        # Create a sample main.py file
        sample_main = '''# NE HOST - Sample Bot
import time

print("Bot Started Successfully!")
print("NE HOST - Python Bot Hosting")
print("Edit this file to add your bot code!")

while True:
    time.sleep(10)
    print("Bot is running...")
'''
        with open(os.path.join(server_path, 'main.py'), 'w') as f:
            f.write(sample_main)
        
        return jsonify({'status': 'success'})
    
    return app

# Create app instance
app = create_app()
import subprocess
import os
import json
import uuid
import psutil
import time
import threading
from datetime import datetime
from pathlib import Path

class ProcessManager:
    def __init__(self, processes_dir="processes", logs_dir="logs"):
        self.processes_dir = Path(processes_dir)
        self.logs_dir = Path(logs_dir)
        self.processes_dir.mkdir(exist_ok=True)
        self.logs_dir.mkdir(exist_ok=True)
        self.active_processes = {}
        self._load_existing_processes()
    
    def _load_existing_processes(self):
        for json_file in self.processes_dir.glob("*.json"):
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)
                    if 'pid' in data and self._is_process_alive(data['pid']):
                        data['status'] = 'running'
                        self.active_processes[data['process_id']] = data
                    else:
                        data['status'] = 'stopped'
                        self._save_process_data(data)
            except Exception as e:
                print(f"Error loading process: {e}")
    
    def _is_process_alive(self, pid):
        try:
            process = psutil.Process(pid)
            return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
    
    def _save_process_data(self, process_data):
        json_file = self.processes_dir / f"{process_data['process_id']}.json"
        data_to_save = process_data.copy()
        if 'start_time' in data_to_save and isinstance(data_to_save['start_time'], datetime):
            data_to_save['start_time'] = data_to_save['start_time'].isoformat()
        if 'stop_time' in data_to_save and isinstance(data_to_save['stop_time'], datetime):
            data_to_save['stop_time'] = data_to_save['stop_time'].isoformat()
        
        with open(json_file, 'w') as f:
            json.dump(data_to_save, f, indent=2)
    
    def start_script(self, script_path, user_id, script_name, args=None):
        process_id = str(uuid.uuid4())
        log_file = self.logs_dir / f"{process_id}.log"
        
        try:
            cmd = ['python', script_path]
            if args:
                cmd.extend(args)
            
            log_fd = open(log_file, 'w')
            log_fd.write(f"=== Script Started at {datetime.now()} ===\n")
            log_fd.write(f"Script: {script_path}\n")
            log_fd.write(f"Process ID: {process_id}\n")
            log_fd.write(f"{'='*50}\n\n")
            log_fd.flush()
            
            process = subprocess.Popen(
                cmd,
                stdout=log_fd,
                stderr=log_fd,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                cwd=os.path.dirname(script_path) if os.path.dirname(script_path) else os.getcwd()
            )
            
            process_data = {
                'process_id': process_id,
                'pid': process.pid,
                'user_id': user_id,
                'script_name': script_name,
                'script_path': script_path,
                'args': args or [],
                'status': 'running',
                'start_time': datetime.now(),
                'log_file': str(log_file)
            }
            
            self.active_processes[process_id] = process_data
            self._save_process_data(process_data)
            
            threading.Thread(target=self._monitor_process, args=(process_id, process.pid), daemon=True).start()
            
            return process_data
            
        except Exception as e:
            print(f"Error starting script: {e}")
            return None
    
    def _monitor_process(self, process_id, pid):
        while True:
            if not self._is_process_alive(pid):
                if process_id in self.active_processes:
                    self.active_processes[process_id]['status'] = 'stopped'
                    self.active_processes[process_id]['stop_time'] = datetime.now()
                    self._save_process_data(self.active_processes[process_id])
                    
                    log_file = self.active_processes[process_id].get('log_file')
                    if log_file and Path(log_file).exists():
                        with open(log_file, 'a') as f:
                            f.write(f"\n=== Script Stopped at {datetime.now()} ===\n")
                break
            time.sleep(5)
    
    def stop_process(self, process_id):
        process_data = None
        
        if process_id in self.active_processes:
            process_data = self.active_processes[process_id]
        else:
            json_file = self.processes_dir / f"{process_id}.json"
            if json_file.exists():
                with open(json_file, 'r') as f:
                    process_data = json.load(f)
        
        if not process_data:
            return False
        
        try:
            pid = process_data['pid']
            if self._is_process_alive(pid):
                process = psutil.Process(pid)
                process.terminate()
                try:
                    process.wait(timeout=5)
                except psutil.TimeoutExpired:
                    process.kill()
            
            process_data['status'] = 'stopped'
            process_data['stop_time'] = datetime.now()
            
            if process_id in self.active_processes:
                del self.active_processes[process_id]
            
            self._save_process_data(process_data)
            return True
            
        except Exception as e:
            print(f"Error stopping process: {e}")
            return False
    
    def restart_process(self, process_id):
        process_data = None
        
        if process_id in self.active_processes:
            process_data = self.active_processes[process_id]
        else:
            json_file = self.processes_dir / f"{process_id}.json"
            if json_file.exists():
                with open(json_file, 'r') as f:
                    process_data = json.load(f)
        
        if not process_data:
            return None
        
        self.stop_process(process_id)
        time.sleep(1)
        
        return self.start_script(
            process_data['script_path'],
            process_data['user_id'],
            process_data['script_name'],
            process_data.get('args', [])
        )
    
    def get_process(self, process_id):
        if process_id in self.active_processes:
            return self.active_processes[process_id]
        
        json_file = self.processes_dir / f"{process_id}.json"
        if json_file.exists():
            with open(json_file, 'r') as f:
                data = json.load(f)
                if 'start_time' in data and isinstance(data['start_time'], str):
                    data['start_time'] = datetime.fromisoformat(data['start_time'])
                return data
        return None
    
    def get_user_processes(self, user_id):
        user_processes = []
        
        for proc in self.active_processes.values():
            if proc['user_id'] == user_id:
                user_processes.append(proc)
        
        for json_file in self.processes_dir.glob("*.json"):
            with open(json_file, 'r') as f:
                proc = json.load(f)
                if proc['user_id'] == user_id and proc['process_id'] not in [p['process_id'] for p in user_processes]:
                    if 'start_time' in proc and isinstance(proc['start_time'], str):
                        proc['start_time'] = datetime.fromisoformat(proc['start_time'])
                    user_processes.append(proc)
        
        user_processes.sort(key=lambda x: x.get('start_time', datetime.min), reverse=True)
        return user_processes
    
    def get_process_log(self, process_id, lines=100):
        process_data = self.get_process(process_id)
        if process_data and 'log_file' in process_data:
            log_path = Path(process_data['log_file'])
            if log_path.exists():
                with open(log_path, 'r') as f:
                    all_lines = f.readlines()
                    return ''.join(all_lines[-lines:])
        return "লগ পাওয়া যায়নি"
    
    def get_process_status(self, process_id):
        if process_id in self.active_processes:
            if self._is_process_alive(self.active_processes[process_id]['pid']):
                return 'running'
        return 'stopped'

process_manager = ProcessManager()
import eventlet
eventlet.monkey_patch()

import requests
import re
import os
from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit
from datetime import datetime, timezone

FLAMENCO_SERVER = os.environ.get("FLAMENCO_SERVER", "localhost:9080")
FLAMENCO_API_URL = f"http://{FLAMENCO_SERVER}/api/v3"
FLAMENCO_JOBFILES_URL_ROOT = f"http://{FLAMENCO_SERVER}/job-files"

app = Flask(__name__)
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

try:
    SERVER_TZ = datetime.now().astimezone().tzinfo
except Exception:
    SERVER_TZ = timezone.utc

def utc_to_local(dt_utc):
    if not dt_utc:
        return None
    try:
        return dt_utc.astimezone(SERVER_TZ)
    except Exception:
        return dt_utc

def get_farm_status():
    try:
        resp = requests.get(f"{FLAMENCO_API_URL}/status", timeout=3)
        resp.raise_for_status()
        data = resp.json()
        return data.get('status', 'unknown')
    except Exception as e:
        print(f"Error querying farm status: {e}")
        return 'unavailable'

def get_workers():
    try:
        resp = requests.get(f"{FLAMENCO_API_URL}/worker-mgt/workers", timeout=3)
        resp.raise_for_status()
        workers = resp.json().get('workers', [])
        return workers
    except Exception as e:
        print(f"Error querying workers: {e}")
        return []

def get_jobs(statuses=["active", "queued"]):
    try:
        response = requests.post(
            f"{FLAMENCO_API_URL}/jobs/query",
            json={"status_in": statuses},
            timeout=5,
        )
        response.raise_for_status()
        jobs = response.json().get("jobs", [])
        return jobs
    except Exception as e:
        print("Error querying jobs:", e)
        return []

def get_tasks(job_id):
    try:
        response = requests.get(
            f"{FLAMENCO_API_URL}/jobs/{job_id}/tasks",
            timeout=5
        )
        response.raise_for_status()
        return response.json().get("tasks", [])
    except Exception as e:
        print(f"Error querying tasks for job {job_id}:", e)
        return []

def get_log_url(job_id, task_id):
    job_prefix = job_id[:4]
    return f"{FLAMENCO_JOBFILES_URL_ROOT}/job-{job_prefix}/{job_id}/task-{task_id}.txt"

def parse_time_remaining(line):
    m = re.search(r"Remaining:((?:\d{1,2}:)?\d{1,2}:\d{2}(?:\.\d{1,2})?)", line)
    if m:
        return m.group(1)
    return None

def extract_render_step_and_tile(lines):
    tile_info = ""
    step_label = ""
    step_patterns = [
        (r"\|\s*Scene, View Layer \|\s*Synchronizing object \|\s*(.+)$", "Synchronizing object"),
        (r"\|\s*Scene, View Layer \|\s*Synchronizing object$", "Synchronizing object"),
        (r"\|\s*Scene, View Layer \|\s*Initializing$", "Initializing"),
        (r"\|\s*Scene, View Layer \|\s*Waiting for render to start", "Waiting for render to start"),
        (r"\|\s*Scene, View Layer \|\s*Loading render kernels", "Loading render kernels"),
        (r"\|\s*Scene, View Layer \|\s*Updating Scene$", "Updating Scene"),
        (r"\|\s*Scene, View Layer \|\s*Updating Shaders$", "Updating Shaders"),
        (r"\|\s*Scene, View Layer \|\s*Updating Procedurals$", "Updating Procedurals"),
        (r"\|\s*Scene, View Layer \|\s*Updating Background$", "Updating Background"),
        (r"\|\s*Scene, View Layer \|\s*Updating Camera$", "Updating Camera"),
        (r"\|\s*Scene, View Layer \|\s*Updating Meshes Flags$", "Updating Meshes Flags"),
        (r"\|\s*Scene, View Layer \|\s*Updating Objects Flags$", "Updating Objects Flags"),
        (r"\|\s*Scene, View Layer \|\s*Updating Meshes$", "Updating Meshes"),
        (r"\|\s*Scene, View Layer \|\s*Updating Particle Systems", "Updating Particle Systems"),
        (r"\|\s*Scene, View Layer \|\s*Updating Mesh \|\s*Computing normals", "Computing normals"),
        (r"\|\s*Scene, View Layer \|\s*Updating Mesh \|\s*Copying Mesh to device", "Copying Mesh to device"),
        (r"\|\s*Scene, View Layer \|\s*Updating Mesh \|\s*Copying Curves to device", "Copying Curves to device"),
        (r"\|\s*Scene, View Layer \|\s*Updating Mesh \|\s*Computing attributes", "Computing attributes"),
        (r"\|\s*Scene, View Layer \|\s*Updating Mesh \|\s*Copying Attributes to device", "Copying Attributes to device"),
        (r"\|\s*Scene, View Layer \|\s*Updating Mesh \|\s*Computing Displacement Mesh", "Computing Displacement Mesh"),
        (r"\|\s*Scene, View Layer \|\s*Updating Mesh \|\s*Updating Displacement Images", "Updating Displacement Images"),
        (r"\|\s*Scene, View Layer \|\s*Updating Geometry BVH.*?Building BVH", "Building BVH"),
        (r"\|\s*Scene, View Layer \|\s*Updating Scene BVH \|\s*Building", "Building Scene BVH"),
        (r"\|\s*Scene, View Layer \|\s*Updating Scene BVH \|\s*Building BVH", "Building Scene BVH"),
        (r"\|\s*Scene, View Layer \|\s*Updating Scene BVH \|\s*Copying BVH to device", "Copying BVH to device"),
        (r"\|\s*Scene, View Layer \|\s*Updating Objects \|\s*Copying Transformations to device", "Copying Transformations"),
        (r"\|\s*Scene, View Layer \|\s*Updating Objects \|\s*Applying Static Transformations", "Applying Static Transformations"),
        (r"\|\s*Scene, View Layer \|\s*Updating Particle Systems \|\s*Copying Particles to device", "Copying Particles to device"),
        (r"\|\s*Scene, View Layer \|\s*Updating Objects$", "Updating Objects"),
        (r"\|\s*Scene, View Layer \|\s*Updating Lights \|\s*Importance map", "Updating Lights Importance map"),
        (r"\|\s*Scene, View Layer \|\s*Updating Lights$", "Updating Lights"),
        (r"\|\s*Scene, View Layer \|\s*Updating Images$", "Updating Images"),
        (r"\|\s*Scene, View Layer \|\s*Updating Camera Volume$", "Updating Camera Volume"),
        (r"\|\s*Scene, View Layer \|\s*Updating Lookup Tables$", "Updating Lookup Tables"),
        (r"\|\s*Scene, View Layer \|\s*Updating Film$", "Updating Film"),
        (r"\|\s*Scene, View Layer \|\s*Updating Integrator$", "Updating Integrator"),
        (r"\|\s*Scene, View Layer \|\s*Updating Baking$", "Updating Baking"),
        (r"\|\s*Scene, View Layer \|\s*Updating Device \|\s*Writing constant memory", "Writing constant memory"),
        (r"\|\s*Scene, View Layer \|\s*Rendered \d+/\d+ Tiles, Sample \d+/\d+", "Rendering Tiles"),
        (r"\|\s*Scene, View Layer \|\s*Finishing$", "Finishing"),
        (r"\|\s*Scene, View Layer \|\s*Denoising$", "Denoising"),
        (r"\|\s*Scene \|\s*Reading full buffer from disk", "Reading full buffer from disk"),
        (r"\|\s*Scene, View Layer \|\s*Finished$", "Finished"),
    ]
    for line in reversed(lines):
        m = re.search(r"Rendered\s+(\d+)\s*/\s*(\d+)\s+Tiles", line)
        if m:
            tile_info = f"Rendering tile {m.group(1)} of {m.group(2)}"
        for pat, label in step_patterns:
            if re.search(pat, line):
                step_label = label
        if tile_info and step_label:
            break
    return step_label, tile_info

def fetch_render_progress_and_step(log_url):
    try:
        resp = requests.get(log_url, timeout=3)
        if resp.status_code != 200:
            return 0, 0, 0, "No log", None, "", "", ""
        lines = resp.text.splitlines()
        pat = re.compile(r"Rendered\s+(\d+)\s*/\s*(\d+)", re.IGNORECASE)
        last_update = datetime.now(SERVER_TZ).strftime('%Y-%m-%d %H:%M:%S')
        step_label, tile_info = extract_render_step_and_tile(lines)
        time_remaining = ""
        for line in reversed(lines):
            m = pat.search(line)
            if m:
                cur, total = int(m.group(1)), int(m.group(2))
                pct = int(cur / total * 100) if total else 0
                for lookback in range(0, 10):
                    idx = lines.index(line) - lookback
                    if idx < 0:
                        break
                    tr = parse_time_remaining(lines[idx])
                    if tr:
                        time_remaining = tr
                        break
                return cur, total, pct, f"{cur} / {total}", last_update, step_label, tile_info, time_remaining
            m2 = re.search(r"Building BVH\s+(\d+)%", line)
            if m2:
                pct = int(m2.group(1))
                return pct, 100, pct, f"{pct}%", last_update, "Building BVH", "", ""
        for line in reversed(lines):
            tr = parse_time_remaining(line)
            if tr:
                time_remaining = tr
                break
        return 0, 0, 0, "No progress", last_update, step_label, tile_info, time_remaining
    except Exception as e:
        print(f"Error fetching log {log_url}:", e)
        return 0, 0, 0, "Log error", None, "", "", ""

def parse_iso8601(dtstr):
    if dtstr:
        try:
            if dtstr.endswith('Z'):
                dtstr = dtstr[:-1]
            return datetime.fromisoformat(dtstr).replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None

def collect_job_data():
    jobs = get_jobs(["active", "queued"])
    jobs_display = []
    for job in jobs:
        job_id = job.get("id")
        job_name = job.get("name", "-")
        tasks = get_tasks(job_id)
        n_tasks = len(tasks)
        n_tasks_completed = 0
        tasks_display = []
        for t in tasks:
            task_id = t.get("id")
            task_name = t.get("name") or t.get("type") or task_id
            task_status = t.get("status", "-").capitalize()
            log_url = get_log_url(job_id, task_id)
            if t.get("status") == "completed":
                progress_pct = 100
                progress_text = "Completed"
                n_tasks_completed += 1
                last_log_time = ""
                step_label = "Finished"
                tile_info = ""
                time_remaining = ""
            elif t.get("status") == "failed":
                progress_pct = 100
                progress_text = "Failed"
                n_tasks_completed += 1
                last_log_time = ""
                step_label = "Failed"
                tile_info = ""
                time_remaining = ""
            else:
                cur, total, pct, progress, last_log_time, step_label, tile_info, time_remaining = fetch_render_progress_and_step(log_url)
                progress_pct = pct
                progress_text = progress
            tasks_display.append({
                "task_id": task_id,
                "task_name": task_name,
                "status": task_status,
                "progress_pct": progress_pct,
                "progress_text": progress_text,
                "log_url": log_url,
                "last_log_time": last_log_time or "",
                "step_label": step_label,
                "tile_info": tile_info,
                "time_remaining": time_remaining,
            })
        job_progress_pct = int((n_tasks_completed / n_tasks) * 100) if n_tasks > 0 else 0
        jobs_display.append({
            "job_id": job_id,
            "job_name": job_name,
            "job_progress_pct": job_progress_pct,
            "job_status": job.get("status", "-").capitalize(),
            "tasks": tasks_display,
            "n_tasks": n_tasks,
            "n_tasks_completed": n_tasks_completed
        })

    completed_jobs = get_jobs(["completed"])
    for job in completed_jobs:
        job['updated_dt'] = parse_iso8601(job.get("updated") or job.get("completed"))
    completed_jobs = sorted(
        [j for j in completed_jobs if j.get('updated_dt')],
        key=lambda x: x['updated_dt'], reverse=True
    )
    completed_jobs_limit = 10
    completed_jobs_display = []
    for job in completed_jobs[:completed_jobs_limit]:
        job_id = job.get("id")
        dt_utc = job['updated_dt']
        dt_local = utc_to_local(dt_utc)
        completed_job = {
            "job_id": job_id,
            "job_name": job.get("name", "-"),
            "completed_time": dt_local.strftime("%Y-%m-%d %H:%M:%S") if dt_local else "N/A",
            "job_status": job.get("status", "-").capitalize(),
        }
        task_objs = get_tasks(job_id)
        task_display = []
        for t in task_objs:
            task_id = t.get("id")
            task_name = t.get("name") or t.get("type") or task_id
            task_status = t.get("status", "-").capitalize()
            log_url = get_log_url(job_id, task_id)
            if t.get("status") == "completed":
                progress_pct = 100
                progress_text = "Completed"
                step_label = "Finished"
                tile_info = ""
                time_remaining = ""
            elif t.get("status") == "failed":
                progress_pct = 100
                progress_text = "Failed"
                step_label = "Failed"
                tile_info = ""
                time_remaining = ""
            else:
                cur, total, pct, progress, last_log_time, step_label, tile_info, time_remaining = fetch_render_progress_and_step(log_url)
                progress_pct = pct
                progress_text = progress
            task_display.append({
                "task_id": task_id,
                "task_name": task_name,
                "status": task_status,
                "progress_pct": progress_pct,
                "progress_text": progress_text,
                "log_url": log_url,
                "step_label": step_label,
                "tile_info": tile_info,
                "time_remaining": time_remaining,
            })
        completed_job['tasks'] = task_display
        completed_jobs_display.append(completed_job)

    return {"jobs": jobs_display, "completed_jobs": completed_jobs_display, "workers": get_workers()}

@app.route("/")
def index():
    farm_status = get_farm_status()
    return render_template_string(TEMPLATE, flamenco_server=FLAMENCO_SERVER, farm_status=farm_status)

def background_thread():
    while True:
        data = collect_job_data()
        data['farm_status'] = get_farm_status()
        socketio.emit("progress_update", data)
        socketio.sleep(1)

@socketio.on('connect')
def on_connect():
    data = collect_job_data()
    data['farm_status'] = get_farm_status()
    emit("progress_update", data)

TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Flamenco Live Monitor</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js"></script>
    <link rel="icon" type="image/svg+xml" href="{{ url_for('static', filename='favicon.svg') }}">
    <style>
        body {
            background: #222;
            color: #e0e0e0;
            font-family: Segoe UI, Arial, sans-serif;
            margin: 0; padding: 0;
        }
        .main-flex {
            display: flex;
            flex-direction: row;
            align-items: stretch;
            min-height: 100vh;
            max-width: 1600px;
            margin: 0 auto;
        }
        .workers-sidebar,
        .completed-sidebar {
            width: 340px;
            background: #222329;
            border-radius: 0 12px 12px 0;
            box-sizing: border-box;
            box-shadow: 2px 0 16px #0004;
            position: fixed;
            top: 0;
            height: 100vh;
            z-index: 10;
            overflow-y: auto;
            padding: 22px 12px 30px 18px;
            border-right: 1.5px solid #363646;
        }
        .workers-sidebar {
            left: 0;
            border-radius: 0 12px 12px 0;
            border-right: 1.5px solid #363646;
        }
        .completed-sidebar {
            right: 0;
            border-radius: 12px 0 0 12px;
            border-left: 1.5px solid #363646;
            border-right: none;
            padding: 22px 18px 30px 12px;
            box-shadow: -2px 0 16px #0004;
        }
        .workers-title, .completed-title {
            font-size: 1.20em;
            margin-bottom: 15px;
            color: #a7ebfa;
            letter-spacing: 0.07em;
            font-weight: 500;
            text-align: left;
        }
        .worker-entry {
            background: #29293a;
            border-radius: 7px;
            margin-bottom: 12px;
            box-shadow: 0 2px 7px #0002;
            transition: background 0.18s;
        }
        .worker-header {
            display: flex;
            align-items: center;
            cursor: pointer;
            padding: 13px 10px 13px 10px;
            border-radius: 7px;
            transition: background 0.15s;
        }
        .worker-header:hover {
            background: #2e3950;
        }
        .worker-name {
            font-weight: 600;
            font-size: 1.08em;
            margin-right: 18px;
        }
        .worker-status {
            font-size: 1em;
            font-family: monospace;
            margin-right: 16px;
            padding: 1px 9px 1px 8px;
            border-radius: 8px;
            background: #1b212b;
            color: #80ffd2;
            font-weight: 500;
        }
        .worker-status.awake { color: #73ff7a; background: #223d1e; }
        .worker-status.offline { color: #ff7878; background: #341d1d; }
        .worker-status.idle { color: #fff49a; background: #32320f; }
        .worker-status.busy { color: #7ad1ff; background: #182340; }
        .worker-version {
            font-size: 0.97em;
            color: #8ef2f3;
        }
        .worker-toggle-arrow {
            font-size: 1.45em;
            color: #79e6fa;
            margin-right: 10px;
        }
        .worker-details {
            background: #1c1c25;
            border-radius: 0 0 7px 7px;
            padding: 13px 15px 10px 31px;
            margin-bottom: 2px;
            font-size: 0.99em;
            color: #eee;
            box-shadow: 0 2px 7px #0001;
        }
        .worker-details-row {
            margin-bottom: 5px;
            font-family: monospace;
        }
        .container {
            flex: 1;
            max-width: 1100px;
            margin: 40px auto;
            background: #292929;
            border-radius: 8px;
            box-shadow: 0 4px 20px #000a;
            padding: 32px;
            margin-left: 360px; /* space for left sidebar */
            margin-right: 360px; /* space for right sidebar */
            min-height: 100vh;
        }
        .status-bar {
            width: 410px;
            margin: 26px auto 0 auto;
            text-align: center;
            font-size: 1.18em;
            border-radius: 12px;
            box-shadow: 0 3px 14px #0006;
            background: #18191a;
            padding: 14px 0 11px 0;
            letter-spacing: 0.04em;
        }
        .status-red { color: #ff2b2b; font-weight: bold; }
        .status-yellow { color: #ffdb37; font-weight: bold; }
        .status-green { color: #7bf178; font-weight: bold; }
        .status-orange { color: #ff9800; font-weight: bold; }
        h2 { margin-bottom: 24px; }
        .job-block {
            margin-bottom: 38px;
            padding: 24px;
            background: #232323;
            border-radius: 7px;
            box-shadow: 0 2px 9px #0006;
        }
        .progress-bar-bg {
            width: 380px;
            height: 28px;
            background: #333;
            border-radius: 10px;
            overflow: hidden;
            display: inline-block;
            vertical-align: middle;
            margin-right: 8px;
        }
        .progress-bar {
            height: 100%;
            background: linear-gradient(90deg, #27e2f3, #1db385 82%, #58f7b5);
            border-radius: 8px;
            transition: width 0.7s cubic-bezier(.44,.15,.28,1.11);
        }
        .progress-label {
            font-size: 1.08em;
            font-family: monospace;
            color: #afffd3;
            margin-left: 12px;
            vertical-align: middle;
        }
        .tile-label {
            font-size: 0.98em;
            color: #ffb97e;
            margin-left: 10px;
            vertical-align: middle;
            font-family: monospace;
        }
        .time-remaining-label {
            font-size: 0.97em;
            color: #96f797;
            margin-left: 14px;
            vertical-align: middle;
            font-family: monospace;
        }
        .task-table, .completed-task-table {
            width: 99%;
            border-collapse: collapse;
            margin-top: 18px;
        }
        .task-table th, .task-table td, .completed-task-table th, .completed-task-table td {
            padding: 8px 12px;
            border-bottom: 1px solid #353535;
        }
        .task-table th {
            background: #232840;
            color: #7cd7ff;
            cursor: pointer;
            user-select: none;
        }
        .task-table tr:last-child td { border-bottom: none; }
        .log-link { color: #53e7fc; text-decoration: underline; }
        .completed-job-list-item {
            background: #27283a;
            border-radius: 8px;
            padding: 13px 9px 13px 13px;
            margin-bottom: 11px;
            cursor: pointer;
            transition: background 0.15s;
            box-shadow: 0 1px 7px #0002;
            display: flex;
            flex-direction: column;
        }
        .completed-job-list-item:hover {
            background: #25315a;
        }
        .completed-title {
            margin-bottom: 13px;
        }
        .completed-job-list-name {
            font-size: 1.09em;
            font-weight: 600;
        }
        .completed-job-list-id {
            font-size: 0.97em;
            color: #98e6ff;
            margin-left: 5px;
        }
        .completed-job-list-status {
            font-size: 0.99em;
            color: #ffd96d;
            margin-left: 7px;
        }
        .completed-job-list-time {
            font-size: 0.98em;
            color: #aeffae;
            margin-left: 5px;
        }
        .completed-task-table th {
            background: #243248;
            color: #6bc9f3;
        }

        /* Modal styles */
        .modal-overlay {
            display: none;
            position: fixed;
            z-index: 10001;
            left: 0;
            top: 0;
            width: 100vw;
            height: 100vh;
            background: rgba(20, 20, 40, 0.88);
        }
        .modal-overlay.active {
            display: block;
        }
        .modal-dialog {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            min-width: 420px;
            min-height: 200px;
            background: #242637;
            border-radius: 15px;
            box-shadow: 0 9px 48px #000c;
            padding: 35px 35px 30px 35px;
            max-width: 850px;
            width: 90vw;
            max-height: 88vh;
            overflow-y: auto;
            color: #fff;
        }
        .modal-close {
            position: absolute;
            top: 15px;
            right: 23px;
            font-size: 2.1em;
            font-weight: 800;
            color: #b4f4fa;
            cursor: pointer;
            z-index: 9999;
            transition: color 0.18s;
        }
        .modal-close:hover { color: #ff7b7b; }
        .modal-job-header {
            font-size: 1.25em;
            font-weight: bold;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .modal-job-id {
            font-size: 0.98em;
            color: #99f1f6;
        }
        .modal-job-status {
            font-size: 0.98em;
            color: #ffd96d;
        }
        .modal-job-time {
            font-size: 0.97em;
            color: #aeffae;
        }
        .modal-tasks-label {
            margin-top: 16px;
            font-size: 1.08em;
            font-weight: 600;
            color: #9be0fd;
            margin-bottom: 5px;
        }
        @media (max-width:1200px) {
            .main-flex { flex-direction: column; }
            .workers-sidebar, .completed-sidebar {
                position: static;
                width: 99%;
                border-radius: 0 0 12px 12px;
                height: auto;
                min-height: 0;
                margin-bottom: 10px;
            }
            .container { margin-left: 0; margin-right: 0; }
            .modal-dialog { min-width: 98vw; padding: 15px; }
        }
        @media (max-width: 500px) {
            .modal-dialog { min-width: 98vw; font-size: 0.96em; }
        }
    </style>
</head>
<body>
    <div id="farm-status" class="status-bar"></div>
    <div class="main-flex">
        <div class="workers-sidebar">
            <div class="workers-title">Flamenco Workers</div>
            <div id="workers-list"></div>
        </div>
        <div class="container">
            <h2>Flamenco Jobs & Task Progress <span id="updating" style="font-size:0.7em; color:#6f8;">(Live)</span></h2>
            <div id="jobs-list"></div>
        </div>
        <div class="completed-sidebar">
            <div class="completed-title">Last 10 Completed Jobs</div>
            <div id="completed-jobs-list"></div>
        </div>
    </div>

    <!-- Modal for completed job details -->
    <div class="modal-overlay" id="completed-job-modal-overlay" onclick="closeCompletedJobModal(event)">
        <div class="modal-dialog" id="completed-job-modal-dialog" onclick="event.stopPropagation()">
            <div class="modal-close" onclick="closeCompletedJobModal(event)">&times;</div>
            <div id="completed-job-modal-content"></div>
        </div>
    </div>
    <script>
        function updateFarmStatusBox(farmStatus) {
            let colorClass = "status-yellow";
            let label = farmStatus.charAt(0).toUpperCase() + farmStatus.slice(1);
            if (farmStatus.toLowerCase() === "inoperative") {
                colorClass = "status-red";
            } else if (farmStatus.toLowerCase() === "idle") {
                colorClass = "status-yellow";
            } else if (farmStatus.toLowerCase() === "active") {
                colorClass = "status-green";
            } else if (farmStatus.toLowerCase() === "waiting") {
                colorClass = "status-orange";
            } else if (farmStatus.toLowerCase() === "unavailable") {
                colorClass = "status-red";
                label = "Unavailable";
            }
            document.getElementById("farm-status").innerHTML =
              `Farm Status: <span class="${colorClass}">${label}</span>`;
        }
        updateFarmStatusBox("{{ farm_status }}");

        var taskSortingState = {};
        var completedDropdownState = {};
        var lastJobsData = [];
        var workersDropdownState = {};
        var lastCompletedJobs = [];

        function createProgressBar(pct, width=200, height=16) {
            return `<div class="progress-bar-bg" style="width:${width}px;height:${height}px;">
                <div class="progress-bar" style="width:${pct}%;"></div>
            </div>`;
        }
        function getSortedClass(state, col) {
            if (state.field !== col) return "";
            return state.asc ? "sorted-asc" : "sorted-desc";
        }
        function sortTasks(tasks, state) {
            if (!state || !state.field || state.field === "default") return tasks;
            let key = state.field;
            let asc = state.asc;
            let cmp = (a, b) => {
                if (key === "progress_pct") return (asc ? 1 : -1) * (a.progress_pct - b.progress_pct);
                let av = (a[key] || "").toString().toLowerCase();
                let bv = (b[key] || "").toString().toLowerCase();
                if (av === bv) return 0;
                return asc ? (av < bv ? -1 : 1) : (av > bv ? -1 : 1);
            };
            return [...tasks].sort(cmp);
        }
        function renderTaskRows(tasks, jobId, state) {
            let sorted = sortTasks(tasks, state);
            return sorted.map(function(task) {
                return `<tr>
                    <td>${task.task_name}</td>
                    <td>${task.status}</td>
                    <td>
                        ${createProgressBar(task.progress_pct, 160, 14)}
                        <span class="progress-label">${task.progress_pct}%</span>
                        ${
                            task.tile_info && task.tile_info !== "" ?
                            `<span class="tile-label">${task.tile_info}</span>` : ""
                        }
                        ${
                            task.step_label && task.step_label !== "" ?
                            `<span class="step-label">${task.step_label}</span>` : ""
                        }
                        ${
                            task.time_remaining && task.time_remaining !== "" ?
                            `<span class="time-remaining-label">ETA: ${task.time_remaining}</span>` : ""
                        }
                    </td>
                    <td>
                        <a class="log-link" href="${task.log_url}" target="_blank">Log File</a>
                    </td>
                </tr>`;
            }).join("");
        }
        function toggleTaskSorting(jobId, col) {
            let state = taskSortingState[jobId] || {field: "default", asc: true};
            if (state.field === col) {
                state.asc = !state.asc;
            } else {
                state.field = col;
                state.asc = true;
            }
            taskSortingState[jobId] = state;
            let job = lastJobsData.find(j => j.job_id === jobId);
            if (job) {
                let tableBody = document.querySelector(`#task-table-${jobId} tbody`);
                tableBody.innerHTML = renderTaskRows(job.tasks, jobId, state);
            }
            ['task_name', 'status', 'progress_pct', 'log_url'].forEach(colName => {
                let th = document.getElementById(`th-${colName}-${jobId}`);
                if (th) th.className = getSortedClass(state, colName);
            });
        }
        function renderJobs(jobs) {
            lastJobsData = jobs;
            let html = '';
            jobs.forEach(function(job) {
                html += `<div class="job-block">
                    <div style="margin-bottom:9px;">
                        <b style="font-size:1.1em;">${job.job_name}</b>
                        <span style="font-size:0.97em;color:#9de0fd;">[${job.job_id}]</span>
                        <span style="font-size:0.93em;color:#ffd;"> (${job.n_tasks_completed}/${job.n_tasks} tasks completed)</span>
                    </div>
                    <div style="margin-bottom:18px;">
                        ${createProgressBar(job.job_progress_pct, 380, 28)}
                        <span class="progress-label">${job.job_progress_pct}%</span>
                    </div>
                    <table class="task-table" id="task-table-${job.job_id}">
                        <thead>
                            <tr>
                                <th id="th-task_name-${job.job_id}" onclick="toggleTaskSorting('${job.job_id}','task_name')">Task Name</th>
                                <th id="th-status-${job.job_id}" onclick="toggleTaskSorting('${job.job_id}','status')">Status</th>
                                <th id="th-progress_pct-${job.job_id}" onclick="toggleTaskSorting('${job.job_id}','progress_pct')">Render Progress</th>
                                <th id="th-log_url-${job.job_id}" onclick="toggleTaskSorting('${job.job_id}','log_url')">Log File</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${renderTaskRows(job.tasks, job.job_id, taskSortingState[job.job_id])}
                        </tbody>
                    </table>
                </div>`;
            });
            document.getElementById("jobs-list").innerHTML = html;
        }

        // Modal popup for completed jobs
        function renderCompletedJobs(jobs) {
            lastCompletedJobs = jobs;
            let html = '';
            jobs.forEach(function(job, idx) {
                html += `
                    <div class="completed-job-list-item" onclick="showCompletedJobModal(${idx})">
                        <span>
                            <span class="completed-job-list-name">${job.job_name}</span>
                            <span class="completed-job-list-id">[${job.job_id}]</span>
                        </span>
                        <span>
                            <span class="completed-job-list-status">${job.job_status || ''}</span>
                            <span class="completed-job-list-time">${job.completed_time ? 'Completed: ' + job.completed_time : ''}</span>
                        </span>
                    </div>
                `;
            });
            document.getElementById("completed-jobs-list").innerHTML = html;
        }

        function showCompletedJobModal(idx) {
            var job = lastCompletedJobs[idx];
            if (!job) return;
            let modalContent = `
                <div class="modal-job-header">
                    <span>${job.job_name}</span>
                    <span class="modal-job-id">[${job.job_id}]</span>
                    <span class="modal-job-status">${job.job_status || ''}</span>
                    <span class="modal-job-time">${job.completed_time ? 'Completed: ' + job.completed_time : ''}</span>
                </div>
                <div class="modal-tasks-label">Tasks</div>
                <table class="completed-task-table">
                    <thead>
                        <tr>
                            <th>Task Name</th>
                            <th>Status</th>
                            <th>Render Progress</th>
                            <th>Log File</th>
                        </tr>
                    </thead>
                    <tbody>
                    ${
                        job.tasks.map(function(task) {
                            return `<tr>
                                <td>${task.task_name}</td>
                                <td>${task.status}</td>
                                <td>
                                    ${createProgressBar(task.progress_pct, 160, 14)}
                                    <span class="progress-label">${task.progress_pct}%</span>
                                    ${
                                        task.tile_info && task.tile_info !== "" ?
                                        `<span class="tile-label">${task.tile_info}</span>` : ""
                                    }
                                    ${
                                        task.step_label && task.step_label !== "" ?
                                        `<span class="step-label">${task.step_label}</span>` : ""
                                    }
                                    ${
                                        task.time_remaining && task.time_remaining !== "" ?
                                        `<span class="time-remaining-label">ETA: ${task.time_remaining}</span>` : ""
                                    }
                                </td>
                                <td>
                                    <a class="log-link" href="${task.log_url}" target="_blank">Log File</a>
                                </td>
                            </tr>`;
                        }).join('')
                    }
                    </tbody>
                </table>
            `;
            document.getElementById('completed-job-modal-content').innerHTML = modalContent;
            document.getElementById('completed-job-modal-overlay').classList.add('active');
        }
        window.showCompletedJobModal = showCompletedJobModal;

        function closeCompletedJobModal(event) {
            document.getElementById('completed-job-modal-overlay').classList.remove('active');
        }
        window.closeCompletedJobModal = closeCompletedJobModal;

        // WORKERS PANEL LOGIC
        function renderWorkers(workers) {
            let html = '';
            workers.forEach(function(worker, idx) {
                let dropdownId = 'worker-dropdown-' + idx;
                let isOpen = workersDropdownState[dropdownId] || false;
                html += `<div class="worker-entry">
                    <div class="worker-header" onclick="toggleWorkerDropdown('${dropdownId}')">
                        <span class="worker-toggle-arrow" id="worker-arrow-${dropdownId}">${isOpen ? '▼' : '►'}</span>
                        <span class="worker-name">${worker.name || '(Unnamed)'}</span>
                        <span class="worker-status ${worker.status.toLowerCase()}">${worker.status}</span>
                        <span class="worker-version">v${worker.version || '-'}</span>
                    </div>
                    <div class="worker-details" id="${dropdownId}" style="display:${isOpen ? 'block' : 'none'};">
                        <div class="worker-details-row"><b>ID:</b> <span>${worker.id}</span></div>
                        <div class="worker-details-row"><b>Status:</b> <span>${worker.status}</span></div>
                        <div class="worker-details-row"><b>Version:</b> <span>${worker.version}</span></div>
                        <div class="worker-details-row"><b>Can Restart:</b> <span>${worker.can_restart}</span></div>
                        <div class="worker-details-row"><b>Last Seen:</b> <span>${worker.last_seen}</span></div>
                    </div>
                </div>`;
            });
            document.getElementById("workers-list").innerHTML = html;
        }
        function toggleWorkerDropdown(dropdownId) {
            workersDropdownState[dropdownId] = !workersDropdownState[dropdownId];
            let el = document.getElementById(dropdownId);
            let arrow = document.getElementById("worker-arrow-" + dropdownId);
            if (el && arrow) {
                el.style.display = workersDropdownState[dropdownId] ? 'block' : 'none';
                arrow.innerHTML = workersDropdownState[dropdownId] ? '▼' : '►';
            }
        }
        window.toggleWorkerDropdown = toggleWorkerDropdown;

        var socket = io();
        socket.on('progress_update', function(data) {
            renderJobs(data.jobs || []);
            renderCompletedJobs(data.completed_jobs || []);
            renderWorkers(data.workers || []);
            if (data.farm_status) {
                updateFarmStatusBox(data.farm_status);
            }
        });
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    socketio.start_background_task(target=background_thread)
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)

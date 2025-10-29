#!/usr/bin/env python3
"""
Render-ready Flask app for cookie-based Instagram thread/message sender.

Usage:
- Start: `python app.py`
- Open the web UI (Render will give you a public URL, locally use http://127.0.0.1:5000)
- Upload:
    - cookies file (contains sessionid)
    - message file (plain text)
    - speed file (number of seconds)
    - either enter thread UID text or upload a small file containing it
- Click Start. Check Live Console for progress.

Dependencies:
    pip install flask instagrapi Pillow Werkzeug

Security:
- Keep sessionid private. Do not use for spam.
"""
from flask import Flask, request, jsonify, Response, render_template_string, redirect, url_for
import os
import threading
import time
import json
from werkzeug.utils import secure_filename

# Optional: instagrapi may raise errors if not installed or versions mismatch.
try:
    from instagrapi import Client
except Exception as e:
    Client = None  # We'll report error later if user tries to start worker.

# --- Config ---
UPLOAD_FOLDER = "/tmp/ig_sender_uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_TEXT_EXT = {"txt", "json", "cookie"}
LOG_MAX_LINES = 800

# --- App ---
app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# In-memory state & logs
state = {
    "running": False,
    "thread_id": None,
    "message": None,
    "interval": 5,
    "log": [],
    "last_error": None,
}
log_lock = threading.Lock()


# ---- Helpers ----
def allowed_file(filename):
    if not filename:
        return False
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_TEXT_EXT


def append_log(line):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {line}"
    with log_lock:
        state["log"].append(entry)
        if len(state["log"]) > LOG_MAX_LINES:
            state["log"] = state["log"][-LOG_MAX_LINES:]


def extract_sessionid_from_file(path):
    """
    Accepts:
      - raw sessionid in file
      - JSON containing {"sessionid": "..."}
      - cookie line containing sessionid=...
    Returns sessionid string or None.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read().strip()
    except Exception:
        return None

    if not content:
        return None

    # Try parse JSON
    try:
        obj = json.loads(content)
        for key in ("sessionid", "session", "cookie"):
            if key in obj and obj[key]:
                return str(obj[key]).strip()
    except Exception:
        pass

    # Try cookie style "sessionid=ABC; other=..."
    if "sessionid=" in content:
        parts = content.replace("\n", ";").split(";")
        for p in parts:
            if "sessionid=" in p:
                return p.split("sessionid=")[-1].strip()

    # If the file is small and looks like a token, return it
    if len(content) > 10 and ("\n" not in content or content.count("\n") < 3):
        return content.strip()

    return None


# ---- Worker ----
def worker_send_to_thread(sessionid, thread_uid, message_text, interval_seconds):
    append_log("Worker started.")
    if Client is None:
        append_log("instagrapi is not installed or failed to import. Cannot proceed.")
        state["last_error"] = "instagrapi import failed"
        state["running"] = False
        return

    client = Client()
    try:
        append_log("Logging in using sessionid...")
        client.login_by_sessionid(sessionid)
        append_log("Login successful.")
    except Exception as e:
        append_log(f"Login failed: {repr(e)}")
        state["last_error"] = f"login_failed: {repr(e)}"
        state["running"] = False
        return

    # Attempt a single send (the UI starts one job per click). Respect interval for safety.
    try:
        append_log(f"Sending message to thread uid: {thread_uid}")
        try:
            client.direct_send(message_text, [thread_uid])
            append_log(f"Message sent to thread {thread_uid} using direct_send().")
        except Exception as e:
            append_log(f"direct_send failed: {repr(e)} -- trying fallback message_send()")
            try:
                # message_send signature may vary; try best-effort
                client.message_send(message_text, thread_uid)
                append_log(f"Message sent to thread {thread_uid} using message_send().")
            except Exception as e2:
                append_log(f"Both send attempts failed: {repr(e2)}")
                state["last_error"] = f"send_failed: {repr(e2)}"
    except Exception as e:
        append_log(f"Unexpected error in send flow: {repr(e)}")
        state["last_error"] = f"unexpected_send_error: {repr(e)}"
    finally:
        try:
            client.logout()
            append_log("Logged out client.")
        except Exception:
            pass
        state["running"] = False
        append_log("Worker finished.")


# ---- Routes ----
INDEX_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>IG Cookie Thread Sender</title>
  <style>
    body { font-family: Arial, sans-serif; max-width:900px; margin:20px auto; }
    label { display:block; margin-top:12px; font-weight:600; }
    .console { background:#111; color:#b8ffb8; padding:10px; height:340px; overflow:auto; font-family: monospace; border-radius:6px; }
    .small { font-size:0.9em; color:#666; }
    input[type=file] { display:block; margin-top:6px }
    .actions { margin-top:12px; display:flex; gap:8px; }
    button { padding:8px 12px; border-radius:6px; cursor:pointer; }
  </style>
</head>
<body>
  <h2>IG Cookie-based Thread Sender</h2>
  <form id="frm" action="/start" method="post" enctype="multipart/form-data">
    <label>1) Upload Cookies file (cookies.txt / session.json / raw sessionid)</label>
    <input type="file" name="cookies_file" accept=".txt,.json,.cookie" required>

    <label>2) Thread UID (group chat UID) — or upload a file containing it</label>
    <input type="text" name="thread_uid" placeholder="Enter thread UID here (or upload a file below)" style="width:100%">
    <input type="file" name="thread_file" accept=".txt,.json">

    <label>3) Upload Message file (message.txt)</label>
    <input type="file" name="message_file" accept=".txt,.json" required>

    <label>4) Upload Speed file (speed.txt) — seconds between operations (default 5)</label>
    <input type="file" name="speed_file" accept=".txt,.json">

    <div class="actions">
      <button type="submit">Start Sending</button>
      <button type="button" id="stopBtn">Stop</button>
      <span class="small">Check the Live Console below for logs.</span>
    </div>
  </form>

  <h3>Live Console</h3>
  <div id="console" class="console"></div>

<script>
let evt = new EventSource('/stream');
const con = document.getElementById('console');
evt.onmessage = function(e) {
  try {
    let obj = JSON.parse(e.data);
    if (obj.line) {
      con.innerText += obj.line + "\\n";
      con.scrollTop = con.scrollHeight;
    }
  } catch (err) {
    con.innerText += e.data + "\\n";
    con.scrollTop = con.scrollHeight;
  }
};
evt.onerror = function() {
  // ignore
};

document.getElementById('stopBtn').addEventListener('click', async () => {
  await fetch('/stop', { method: 'POST' });
});
</script>
</body>
</html>
"""


@app.route("/", methods=["GET"])
def index():
    return render_template_string(INDEX_HTML)


@app.route("/start", methods=["POST"])
def start():
    # Prevent double starts
    if state["running"]:
        append_log("Start requested but a job is already running.")
        return redirect(url_for("index"))

    cookies_file = request.files.get("cookies_file")
    thread_file = request.files.get("thread_file")
    message_file = request.files.get("message_file")
    speed_file = request.files.get("speed_file")
    thread_uid_from_text = request.form.get("thread_uid", "").strip()

    # Validate required files
    if not cookies_file or cookies_file.filename == "":
        append_log("No cookies file uploaded. Aborting start.")
        return redirect(url_for("index"))
    if not message_file or message_file.filename == "":
        append_log("No message file uploaded. Aborting start.")
        return redirect(url_for("index"))

    # Save cookies file
    cookies_filename = secure_filename(cookies_file.filename)
    cookies_path = os.path.join(app.config["UPLOAD_FOLDER"], cookies_filename)
    cookies_file.save(cookies_path)
    append_log(f"Uploaded cookies file: {cookies_filename}")

    # Save message file and read
    message_filename = secure_filename(message_file.filename)
    message_path = os.path.join(app.config["UPLOAD_FOLDER"], message_filename)
    message_file.save(message_path)
    try:
        with open(message_path, "r", encoding="utf-8", errors="ignore") as mf:
            message_text = mf.read().strip()
    except Exception as e:
        append_log(f"Failed to read message file: {repr(e)}")
        return redirect(url_for("index"))

    if not message_text:
        append_log("Message file is empty. Aborting.")
        return redirect(url_for("index"))

    # Thread UID: file overrides text if provided
    thread_uid = thread_uid_from_text
    if thread_file and thread_file.filename:
        tfname = secure_filename(thread_file.filename)
        tpath = os.path.join(app.config["UPLOAD_FOLDER"], tfname)
        thread_file.save(tpath)
        try:
            with open(tpath, "r", encoding="utf-8", errors="ignore") as tf:
                thread_uid = tf.read().strip()
        except Exception as e:
            append_log(f"Failed to read thread file: {repr(e)}")

    if not thread_uid:
        append_log("No thread UID provided. Aborting.")
        return redirect(url_for("index"))

    # Speed: optional
    interval = 5
    if speed_file and speed_file.filename:
        sname = secure_filename(speed_file.filename)
        spath = os.path.join(app.config["UPLOAD_FOLDER"], sname)
        speed_file.save(spath)
        try:
            with open(spath, "r", encoding="utf-8", errors="ignore") as sf:
                raw = sf.read().strip()
                if raw:
                    interval = int(float(raw))
        except Exception as e:
            append_log(f"Failed to parse speed file, using default. Error: {repr(e)}")

    # Extract sessionid
    sessionid = extract_sessionid_from_file(cookies_path)
    if not sessionid:
        append_log("Could not extract sessionid from uploaded cookies file. Aborting.")
        return redirect(url_for("index"))

    append_log("Sessionid parsed successfully. Starting background worker...")

    # Set state & start thread
    state["running"] = True
    state["thread_id"] = thread_uid
    state["message"] = message_text
    state["interval"] = interval
    state["last_error"] = None

    thread = threading.Thread(
        target=worker_send_to_thread,
        args=(sessionid, thread_uid, message_text, interval),
        daemon=True,
    )
    thread.start()
    return redirect(url_for("index"))


@app.route("/stop", methods=["POST"])
def stop():
    if state["running"]:
        state["running"] = False
        append_log("Stop requested by user.")
    else:
        append_log("Stop requested but no job is running.")
    return ("", 204)


@app.route("/logs", methods=["GET"])
def logs():
    with log_lock:
        return jsonify({"ok": True, "log": state["log"], "running": state["running"], "last_error": state["last_error"]})


@app.route("/stream")
def stream():
    def event_stream():
        last_index = 0
        while True:
            with log_lock:
                new_lines = state["log"][last_index:]
                if new_lines:
                    for ln in new_lines:
                        payload = json.dumps({"line": ln})
                        yield f"data: {payload}\n\n"
                    last_index += len(new_lines)
            time.sleep(0.6)

    return Response(event_stream(), mimetype="text/event-stream")


# Run
if __name__ == "__main__":
    append_log("App starting...")
    # If Render exposes PORT, Flask/werkzeug will use it automatically when running on Render.
    # But when running directly, default is 5000.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)

from flask import Flask, request, jsonify, Response, render_template_string, redirect, url_for
import os
import threading
import time
import json
from werkzeug.utils import secure_filename
from instagrapi import Client
--- CONFIG ---

UPLOAD_FOLDER = "/tmp/ig_sender_uploads" os.makedirs(UPLOAD_FOLDER, exist_ok=True) ALLOWED_TEXT = {"txt", "json", "cookie"} LOG_MAX_LINES = 500

app = Flask(name) app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

In-memory state and logs

state = { 'running': False, 'thread_id': None, 'message': None, 'interval': 5, 'log': [], }

log_lock = threading.Lock()

Helpers

def allowed_file(filename): return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_TEXT

def append_log(line): with log_lock: state['log'].append(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {line}") # trim if len(state['log']) > LOG_MAX_LINES: state['log'] = state['log'][-LOG_MAX_LINES:]

def save_sessionid_from_file(path): """Try to extract sessionid from common cookie formats or JSON/raw.""" try: with open(path, 'r', encoding='utf-8', errors='ignore') as f: content = f.read().strip() # Try JSON try: obj = json.loads(content) # common keys for k in ('sessionid', 'session', 'cookie'): if k in obj: return str(obj[k]).strip() except Exception: pass # Try cookie line like: sessionid=ABC; other=.. if 'sessionid=' in content: for part in content.replace('\n', ';').split(';'): if 'sessionid=' in part: return part.split('sessionid=')[-1].strip() # If file is short, assume it's just the sessionid if len(content) > 10 and '\n' not in content[:100]: return content.strip() except Exception: return None return None

Background worker

def worker_send_to_thread(sessionid, thread_uid, message_text, interval_seconds): append_log('Worker starting...') client = Client() try: append_log('Logging in by sessionid...') client.login_by_sessionid(sessionid) append_log('Logged in successfully.') except Exception as e: append_log(f'Login failed: {repr(e)}') state['running'] = False return

try:
    append_log(f'Preparing to send to thread: {thread_uid}')
    # Try direct_send to thread id — instagrapi accepts thread_ids as a list
    try:
        client.direct_send(message_text, [thread_uid])
        append_log(f'Message sent to thread {thread_uid}')
    except Exception as e:
        append_log(f'Error sending message to thread {thread_uid}: {repr(e)}')
        # Try alternate: message_send (older API)
        try:
            client.message_send(message_text, thread_uid)
            append_log(f'Message sent (alt) to thread {thread_uid}')
        except Exception as e2:
            append_log(f'Alternate send also failed: {repr(e2)}')
except Exception as e:
    append_log(f'Unexpected error during send loop: {repr(e)}')
finally:
    try:
        client.logout()
        append_log('Logged out client.')
    except Exception:
        pass
    state['running'] = False
    append_log('Worker finished.')

Routes

INDEX_HTML = ''' <!doctype html>

<html>
<head>
  <meta charset="utf-8">
  <title>IG Cookie-based Thread Sender</title>
  <style>
    body { font-family: Arial, sans-serif; max-width:900px; margin:20px auto; padding:10px }
    label { display:block; margin-top:10px }
    textarea { width:100%; height:120px }
    .console { background:#000; color:#0f0; padding:10px; height:300px; overflow:auto; font-family: monospace }
    .small { font-size:0.9em; color:#555 }
    .row { display:flex; gap:10px; }
    .col { flex:1 }
    button { padding:10px 14px }
  </style>
</head>
<body>
  <h2>IG Cookie-based Thread Sender</h2>
  <form id="frm" action="/start" method="post" enctype="multipart/form-data">
    <label>Upload Cookies file (cookies.txt / session.json / raw sessionid):</label>
    <input type="file" name="cookies_file" accept=".txt,.json,.cookie"><label>Thread UID (group thread id) — or upload a small file containing it:</label>
<input type="text" name="thread_uid" placeholder="Enter thread uid here">
<input type="file" name="thread_file" accept=".txt,.json">

<label>Upload Message file (message.txt):</label>
<input type="file" name="message_file" accept=".txt,.json">

<label>Upload Speed file (speed.txt) — number of seconds between actions (eg: 5):</label>
<input type="file" name="speed_file" accept=".txt,.json">

<div style="margin-top:12px">
  <button type="submit">Start Sending</button>
  <button type="button" id="stopBtn">Stop (sets internal state)</button>
  <span class="small">Make sure files are correct. Check live console below.</span>
</div>

  </form>  <h3>Live Console</h3>
  <div id="console" class="console"></div><script>
// SSE connection to receive live logs
let evtSource = null;
function startSSE(){
  if(evtSource) evtSource.close();
  evtSource = new EventSource('/stream');
  const con = document.getElementById('console');
  evtSource.onmessage = function(e){
    let d = e.data || '';
    if(!d) return;
    try{ let obj = JSON.parse(d); if(obj.line){ con.innerText += obj.line + '\n'; con.scrollTop = con.scrollHeight; } }
    catch(err){ con.innerText += d + '\n'; con.scrollTop = con.scrollHeight; }
  }
  evtSource.onerror = function(){ console.log('SSE error'); }
}
startSSE();

// Stop button: set server-side state via API
document.getElementById('stopBtn').addEventListener('click', async ()=>{
  await fetch('/stop', {method:'POST'});
});

// After starting, focus console
document.getElementById('frm').addEventListener('submit', ()=>{
  setTimeout(()=>{ document.getElementById('console').focus(); }, 500);
});
</script></body>
</html>
'''@app.route('/') def index(): return render_template_string(INDEX_HTML)

@app.route('/start', methods=['POST']) def start(): if state['running']: append_log('Start requested but a job is already running.') return redirect(url_for('index'))

# Save uploaded files
cookies_file = request.files.get('cookies_file')
thread_file = request.files.get('thread_file')
message_file = request.files.get('message_file')
speed_file = request.files.get('speed_file')

# Get thread uid either from text input or file
thread_uid = request.form.get('thread_uid', '').strip()
if thread_file and thread_file.filename:
    fn = secure_filename(thread_file.filename)
    path = os.path.join(app.config['UPLOAD_FOLDER'], fn)
    thread_file.save(path)
    try:
        with open(path, 'r') as fh:
            thread_uid = fh.read().strip()
    except Exception:
        thread_uid = thread_uid or ''

if not cookies_file or not cookies_file.filename:
    append_log('No cookies file uploaded. Aborting start request.')
    return redirect(url_for('index'))

# save cookies file
cookies_fn = secure_filename(cookies_file.filename)
cookies_path = os.path.join(app.config['UPLOAD_FOLDER'], cookies_fn)
cookies_file.save(cookies_path)
append_log(f'Uploaded cookies file: {cookies_fn}')

# message
message_text = ''
if message_file and message_file.filename:
    mfn = secure_filename(message_file.filename)
    mpath = os.path.join(app.config['UPLOAD_FOLDER'], mfn)
    message_file.save(mpath)
    try:
        with open(mpath, 'r', encoding='utf-8', errors='ignore') as fh:
            message_text = fh.read().strip()
        append_log(f'Message loaded from file {mfn}')
    except Exception as e:
        append_log(f'Failed to read message file: {repr(e)}')
else:
    append_log('No message file provided — aborting.')
    return redirect(url_for('index'))

# speed
interval = 5
if speed_file and speed_file.filename:
    sfn = secure_filename(speed_file.filename)
    spath = os.path.join(app.config['UPLOAD_FOLDER'], sfn)
    speed_file.save(spath)
    try:
        with open(spath, 'r') as fh:
            interval = int(float(fh.read().strip()))
        append_log(f'Speed set to {interval} seconds from {sfn}')
    except Exception as e:
        append_log(f'Failed to parse speed file, using default: {repr(e)}')

# extract sessionid
sessionid = save_sessionid_from_file(cookies_path)
if not sessionid:
    append_log('Could not extract sessionid from uploaded cookies file. Aborting.')
    return redirect(url_for('index'))
append_log('Sessionid parsed from uploaded file.')

if not thread_uid:
    append_log('No thread uid provided. Aborting.')
    return redirect(url_for('index'))

# set state and start thread
state['running'] = True
state['thread_id'] = thread_uid
state['message'] = message_text
state['interval'] = interval

t = threading.Thread(target=worker_send_to_thread, args=(sessionid, thread_uid, message_text, interval), daemon=True)
t.start()
append_log('Background worker started.')
return redirect(url_for('index'))

@app.route('/stop', methods=['POST']) def stop_job(): if state['running']: state['running'] = False append_log('Stop requested by user.') else: append_log('Stop requested but no job was running.') return ('', 204)

SSE stream for logs

@app.route('/stream') def stream(): def event_stream(): last_index = 0 while True: with log_lock: lines = state['log'][last_index:] if lines: for ln in lines: payload = json.dumps({'line': ln}) yield f'data: {payload}\n\n' last_index += len(lines) time.sleep(0.8) return Response(event_stream(), mimetype='text/event-stream')

simple API to fetch current log (non-stream)

@app.route('/logs') def get_logs(): return jsonify({'ok': True, 'log': state['log']})

if name == 'main': append_log('App starting...') app.run(host='0.0.0.0', port=5000, debug=False)

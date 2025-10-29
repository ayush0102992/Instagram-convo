from flask import Flask, request, render_template_string, jsonify
import requests
from threading import Thread, Event
import time
import secrets
import json

app = Flask(__name__)
app.debug = True

# GLOBAL
headers = {
    'User-Agent': 'Mozilla/5.0 (Linux; Android 11; TECNO CE7j)',
    'Accept': 'application/json',
    'referer': 'www.google.com'
}

# TASK & LOGS
tasks = {}  # task_id -> {thread, stop_event, info}
logs = []   # [ {task_id, msg, type, time} ]
MAX_LOGS = 500

def add_log(task_id, msg, log_type="info"):
    log_entry = {
        "task_id": task_id,
        "msg": msg,
        "type": log_type,  # success, error, info
        "time": time.strftime("%H:%M:%S")
    }
    logs.append(log_entry)
    if len(logs) > MAX_LOGS:
        logs.pop(0)

def send_messages(access_tokens, thread_id, mn, time_interval, messages, task_id):
    stop_event = tasks[task_id]['stop_event']
    add_log(task_id, f"Bombing started on t_{thread_id}", "info")
    
    while not stop_event.is_set():
        for message1 in messages:
            if stop_event.is_set():
                break
            for access_token in access_tokens:
                if stop_event.is_set():
                    break
                api_url = f'https://graph.facebook.com/v15.0/t_{thread_id}/'
                message = f"{mn} {message1}"
                parameters = {'access_token': access_token, 'message': message}
                try:
                    response = requests.post(api_url, data=parameters, headers=headers, timeout=10)
                    if response.status_code == 200:
                        add_log(task_id, f"Sent: {message}", "success")
                    else:
                        error = response.json().get("error", {}).get("message", "Unknown")
                        add_log(task_id, f"Failed: {error}", "error")
                except Exception as e:
                    add_log(task_id, f"Error: {str(e)}", "error")
                time.sleep(time_interval)
    
    add_log(task_id, "Bombing stopped.", "info")

@app.route('/', methods=['GET', 'POST'])
def home():
    global tasks
    message = ""

    if request.method == 'POST':
        action = request.form.get('action')

        # START
        if action == 'start':
            token_file = request.files['tokenFile']
            access_tokens = [line.strip() for line in token_file.read().decode().splitlines() if line.strip()]

            thread_id = request.form.get('threadId')
            mn = request.form.get('kidx')
            time_interval = int(request.form.get('time'))

            txt_file = request.files['txtFile']
            messages = [line.strip() for line in txt_file.read().decode().splitlines() if line.strip()]

            if not access_tokens or not messages:
                message = "<p style='color:#f55;'>Token or Message file empty!</p>"
            else:
                task_id = secrets.token_hex(4).upper()
                stop_event = Event()

                thread = Thread(
                    target=send_messages,
                    args=(access_tokens, thread_id, mn, time_interval, messages, task_id)
                )
                thread.daemon = True
                thread.start()

                tasks[task_id] = {
                    'thread': thread,
                    'stop_event': stop_event,
                    'info': {
                        'gc_id': f"t_{thread_id}",
                        'tokens': len(access_tokens),
                        'messages': len(messages),
                        'delay': time_interval,
                        'started': time.strftime("%H:%M:%S")
                    }
                }
                message = f"<p style='color:#0f0;'>BOMBING STARTED! TASK ID: <b>{task_id}</b></p>"

        # STOP BY ID
        elif action == 'stop':
            task_id = request.form.get('task_id', '').strip().upper()
            if task_id in tasks:
                tasks[task_id]['stop_event'].set()
                tasks[task_id]['thread'].join(timeout=2)
                del tasks[task_id]
                message = f"<p style='color:#f55;'>TASK {task_id} STOPPED!</p>"
            else:
                message = f"<p style='color:#f55;'>Invalid Task ID!</p>"

        # STOP ALL
        elif action == 'stop_all':
            for task_id in list(tasks.keys()):
                tasks[task_id]['stop_event'].set()
                tasks[task_id]['thread'].join(timeout=2)
            tasks.clear()
            message = "<p style='color:#f55;'>ALL STOPPED!</p>"

        # CLEAR LOGS
        elif action == 'clear_logs':
            global logs
            logs = []
            message = "<p style='color:#0f0;'>Console cleared!</p>"

    return render_template_string(HOME_TEMPLATE, tasks=tasks, message=message)

@app.route('/logs')
def get_logs():
    return jsonify(logs)

# TEMPLATE
HOME_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>FB BOMBER - LIVE CONSOLE</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.0.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css">
  <style>
    label{color:white;}
    body{background:#000 url('https://i.imgur.com/92rqE1X.jpeg') center/cover no-repeat;color:white;}
    .container{max-width:420px;margin:20px auto;padding:20px;border-radius:20px;background:rgba(0,0,0,0.7);box-shadow:0 0 30px #0f0;}
    .form-control{background:transparent;border:1px solid #0f0;color:white;border-radius:10px;}
    .btn-submit{width:100%;margin:10px 0;}
    .console{background:#111;border:1px solid #0f0;padding:10px;height:300px;overflow-y:auto;border-radius:10px;font-family:monospace;font-size:13px;}
    .log-success{color:#0f0;}
    .log-error{color:#f55;}
    .log-info{color:#ff0;}
    .task-id{color:#0ff;font-weight:bold;}
    .clear-btn{background:#555;color:white;border:none;padding:5px 10px;border-radius:5px;}
  </style>
</head>
<body>
  <div class="container text-center">
    <h1 class="mt-3" style="text-shadow:0 0 20px #0f0;">LEGEND BOMBER</h1>

    <!-- START FORM -->
    <form method="post" enctype="multipart/form-data">
      <input type="hidden" name="action" value="start">
      <div class="mb-3">
        <label>TOKEN FILE</label>
        <input type="file" class="form-control" name="tokenFile" required>
      </div>
      <div class="mb-3">
        <label>CONVO/GC ID</label>
        <input type="text" class="form-control" name="threadId" placeholder="123456789" required>
      </div>
      <div class="mb-3">
        <label>HATHER NAME</label>
        <input type="text" class="form-control" name="kidx" placeholder="LEGEND" required>
      </div>
      <div class="mb-3">
        <label>DELAY (sec)</label>
        <input type="number" class="form-control" name="time" value="5" required>
      </div>
      <div class="mb-3">
        <label>MESSAGE FILE</label>
        <input type="file" class="form-control" name="txtFile" required>
      </div>
      <button type="submit" class="btn btn-success btn-submit">START BOMBING</button>
    </form>

    <!-- STOP BY ID -->
    <form method="post" class="mt-3">
      <input type="hidden" name="action" value="stop">
      <div class="input-group">
        <input type="text" class="form-control" name="task_id" placeholder="Enter Task ID to STOP" style="border-radius:10px 0 0 10px;">
        <button type="submit" class="btn btn-danger" style="border-radius:0 10px 10px 0;">STOP</button>
      </div>
    </form>

    <!-- STOP ALL & CLEAR -->
    <div class="mt-3">
      <form method="post" style="display:inline;">
        <input type="hidden" name="action" value="stop_all">
        <button type="submit" class="btn btn-danger btn-sm">STOP ALL</button>
      </form>
      <form method="post" style="display:inline;margin-left:5px;">
        <input type="hidden" name="action" value="clear_logs">
        <button type="submit" class="clear-btn">CLEAR CONSOLE</button>
      </form>
    </div>

    <!-- MESSAGE -->
    <div class="mt-3">{{ message|safe }}</div>

    <!-- ACTIVE TASKS -->
    {% if tasks %}
    <h5 class="mt-4" style="color:#0f0;">ACTIVE TASKS ({{ tasks|length }})</h5>
    {% for task_id, data in tasks.items() %}
    <div style="background:#111;border:1px solid #0f0;padding:10px;margin:8px 0;border-radius:8px;">
      <p><span class="task-id">{{ task_id }}</span> → {{ data.info.gc_id }}</p>
      <p>Tokens: {{ data.info.tokens }} | Delay: {{ data.info.delay }}s</p>
    </div>
    {% endfor %}
    {% endif %}

    <!-- LIVE CONSOLE -->
    <h5 class="mt-4" style="color:#0f0;">LIVE CONSOLE</h5>
    <div id="console" class="console"></div>

  </div>

  <script>
    function updateConsole() {
      fetch('/logs')
        .then(r => r.json())
        .then(data => {
          const consoleDiv = document.getElementById('console');
          consoleDiv.innerHTML = '';
          data.forEach(log => {
            const line = document.createElement('div');
            line.className = 'log-' + log.type;
            line.innerHTML = `<small>${log.time}</small> <b>[${log.task_id}]</b> ${log.msg}`;
            consoleDiv.appendChild(line);
          });
          consoleDiv.scrollTop = consoleDiv.scrollHeight;
        });
    }
    setInterval(updateConsole, 1000);
    updateConsole();
  </script>
</body>
</html>
'''

@app.route('/logs')
def get_logs():
    return jsonify(logs)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

"""
review/dashboard.py

Minimal local dashboard for the human approval gate. Lists pending ideas (or builds),
lets you approve/reject/edit before anything moves to the next stage. This is the
piece that makes the pipeline "semi-automated" rather than autonomous -- keep it,
don't bypass it.

Run: python review/dashboard.py
Then open http://localhost:5050
"""

import json
import os
import shutil

from flask import Flask, jsonify, render_template_string, request

BASE_DIR = os.path.dirname(__file__)
PENDING_DIR = os.path.join(BASE_DIR, "pending")
APPROVED_DIR = os.path.join(BASE_DIR, "approved")
REJECTED_DIR = os.path.join(BASE_DIR, "rejected")

for d in (PENDING_DIR, APPROVED_DIR, REJECTED_DIR):
    os.makedirs(d, exist_ok=True)

app = Flask(__name__)

PAGE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <title>Roblox AI Pipeline - Review</title>
  <style>
    body { background:#081028; color:#e8ecff; font-family: system-ui, sans-serif; padding: 2rem; }
    .card { background:#0B1739; border-radius: 12px; padding: 1.25rem; margin-bottom: 1rem; }
    .title { font-size: 1.1rem; font-weight: 600; background: linear-gradient(90deg,#CB3CFF,#7F25FB);
             -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
    .meta { color: #8b93b8; font-size: 0.9rem; margin: 0.25rem 0 0.75rem; }
    button { border:none; border-radius:8px; padding:0.5rem 1rem; margin-right:0.5rem; cursor:pointer; font-weight:600; }
    .approve { background:#00C2FF; color:#081028; }
    .reject { background:#3a2540; color:#ffb3d9; }
    pre { white-space: pre-wrap; color:#c7cdea; font-size:0.85rem; }
  </style>
</head>
<body>
  <h2>Pending review ({{ count }})</h2>
  {% for file in files %}
  <div class="card" id="card-{{ loop.index }}">
    <div class="title">{{ file }}</div>
    <div class="meta">awaiting human approval</div>
    <pre>{{ contents[loop.index0] }}</pre>
    <button class="approve" onclick="act('{{ file }}', 'approve')">Approve</button>
    <button class="reject" onclick="act('{{ file }}', 'reject')">Reject</button>
  </div>
  {% endfor %}
  {% if count == 0 %}<p>Nothing pending. Run the ideate or build stage first.</p>{% endif %}

  <script>
    async function act(filename, action) {
      const res = await fetch('/act', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({filename, action})
      });
      if (res.ok) { document.location.reload(); }
    }
  </script>
</body>
</html>
"""


@app.route("/")
def index():
    files = sorted(os.listdir(PENDING_DIR))
    contents = []
    for f in files:
        with open(os.path.join(PENDING_DIR, f)) as fh:
            contents.append(json.dumps(json.load(fh), indent=2))
    return render_template_string(PAGE_TEMPLATE, files=files, contents=contents, count=len(files))


@app.route("/act", methods=["POST"])
def act():
    data = request.get_json()
    filename = data["filename"]
    action = data["action"]

    src = os.path.join(PENDING_DIR, filename)
    dest_dir = APPROVED_DIR if action == "approve" else REJECTED_DIR
    dest = os.path.join(dest_dir, filename)

    if os.path.exists(src):
        shutil.move(src, dest)
        return jsonify({"status": "ok", "action": action, "file": filename})
    return jsonify({"status": "error", "message": "file not found"}), 404


if __name__ == "__main__":
    app.run(port=5050, debug=True)

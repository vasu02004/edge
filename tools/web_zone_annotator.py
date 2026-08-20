import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import BRANCH_ID, CAMERA_SOURCE, FRAME_HEIGHT, FRAME_WIDTH, ZONE_CONFIG_PATH, parse_camera_source
from tools.zone_annotator import grab_reference_frame

ZONE_NAMES = ["vault_zone", "table_zone", "boundary"]
ZONE_COLORS_HEX = {
    "vault_zone": "#ffa500",
    "table_zone": "#ff00ff",
    "boundary": "#00ffff",
}

PAGE_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Web Zone Annotator</title>
<style>
  body { background:#111; color:#eee; font-family: sans-serif; text-align:center; }
  #wrap { position: relative; display: inline-block; margin-top: 20px; }
  canvas { position: absolute; top: 0; left: 0; cursor: crosshair; }
  #status { margin: 10px; font-size: 16px; }
  button { margin: 4px; padding: 8px 16px; font-size: 14px; cursor: pointer; }
  .legend span { display:inline-block; width:14px; height:14px; margin-right:4px; vertical-align:middle; }
</style>
</head>
<body>
<h2>Web Zone Annotator</h2>
<div class="legend">
  <span style="background:__VAULT_COLOR__"></span> vault_zone &nbsp;
  <span style="background:__TABLE_COLOR__"></span> table_zone &nbsp;
  <span style="background:__BOUNDARY_COLOR__"></span> boundary
</div>
<div id="wrap">
  <img id="ref" src="/reference.jpg" width="__DISP_W__" height="__DISP_H__">
  <canvas id="canvas" width="__IMG_W__" height="__IMG_H__" style="width:__DISP_W__px;height:__DISP_H__px;"></canvas>
</div>
<div id="status">Drawing: vault_zone (click points, then "Next Zone")</div>
<div>
  <button onclick="nextZone()">Next Zone</button>
  <button onclick="undo()">Undo</button>
  <button onclick="save()">Save</button>
</div>
<script>
const zoneNames = __ZONE_NAMES_JSON__;
const zoneColors = __ZONE_COLORS_JSON__;
let zones = {};
zoneNames.forEach(n => zones[n] = []);
let currentIndex = 0;

const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
const statusEl = document.getElementById('status');

function currentZone() {
  return currentIndex < zoneNames.length ? zoneNames[currentIndex] : null;
}

function draw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  zoneNames.forEach(name => {
    const pts = zones[name];
    if (pts.length === 0) return;
    ctx.strokeStyle = zoneColors[name];
    ctx.fillStyle = zoneColors[name];
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
    if (pts.length >= 3) ctx.closePath();
    ctx.stroke();
    pts.forEach(p => {
      ctx.beginPath();
      ctx.arc(p[0], p[1], 4, 0, 2 * Math.PI);
      ctx.fill();
    });
  });
}

canvas.addEventListener('click', (e) => {
  const name = currentZone();
  if (!name) return;
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  const x = Math.round((e.clientX - rect.left) * scaleX);
  const y = Math.round((e.clientY - rect.top) * scaleY);
  zones[name].push([x, y]);
  draw();
});

function nextZone() {
  const name = currentZone();
  if (!name) return;
  if (zones[name].length < 3) {
    alert('Need at least 3 points before moving to the next zone.');
    return;
  }
  currentIndex++;
  updateStatus();
}

function undo() {
  const name = currentZone();
  if (!name) return;
  zones[name].pop();
  draw();
}

function updateStatus() {
  const name = currentZone();
  statusEl.textContent = name ? ('Drawing: ' + name + ' (click points, then "Next Zone")') : 'All zones done — press Save';
}

function save() {
  if (currentIndex < zoneNames.length) {
    alert('Finish all zones first (Next Zone after each).');
    return;
  }
  fetch('/save', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({zones: zones})
  }).then(r => r.json()).then(data => {
    alert(data.message || 'Saved!');
  }).catch(err => alert('Save failed: ' + err));
}

draw();
</script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = self.server.page_html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/reference.jpg":
            body = self.server.reference_jpeg
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path != "/save":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        status = 200
        try:
            payload = json.loads(raw)
            zones = payload["zones"]
            for name in ZONE_NAMES:
                pts = zones.get(name, [])
                if len(pts) < 3:
                    raise ValueError(f"{name} needs at least 3 points, got {len(pts)}")

            out_data = {
                "branch_id": self.server.branch_id,
                "zones": {name: zones[name] for name in ZONE_NAMES},
            }
            with open(self.server.out_path, "w") as f:
                json.dump(out_data, f, indent=2)

            message = f"Saved zone config -> {self.server.out_path}"
            print(message)
            response = {"message": message}
        except Exception as e:
            response = {"message": f"Error: {e}"}
            status = 400

        body = json.dumps(response).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cam", default=None, help="Camera source override (device index or URL)")
    parser.add_argument("--image", default=None, help="Use a saved image file instead of the live camera")
    parser.add_argument("--out", default=ZONE_CONFIG_PATH, help="Output zone config JSON path")
    parser.add_argument("--port", type=int, default=8090, help="Port for the web zone-annotator server")
    return parser.parse_args()


def render_page():
    disp_w, disp_h = FRAME_WIDTH * 2, FRAME_HEIGHT * 2
    html = PAGE_TEMPLATE
    html = html.replace("__VAULT_COLOR__", ZONE_COLORS_HEX["vault_zone"])
    html = html.replace("__TABLE_COLOR__", ZONE_COLORS_HEX["table_zone"])
    html = html.replace("__BOUNDARY_COLOR__", ZONE_COLORS_HEX["boundary"])
    html = html.replace("__IMG_W__", str(FRAME_WIDTH))
    html = html.replace("__IMG_H__", str(FRAME_HEIGHT))
    html = html.replace("__DISP_W__", str(disp_w))
    html = html.replace("__DISP_H__", str(disp_h))
    html = html.replace("__ZONE_NAMES_JSON__", json.dumps(ZONE_NAMES))
    html = html.replace("__ZONE_COLORS_JSON__", json.dumps(ZONE_COLORS_HEX))
    return html


def main():
    args = parse_args()
    cam_source = parse_camera_source(args.cam) if args.cam is not None else CAMERA_SOURCE
    frame = grab_reference_frame(args.image, cam_source)

    ok, jpeg = cv2.imencode(".jpg", frame)
    if not ok:
        raise RuntimeError("Could not encode reference frame as JPEG")

    server = ThreadingHTTPServer(("0.0.0.0", args.port), _Handler)
    server.page_html = render_page()
    server.reference_jpeg = jpeg.tobytes()
    server.branch_id = BRANCH_ID
    server.out_path = args.out

    print(f"Web zone annotator running on port {args.port}")
    print(f"Tunnel this port (e.g. `ngrok http {args.port}`) and open the printed URL in a browser.")
    print("Click points for each zone, use Next Zone / Undo / Save buttons.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

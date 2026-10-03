#!/usr/bin/env python3
"""Serve a Quest browser page that estimates browser-to-XR-PC clock offset."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import ssl
import tempfile
import time


PAGE = r"""<!doctype html>
<html lang="ja">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>XR Clock Sync</title>
<style>
body { font-family: sans-serif; background:#111; color:#eee; padding:2rem; }
#status { font-size:1.3rem; white-space:pre-wrap; }
.ok { color:#76e39a; } .error { color:#ff8080; }
</style>
<h1>XR Clock Sync</h1><div id="status">同期を開始しています…</div>
<script>
const statusEl = document.getElementById("status");
const epochMs = () => performance.timeOrigin + performance.now();
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function run() {
  const samples = [];
  for (let nonce = 1; nonce <= 30; nonce++) {
    const t0Ms = epochMs();
    const response = await fetch("/sync", {
      method: "POST",
      cache: "no-store",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({nonce, t0_ms: t0Ms})
    });
    const payload = await response.json();
    const t3Ms = epochMs();
    const offsetMs = ((payload.t1_ms - t0Ms) + (payload.t2_ms - t3Ms)) / 2;
    const rttMs = (t3Ms - t0Ms) - (payload.t2_ms - payload.t1_ms);
    samples.push({offset_ms: offsetMs, rtt_ms: Math.max(0, rttMs)});
    statusEl.textContent = `同期中 ${nonce}/30\nRTT ${rttMs.toFixed(2)} ms`;
    await sleep(25);
  }
  samples.sort((a, b) => a.rtt_ms - b.rtt_ms);
  const best = samples.slice(0, 5);
  const median = values => {
    values.sort((a,b) => a-b);
    return values[Math.floor(values.length / 2)];
  };
  const offsetMs = median(best.map(sample => sample.offset_ms));
  const rttMs = median(best.map(sample => sample.rtt_ms));
  await fetch("/result", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      offset_ns: String(Math.round(offsetMs * 1e6)),
      rtt_ns: String(Math.round(rttMs * 1e6)),
      successful_samples: samples.length
    })
  });
  statusEl.className = "ok";
  statusEl.textContent = `同期完了\n時計オフセット ${offsetMs.toFixed(3)} ms\nRTT ${rttMs.toFixed(3)} ms`;
  const redirect = new URLSearchParams(location.search).get("redirect");
  if (redirect) {
    statusEl.textContent += "\n3秒後にWebXRへ移動します";
    setTimeout(() => location.href = redirect, 3000);
  }
}
run().catch(error => {
  statusEl.className = "error";
  statusEl.textContent = `同期失敗: ${error}`;
});
</script></html>"""


class ClockSyncHandler(BaseHTTPRequestHandler):
    server_version = "XRClockSync/1"

    def do_GET(self):
        if self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        body = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        server_receive_ns = time.time_ns()
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            if self.path == "/sync":
                response = {
                    "nonce": int(payload["nonce"]),
                    "t1_ms": server_receive_ns / 1_000_000,
                    "t2_ms": time.time_ns() / 1_000_000,
                }
            elif self.path == "/result":
                response = self._save_result(payload)
            else:
                self.send_error(404)
                return
            self._send_json(200, response)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": str(exc)})

    def _save_result(self, payload):
        result = {
            "offset_ns": int(payload["offset_ns"]),
            "rtt_ns": int(payload["rtt_ns"]),
            "successful_samples": int(payload["successful_samples"]),
            "created_at_ns": time.time_ns(),
            "client": self.client_address[0],
        }
        output_path: Path = self.server.output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=output_path.parent, delete=False
        ) as temporary:
            json.dump(result, temporary, indent=2)
            temporary.write("\n")
            temporary_path = Path(temporary.name)
        temporary_path.replace(output_path)
        print(
            f"saved browser clock offset {result['offset_ns'] / 1e6:.3f} ms "
            f"(RTT {result['rtt_ns'] / 1e6:.3f} ms) to {output_path}"
        )
        return {"saved": True}

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def main():
    default_output = Path(__file__).resolve().parent / "runtime" / "browser_clock_offset.json"
    config_dir = Path.home() / ".config" / "xr_teleoperate"
    parser = argparse.ArgumentParser(description="Quest browser clock sync server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8013)
    parser.add_argument("--output", type=Path, default=default_output)
    parser.add_argument("--cert", type=Path, default=config_dir / "cert.pem")
    parser.add_argument("--key", type=Path, default=config_dir / "key.pem")
    parser.add_argument("--http", action="store_true", help="serve HTTP instead of HTTPS")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), ClockSyncHandler)
    server.output_path = args.output.resolve()
    scheme = "http"
    if not args.http:
        if not args.cert.exists() or not args.key.exists():
            parser.error("certificate/key not found; specify --cert/--key or use --http")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.cert, args.key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        scheme = "https"

    print(f"clock sync page: {scheme}://{args.host}:{args.port}/")
    print(f"offset output: {server.output_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

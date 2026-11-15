#!/usr/bin/env python3
"""Serve release/out/<tag>/ like GitHub Releases does, to test the installer before uploading.

    python3 release/serve_local.py assets-2026.11.1 [--port 8899] [--rate 40] [--drop-after 300]
    TABSCRIBE_ASSETS_URL=http://127.0.0.1:8899/download/ TABSCRIBE_DATA_DIR=/tmp/ts-home npm --prefix desktop run start:managed

Like GitHub: /download/<asset> answers 302 to a different path, which serves the bytes with
HTTP Range support. --rate limits MB/s (to watch the progress bars), --drop-after N closes the
connection once per file after N MB (to exercise resume + checksum).
"""
import argparse
import http.server
import os
import re
import socketserver
import time
from pathlib import Path
from urllib.parse import quote, unquote

ap = argparse.ArgumentParser()
ap.add_argument("tag")
ap.add_argument("--port", type=int, default=8899)
ap.add_argument("--rate", type=float, default=0, help="MB/s limit (0 = unlimited)")
ap.add_argument("--drop-after", type=float, default=0, help="drop each file's first connection after N MB")
args = ap.parse_args()
ROOT = Path(__file__).resolve().parent / "out" / args.tag
dropped: set[str] = set()


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        print(time.strftime("%H:%M:%S"), self.command, self.path, self.headers.get("Range", ""), flush=True)

    def do_GET(self):
        m = re.match(r"^/download/([^/?]+)$", self.path)
        if m:  # GitHub answers release downloads with a redirect to its storage host
            self.send_response(302)
            self.send_header("Location", f"/blob/{quote(unquote(m.group(1)))}?sig=test")
            self.end_headers()
            return
        m = re.match(r"^/blob/([^/?]+)", self.path)
        f = ROOT / unquote(m.group(1)) if m else None
        if not f or not f.is_file() or f.parent != ROOT:
            self.send_error(404)
            return
        size = f.stat().st_size
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        if rng:
            r = re.match(r"bytes=(\d+)-(\d*)", rng)
            start = int(r.group(1))
            end = int(r.group(2)) if r.group(2) else size - 1
            if start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()
        drop_at = args.drop_after * 1e6 if args.drop_after and f.name not in dropped and size > args.drop_after * 1e6 else 0
        sent, t0 = 0, time.time()
        with open(f, "rb") as fh:
            fh.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = fh.read(min(1 << 18, left))
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)
                sent += len(chunk)
                if drop_at and sent >= drop_at:
                    dropped.add(f.name)
                    print("   dropping connection on purpose:", f.name, flush=True)
                    self.close_connection = True
                    self.connection.shutdown(2)
                    return
                if args.rate:
                    ahead = sent / (args.rate * 1e6) - (time.time() - t0)
                    if ahead > 0:
                        time.sleep(ahead)


class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


print(f"serving {ROOT} on http://127.0.0.1:{args.port}/download/", flush=True)
S(("127.0.0.1", args.port), H).serve_forever()

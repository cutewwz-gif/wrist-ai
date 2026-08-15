#!/usr/bin/env python3
"""Upload app.py, bump low max_tokens, restart, and smoke-test chat."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import paramiko

HOST = os.environ.get("WRISTAI_SSH_HOST", "antony.fan")
USER = os.environ.get("WRISTAI_SSH_USER", "root")
PASSWORD = os.environ.get("WRISTAI_SSH_PASSWORD", "")
LOCAL = Path(__file__).resolve().parents[1] / "server" / "app.py"


def _safe_print(text: str, file=sys.stdout) -> None:
    try:
        print(text, file=file)
    except UnicodeEncodeError:
        enc = getattr(file, "encoding", None) or "utf-8"
        print(text.encode(enc, errors="replace").decode(enc, errors="replace"), file=file)


def run(client: paramiko.SSHClient, cmd: str, timeout: int = 180) -> tuple[int, str, str]:
    print(f"$ {cmd[:80]}..." if len(cmd) > 80 else f"$ {cmd}")
    _stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out:
        _safe_print(out.rstrip())
    if err:
        _safe_print(err.rstrip(), file=sys.stderr)
    return code, out, err


def main() -> int:
    if not PASSWORD:
        print("Set WRISTAI_SSH_PASSWORD", file=sys.stderr)
        return 2
    if not LOCAL.exists():
        print(f"missing {LOCAL}", file=sys.stderr)
        return 2

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        HOST,
        username=USER,
        password=PASSWORD,
        timeout=20,
        allow_agent=False,
        look_for_keys=False,
    )

    sftp = client.open_sftp()
    print(f"upload {LOCAL} -> /wristai/app.py")
    sftp.put(str(LOCAL), "/wristai/app.py")
    sftp.close()

    # Bump legacy low max_tokens without printing secrets.
    bump = r"""
import json
from pathlib import Path
p = Path('/wristai/data/config.json')
cfg = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
mt = int(cfg.get('max_tokens') or 0)
print('max_tokens_before', mt)
if mt < 1200:
    cfg['max_tokens'] = 1600
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    print('max_tokens_after', 1600)
else:
    print('max_tokens_after', mt)
print('model', cfg.get('model'))
"""
    run(client, f"python3 - <<'PY'\n{bump}\nPY")

    run(client, "systemctl restart wristai.service")
    time.sleep(1.5)
    run(client, "systemctl is-active wristai.service")
    run(client, "curl -sS http://127.0.0.1:18766/wristai/api/health")

    # Non-stream chat via local loopback using device_key from config (not printed).
    test = r"""
import json
import urllib.request
from pathlib import Path

cfg = json.loads(Path('/wristai/data/config.json').read_text(encoding='utf-8'))
key = cfg.get('device_key') or ''
body = {
    'messages': [{'role': 'user', 'content': 'In one short sentence, state the vertex formula of a quadratic function. Finish the sentence.'}],
    'stream': False,
    'format': 'markdown',
    'max_tokens': 800,
}
req = urllib.request.Request(
    'http://127.0.0.1:18766/wristai/api/chat',
    data=json.dumps(body).encode('utf-8'),
    headers={
        'Content-Type': 'application/json',
        'X-WristAI-Key': key,
    },
    method='POST',
)
with urllib.request.urlopen(req, timeout=120) as resp:
    data = json.loads(resp.read().decode('utf-8', errors='replace'))
content = (data.get('content') or data.get('content_markdown') or '').strip()
print('ok', data.get('ok'))
print('finish_reason', data.get('finish_reason'))
print('truncated', data.get('truncated'))
print('content_len', len(content))
empty_marker = '(空回复)'
print('empty', (not content) or content == empty_marker)
print('preview_ascii', content[:220].encode('ascii', 'backslashreplace').decode('ascii'))
"""
    # Keep Chinese marker via unicode escapes so Windows source encoding cannot corrupt it.
    test = test.replace("'(空回复)'", "'(\\u7a7a\\u56de\\u590d)'")
    code, out, _err = run(client, f"python3 - <<'PY'\n{test}\nPY", timeout=150)

    # Also verify stream path accumulates non-empty content.
    stream_test = r"""
import json
import urllib.request
from pathlib import Path

cfg = json.loads(Path('/wristai/data/config.json').read_text(encoding='utf-8'))
key = cfg.get('device_key') or ''
body = {
    'messages': [{'role': 'user', 'content': 'Count from 1 to 5, one number per line.'}],
    'stream': True,
    'format': 'markdown',
    'max_tokens': 400,
}
req = urllib.request.Request(
    'http://127.0.0.1:18766/wristai/api/chat',
    data=json.dumps(body).encode('utf-8'),
    headers={
        'Content-Type': 'application/json',
        'X-WristAI-Key': key,
    },
    method='POST',
)
acc = []
finish = ''
with urllib.request.urlopen(req, timeout=120) as resp:
    buf = ''
    while True:
        chunk = resp.read(256)
        if not chunk:
            break
        buf += chunk.decode('utf-8', errors='replace')
        while '\n' in buf:
            line, buf = buf.split('\n', 1)
            s = line.strip()
            if not s.startswith('data:'):
                continue
            payload = s[5:].strip()
            if not payload or payload == '[DONE]':
                continue
            try:
                obj = json.loads(payload)
            except Exception:
                continue
            delta = (((obj.get('choices') or [{}])[0]).get('delta') or {}).get('content') or ''
            if delta:
                acc.append(delta)
            fr = ((obj.get('choices') or [{}])[0]).get('finish_reason') or ''
            if fr:
                finish = fr
text = ''.join(acc).strip()
print('stream_len', len(text))
print('stream_empty', not text)
print('stream_finish', finish)
print('stream_preview_ascii', text[:180].encode('ascii', 'backslashreplace').decode('ascii'))
"""
    code2, out2, _err2 = run(client, f"python3 - <<'PY'\n{stream_test}\nPY", timeout=150)

    client.close()
    if code != 0 or code2 != 0:
        return 1
    if "empty True" in out or "content_len 0" in out:
        print("FAIL: non-stream chat empty", file=sys.stderr)
        return 1
    if "stream_empty True" in out2 or "stream_len 0" in out2:
        print("FAIL: stream chat empty", file=sys.stderr)
        return 1
    print("\nDEPLOY_AND_TEST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

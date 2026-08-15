#!/usr/bin/env python3
"""Upload wristai server files and configure antony.fan."""

from __future__ import annotations

import os
import pathlib
import sys
import time

import paramiko

HOST = os.environ.get("WRISTAI_SSH_HOST", "antony.fan")
USER = os.environ.get("WRISTAI_SSH_USER", "root")
PASSWORD = os.environ.get("WRISTAI_SSH_PASSWORD", "")
REMOTE_ROOT = "/wristai"
LOCAL_SERVER = pathlib.Path(__file__).resolve().parents[1] / "server"

NGINX_SNIPPET = """
    # Wrist AI admin + chat proxy (127.0.0.1:18766)
    location ^~ /wristai/ {
        proxy_pass http://127.0.0.1:18766;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
        chunked_transfer_encoding on;
    }

    location = /wristai {
        return 301 /wristai/;
    }
"""


def run(client: paramiko.SSHClient, cmd: str, check: bool = True) -> str:
    print(f"$ {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=300)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out:
        print(out.rstrip())
    if err:
        print(err.rstrip(), file=sys.stderr)
    if check and code != 0:
        raise RuntimeError(f"command failed ({code}): {cmd}")
    return out


def ensure_nginx(client: paramiko.SSHClient) -> None:
    conf = "/opt/1panel/apps/openresty/openresty/conf/conf.d/homepage.conf"
    current = run(client, f"cat {conf}")
    if "location ^~ /wristai/" in current:
        print("nginx: /wristai/ already configured")
        return

    marker = "    # SuperMini device API + image host (proxied to 127.0.0.1:18765)"
    if marker not in current:
        # append before final closing brace
        idx = current.rfind("}")
        if idx < 0:
            raise RuntimeError("cannot find end of homepage.conf")
        updated = current[:idx] + NGINX_SNIPPET + "\n" + current[idx:]
    else:
        updated = current.replace(marker, NGINX_SNIPPET + "\n" + marker)

    sftp = client.open_sftp()
    with sftp.file(conf, "w") as f:
        f.write(updated)
    sftp.close()
    cname = run(
        client,
        "docker ps --format '{{.Names}}' | grep -i openresty | head -1",
    ).strip()
    if not cname:
        raise RuntimeError("openresty container not found")
    run(client, f"docker exec {cname} nginx -t")
    run(client, f"docker exec {cname} nginx -s reload")
    print("nginx: reloaded with /wristai/")


def main() -> int:
    if not PASSWORD:
        print("Set WRISTAI_SSH_PASSWORD first", file=sys.stderr)
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

    run(client, f"mkdir -p {REMOTE_ROOT}/data")
    sftp = client.open_sftp()
    for name in ("app.py", "requirements.txt", "wristai.service"):
        local = LOCAL_SERVER / name
        remote = f"{REMOTE_ROOT}/{name}"
        print(f"upload {local} -> {remote}")
        sftp.put(str(local), remote)
    sftp.close()

    run(
        client,
        f"cd {REMOTE_ROOT} && python3 -m venv .venv && "
        f".venv/bin/pip install -U pip && .venv/bin/pip install -r requirements.txt",
    )
    run(client, f"cp {REMOTE_ROOT}/wristai.service /etc/systemd/system/wristai.service")
    run(client, "systemctl daemon-reload")
    run(client, "systemctl enable --now wristai.service")
    time.sleep(1)
    run(client, "systemctl --no-pager --full status wristai.service | head -30", check=False)

    ensure_nginx(client)

    # smoke tests
    run(client, "curl -sS http://127.0.0.1:18766/wristai/api/health")
    run(client, "curl -sS http://127.0.0.1/wristai/api/health")
    client.close()
    print("\nDONE: open http://antony.fan/wristai/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

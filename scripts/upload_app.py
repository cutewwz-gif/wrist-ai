#!/usr/bin/env python3
import os
import sys
import time
from pathlib import Path

import paramiko

PASSWORD = os.environ.get("WRISTAI_SSH_PASSWORD", "")
LOCAL = Path(__file__).resolve().parents[1] / "server" / "app.py"


def main() -> int:
    if not PASSWORD:
        print("Set WRISTAI_SSH_PASSWORD", file=sys.stderr)
        return 2
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        "antony.fan",
        username="root",
        password=PASSWORD,
        timeout=20,
        allow_agent=False,
        look_for_keys=False,
    )
    sftp = client.open_sftp()
    sftp.put(str(LOCAL), "/wristai/app.py")
    sftp.close()
    stdin, stdout, stderr = client.exec_command("systemctl restart wristai.service")
    stdout.channel.recv_exit_status()
    time.sleep(1.2)
    stdin, stdout, stderr = client.exec_command(
        "curl -sS http://127.0.0.1:18766/wristai/api/health; "
        "python3 -c \"from pathlib import Path; import importlib.util; "
        "print('md_ok', 'markdown_to_plain' in Path('/wristai/app.py').read_text())\""
    )
    print(stdout.read().decode())
    err = stderr.read().decode()
    if err:
        print(err, file=sys.stderr)
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

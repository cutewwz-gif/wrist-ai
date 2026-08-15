#!/usr/bin/env python3
"""Run a remote command on antony.fan via SSH.

Set env:
  WRISTAI_SSH_HOST (default antony.fan)
  WRISTAI_SSH_USER (default root)
  WRISTAI_SSH_PASSWORD (required)
"""
import os
import sys

import paramiko

HOST = os.environ.get("WRISTAI_SSH_HOST", "antony.fan")
USER = os.environ.get("WRISTAI_SSH_USER", "root")
PASSWORD = os.environ.get("WRISTAI_SSH_PASSWORD", "")


def main() -> int:
    if not PASSWORD:
        print("Set WRISTAI_SSH_PASSWORD first", file=sys.stderr)
        return 2
    cmd = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "echo ok"
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
    stdin, stdout, stderr = client.exec_command(cmd, timeout=120)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out:
        print(out, end="" if out.endswith("\n") else "\n")
    if err:
        print(err, end="" if err.endswith("\n") else "\n", file=sys.stderr)
    client.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())

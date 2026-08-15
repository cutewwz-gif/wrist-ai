#!/usr/bin/env python3
import os
import paramiko

HOST = os.environ.get("WRISTAI_SSH_HOST", "antony.fan")
USER = os.environ.get("WRISTAI_SSH_USER", "root")
PASSWORD = os.environ.get("WRISTAI_SSH_PASSWORD", "")

def main():
    if not PASSWORD:
        raise SystemExit("Set WRISTAI_SSH_PASSWORD")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASSWORD, timeout=20, allow_agent=False, look_for_keys=False)
    cmd = "curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 8 https://api.github.com; echo; which git; git --version; which gh || true"
    stdin, stdout, stderr = c.exec_command(cmd, timeout=30)
    print(stdout.read().decode())
    print(stderr.read().decode())
    c.close()

if __name__ == "__main__":
    main()

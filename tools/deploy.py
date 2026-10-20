#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Upload the 3DS Controller .3dsx to the console over ftpd and write config.ini.

Usage
-----
    python tools/deploy.py --host 192.168.10.11
    python tools/deploy.py --host 192.168.10.11 --pc-ip 192.168.10.9
    python tools/deploy.py --host 192.168.10.11 --no-config

`--pc-ip` defaults to auto-detection: the local address that would be used to
reach the 3DS. That is the address the console has to send its UDP packets to.

The file goes to /3ds/3ds_controller.3dsx. config.ini is written twice, because
the working directory differs between the two ways of starting the app:
  * .3dsx via Homebrew Launcher -> cwd is /3ds  -> /3ds/config.ini
  * .cia from the home menu     -> cwd is /     -> /config.ini
"""
import argparse
import hashlib
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ftp_client import Client

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_3DSX = os.path.join(HERE, "prebuilt", "3ds_controller.3dsx")
REMOTE_3DSX = "3ds/3ds_controller.3dsx"
CONF_PATHS = ["3ds/config.ini", "config.ini"]


def detect_local_ip(host):
    """Local address used to reach `host` (no packet is actually sent)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((host, 5000))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def md5(path):
    with open(path, "rb") as fp:
        return hashlib.md5(fp.read()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description="Deploy 3DS Controller over ftpd")
    ap.add_argument("--host", default=os.environ.get("DS_HOST", "192.168.10.11"),
                    help="3DS IP address (default: $DS_HOST or 192.168.10.11)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("DS_PORT", "5000")),
                    help="ftpd port (default: 5000)")
    ap.add_argument("--pc-ip", default=os.environ.get("PC_IP"),
                    help="PC IP written into config.ini (default: auto-detect)")
    ap.add_argument("--no-config", action="store_true",
                    help="only upload the .3dsx, leave config.ini untouched")
    ap.add_argument("--no-upload", action="store_true",
                    help="only write config.ini")
    args = ap.parse_args()

    if not os.path.exists(LOCAL_3DSX):
        sys.exit(f"[ERROR] not found: {LOCAL_3DSX}")

    pc_ip = args.pc_ip or detect_local_ip(args.host)
    conf = f"serverip={pc_ip}\nport=8888\nlcdtogglekey=KEY_L\n"

    print(f"[连接] {args.host}:{args.port}")
    c = Client(args.host, args.port)

    if not args.no_upload:
        size = os.path.getsize(LOCAL_3DSX)
        print(f"[上传] {LOCAL_3DSX} -> {REMOTE_3DSX} ({size} B)")
        if not c.put(REMOTE_3DSX, LOCAL_3DSX):
            c.close()
            sys.exit("[ERROR] upload failed")

        check = os.path.join(HERE, "_verify.3dsx")
        if c.get(REMOTE_3DSX, check):
            same = md5(check) == md5(LOCAL_3DSX)
            os.remove(check)
            print(f"[校验] {'md5 一致' if same else 'MD5 不一致！'}")
            if not same:
                c.close()
                sys.exit("[ERROR] verification failed")

    if not args.no_config:
        for path in CONF_PATHS:
            if c.put_bytes(path, conf.encode("utf-8")):
                print(f"[配置] {path} -> {conf.strip().replace(chr(10), ' | ')}")
            else:
                print(f"[警告] 写入 {path} 失败")

    c.close()
    print("[完成] 在 3DS 上用 Homebrew Launcher 启动 3ds_controller")


if __name__ == "__main__":
    main()

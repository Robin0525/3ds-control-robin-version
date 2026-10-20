#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""3DS ftpd helper: connect, list, read and write files on the 3DS SD card.

ftpd on the 3DS reports its own address in the PASV reply, which is often
unreachable from the PC (the console may advertise a different interface), so
PASV host is forced to the host we connected to.
"""
import ftplib
import os
import re
import time

DEFAULT_HOST = os.environ.get("DS_HOST", "192.168.10.11")
DEFAULT_PORT = int(os.environ.get("DS_PORT", "5000"))


class Client:
    def __init__(self, host=None, port=None):
        self.host = host or DEFAULT_HOST
        self.port = port or DEFAULT_PORT
        self.ftp = None
        self.connect()

    def connect(self):
        self.close()
        f = ftplib.FTP()
        f.encoding = "utf-8"
        f.connect(self.host, self.port, timeout=25)
        try:
            f.login("anonymous", "anonymous")
        except ftplib.error_perm:
            f.encoding = "latin-1"
            f.login()

        def makepasv():
            resp = f.sendcmd("PASV")
            m = re.search(r"(\d+),(\d+),(\d+),(\d+),(\d+),(\d+)", resp)
            if not m:
                raise ftplib.error_reply(resp)
            n = [int(x) for x in m.groups()]
            return self.host, n[4] * 256 + n[5]

        f.makepasv = makepasv
        self.ftp = f

    def close(self):
        if self.ftp:
            try:
                self.ftp.quit()
            except Exception:
                try:
                    self.ftp.close()
                except Exception:
                    pass
            self.ftp = None

    def ls(self, path="", retry=3):
        for _ in range(retry):
            try:
                self.ftp.cwd("/")
                if path:
                    self.ftp.cwd(path)
                lines = []
                self.ftp.retrlines("LIST", lines.append)
                time.sleep(0.18)
                rows = []
                for ln in lines:
                    p = ln.split(None, 8)
                    if len(p) < 9:
                        continue
                    rows.append({
                        "dir": p[0].startswith("d"),
                        "size": p[4],
                        "date": f"{p[5]} {p[6]} {p[7]}",
                        "name": p[8],
                    })
                return rows
            except Exception:
                self.connect()
                time.sleep(0.4)
        return None

    def get(self, remote, local):
        for _ in range(3):
            try:
                with open(local, "wb") as fp:
                    self.ftp.retrbinary(f"RETR {remote}", fp.write)
                time.sleep(0.18)
                return True
            except Exception:
                self.connect()
                time.sleep(0.4)
        return False

    def put(self, remote, local):
        for _ in range(3):
            try:
                with open(local, "rb") as fp:
                    self.ftp.storbinary(f"STOR {remote}", fp, blocksize=8192)
                time.sleep(0.18)
                return True
            except Exception:
                self.connect()
                time.sleep(0.4)
        return False

    def put_bytes(self, remote, data):
        import io
        for _ in range(3):
            try:
                self.ftp.storbinary(f"STOR {remote}", io.BytesIO(data))
                time.sleep(0.18)
                return True
            except Exception:
                self.connect()
                time.sleep(0.4)
        return False

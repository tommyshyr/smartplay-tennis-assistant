"""User-facing launcher. Reuses an existing assistant, otherwise opens after readiness."""
from pathlib import Path
from http.client import HTTPConnection
import subprocess
import sys
import threading
import time
import webbrowser

URL = 'http://127.0.0.1:8787'


def available():
    con = HTTPConnection('127.0.0.1', 8787, timeout=1)
    try:
        con.request('GET', '/api/state')
        response = con.getresponse()
        return response.status == 200 and b'csrf_token' in response.read(512_000)
    except OSError:
        return False
    finally:
        con.close()


if sys.version_info < (3, 11):
    raise SystemExit('请安装 Python 3.11 或更新版本。')
if available():
    webbrowser.open(URL)
    raise SystemExit(0)


def open_when_ready():
    for _ in range(40):
        if available():
            webbrowser.open(URL)
            return
        time.sleep(0.25)


threading.Thread(target=open_when_ready, daemon=True).start()
raise SystemExit(subprocess.call([sys.executable, str(Path(__file__).with_name('app.py'))]))

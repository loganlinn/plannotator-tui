"""Controlled agent-shaped PTY for test-kitty-integration.py; never calls a model."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import termios
import tty

root, binary, host = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
old = termios.tcgetattr(0)


def draw(mode='empty'):
    prompt = '›' if host == 'codex' else '❯'
    boundary = '─' * 20 if host == 'claude' else ''
    suffix = 'unfinished draft' if mode == 'draft' else ''
    footer = '1. Approve this command?' if mode == 'dialog' else '? for shortcuts'
    sys.stdout.write(f'\x1b[2J\x1b[HCaptured {host} output\x1b[3;1H{boundary}'
        f'\x1b[4;1H{prompt} {suffix}\x1b[5;1H{boundary}\x1b[7;1H{footer}'
        '\x1b[?2004h\x1b[?25h\x1b[4;3H')
    sys.stdout.flush()


try:
    tty.setraw(0)
    draw()
    (root / 'started').touch()
    data = b''
    while True:
        command = root / 'command.json'
        if command.exists():
            request = json.loads(command.read_text())
            command.unlink()
            if 'event' in request:
                subprocess.run([binary, 'kitty', 'hook', host], input=json.dumps(request['event']),
                               text=True, capture_output=True, check=True, timeout=10)
            if 'mode' in request:
                draw(request['mode'])
            (root / 'done').write_text(str(request['sequence']))
        if select.select([0], [], [], .02)[0]:
            chunk = os.read(0, 65536)
            if not chunk:
                break
            data += chunk
            (root / 'received').write_bytes(data)
finally:
    termios.tcsetattr(0, termios.TCSANOW, old)

"""Cross-platform keyboard input — Windows (msvcrt) and Linux (termios)."""

import sys
import time

if sys.platform == "win32":
    import msvcrt

    def read_key() -> str:
        ch = msvcrt.getwch()
        if ch in ('\x00', '\xe0'):
            ch2 = msvcrt.getwch()
            return {'H': 'UP', 'P': 'DOWN', 'K': 'LEFT', 'M': 'RIGHT'}.get(ch2, '')
        if ch == '\r':
            return 'ENTER'
        if ch == '\x1b':
            return 'ESC'
        return ch.lower()

    def poll_key(timeout: float = 0.1) -> str | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if msvcrt.kbhit():
                return read_key()
            time.sleep(0.02)
        return None

else:
    import os
    import select
    import termios
    import tty

    _ARROW_SEQS = {
        b'[A': 'UP',  b'[B': 'DOWN',  b'[D': 'LEFT',  b'[C': 'RIGHT',
        b'OA': 'UP',  b'OB': 'DOWN',  b'OD': 'LEFT',  b'OC': 'RIGHT',
    }

    def _read_one(fd: int) -> bytes:
        return os.read(fd, 1)

    def _parse(fd: int, ch: bytes) -> str:
        if ch == b'\x1b':
            r, _, _ = select.select([fd], [], [], 0.05)
            if r:
                seq = os.read(fd, 2)
                return _ARROW_SEQS.get(seq, 'ESC')
            return 'ESC'
        if ch in (b'\r', b'\n'):
            return 'ENTER'
        if ch == b'\x03':
            raise KeyboardInterrupt
        if ch == b'\x04':
            return 'ESC'
        if not ch:
            return ''
        return ch.decode('utf-8', errors='replace').lower()

    def read_key() -> str:
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            return _parse(fd, _read_one(fd))
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    def poll_key(timeout: float = 0.1) -> str | None:
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            # TCSANOW: apply immediately without flushing buffered input
            tty.setcbreak(fd, termios.TCSANOW)
            r, _, _ = select.select([fd], [], [], timeout)
            if not r:
                return None
            return _parse(fd, _read_one(fd))
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

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
    import select
    import termios
    import tty

    def read_key() -> str:
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == '\x1b':
                # Check if more bytes follow (arrow keys send \x1b[A etc.)
                r, _, _ = select.select([sys.stdin], [], [], 0.05)
                if r:
                    seq = sys.stdin.read(2)
                    return {
                        '[A': 'UP', '[B': 'DOWN', '[D': 'LEFT', '[C': 'RIGHT',
                    }.get(seq, 'ESC')
                return 'ESC'
            if ch == '\r' or ch == '\n':
                return 'ENTER'
            if ch == '\x03':   # Ctrl-C
                raise KeyboardInterrupt
            if ch == '\x04':   # Ctrl-D
                return 'ESC'
            return ch.lower()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    def poll_key(timeout: float = 0.1) -> str | None:
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        if r:
            return read_key()
        return None

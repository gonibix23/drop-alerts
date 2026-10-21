from pathlib import Path


class ProcessLock:
    """OS-held singleton lock, released on crash; never delete the locked file."""

    def __init__(self, path: str):
        self.path = Path(path + ".lock")
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        self.file.seek(0)
        self.file.write(b"0")
        self.file.flush()
        self.file.seek(0)
        try:
            if __import__("os").name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("Ya existe un servicio usando esta base de datos") from None
        return self

    def __exit__(self, *_):
        self.file.close()

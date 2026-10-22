"""一轮工作的过程日志。写入日志文件，不打到终端。"""

import time
from pathlib import Path

from .config import TRACE_LOG

_MAX_BYTES = 1_048_576
_KEEP = 3


class Trace:
    """按步骤记下耗时。总时间从创建时算起，本步时间是距上一条的间隔。"""

    def __init__(self) -> None:
        now = time.monotonic()
        self.started = now
        self._last = now

    def log(self, message: str) -> None:
        now = time.monotonic()
        total = now - self.started
        gap = now - self._last
        self._last = now
        clock = time.strftime("%H:%M:%S")
        _write(f"{clock} [trace +{total:6.2f}s | 本步 {gap:5.2f}s] {message}")

    def write_block(self, title: str, body: str) -> None:
        """把一段多行正文写进日志，不截断。"""
        text = body.strip()
        if not text:
            return
        self.log(title)
        _write("\n".join(f"  | {line}" for line in text.splitlines()))

    def since(self, started: float) -> float:
        return time.monotonic() - started


def clip(text: str, limit: int = 180) -> str:
    """把日志里的参数压成一行，并截断过长的内容。"""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1] + "…"


def _write(text: str) -> None:
    path = TRACE_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    _rotate(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def _rotate(path: Path) -> None:
    """超过大小就滚动，只保留最近几份。"""
    if not path.exists() or path.stat().st_size < _MAX_BYTES:
        return
    oldest = _backup(path, _KEEP)
    if oldest.exists():
        oldest.unlink()
    for index in range(_KEEP - 1, 0, -1):
        source = _backup(path, index)
        if source.exists():
            source.replace(_backup(path, index + 1))
    path.replace(_backup(path, 1))


def _backup(path: Path, index: int) -> Path:
    return path.with_name(f"{path.name}.{index}")

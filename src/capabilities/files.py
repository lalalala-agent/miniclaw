"""限制在工作区内的文件、命令和网页工具。"""

import asyncio
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from agents import function_tool

from ..config import REPO_ROOT, WORKSPACE_DIR

MAX_FILE_CHARS = 100_000
MAX_COMMAND_OUTPUT = 8_000
MAX_FETCH_BYTES = 100_000
COMMAND_TIMEOUT_SECONDS = 60


def resolve_workspace_path(raw: str) -> Path:
    """把路径解析到工作区内，拒绝逃出工作区的路径。"""
    if not raw or not raw.strip():
        raise ValueError("path is empty")
    root = WORKSPACE_DIR.resolve()
    candidate = Path(raw)
    path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if not path.is_relative_to(root):
        raise ValueError("path escapes workspace")
    return path


def _trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[输出已截断]"


def _reject_glob(pattern: str) -> str | None:
    if not pattern or Path(pattern).is_absolute() or ".." in Path(pattern).parts:
        return "模式无效。"
    return None


def _read_file_sync(path: str) -> str:
    try:
        file = resolve_workspace_path(path)
    except ValueError as exc:
        return str(exc)
    if not file.is_file():
        return "文件不存在。"
    return _trim(file.read_text(encoding="utf-8"), MAX_FILE_CHARS)


def _write_file_sync(path: str, content: str) -> str:
    try:
        file = resolve_workspace_path(path)
    except ValueError as exc:
        return str(exc)
    file.parent.mkdir(parents=True, exist_ok=True)
    if not file.parent.resolve().is_relative_to(WORKSPACE_DIR.resolve()):
        return "path escapes workspace"
    file.write_text(content, encoding="utf-8")
    return "已写入。"


def _edit_file_sync(path: str, old_text: str, new_text: str) -> str:
    if not old_text:
        return "要替换的文本不能为空。"
    try:
        file = resolve_workspace_path(path)
    except ValueError as exc:
        return str(exc)
    if not file.is_file():
        return "文件不存在。"
    content = file.read_text(encoding="utf-8")
    count = content.count(old_text)
    if count == 0:
        return "未找到要替换的文本。"
    if count > 1:
        return f"找到 {count} 处匹配，需要唯一匹配才能替换。"
    file.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
    return "已更新。"


def _glob_files_sync(pattern: str) -> str:
    rejected = _reject_glob(pattern)
    if rejected:
        return rejected
    root = WORKSPACE_DIR.resolve()
    matches: list[str] = []
    for path in root.glob(pattern):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            continue
        matches.append(str(resolved.relative_to(root)).replace("\\", "/"))
        if len(matches) >= 200:
            break
    if not matches:
        return "没有匹配的文件。"
    return "\n".join(sorted(matches))


def _grep_files_sync(pattern: str, glob_pattern: str) -> str:
    rejected = _reject_glob(glob_pattern)
    if rejected:
        return rejected
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return f"正则无效：{exc}"
    root = WORKSPACE_DIR.resolve()
    lines: list[str] = []
    for path in root.glob(glob_pattern):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(root) or resolved.stat().st_size > 1_000_000:
            continue
        try:
            text = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        relative = str(resolved.relative_to(root)).replace("\\", "/")
        for number, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                lines.append(f"{relative}:{number}:{line[:300]}")
                if len(lines) >= 50:
                    return "\n".join(lines) + "\n...[结果已截断]"
    return "\n".join(lines) if lines else "没有匹配。"


def _command_env() -> dict[str, str]:
    """让 python 指向本仓库的虚拟环境，从而能 import python-pptx。"""
    env = os.environ.copy()
    venv_bin = REPO_ROOT / ".venv" / "bin"
    if venv_bin.is_dir():
        env["PATH"] = str(venv_bin) + os.pathsep + env.get("PATH", "")
    return env


def _run_command_sync(command: str) -> str:
    if not command.strip():
        return "命令为空。"
    if sys.platform == "win32":
        argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        argv = ["bash", "-lc", command]
    try:
        completed = subprocess.run(
            argv,
            cwd=WORKSPACE_DIR,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
            env=_command_env(),
        )
    except subprocess.TimeoutExpired:
        return "命令超时。"
    except OSError as exc:
        return f"无法执行命令：{exc}"
    output = (completed.stdout or "") + (completed.stderr or "")
    body = _trim(output.strip(), MAX_COMMAND_OUTPUT) or "(无输出)"
    return f"退出码 {completed.returncode}\n{body}"


def _fetch_url_sync(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "只允许 http 或 https。"
    request = urllib.request.Request(url, headers={"User-Agent": "self-agent"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = response.read(MAX_FETCH_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return f"抓取失败：{exc}"
    text = payload[:MAX_FETCH_BYTES].decode("utf-8", errors="replace")
    if len(payload) > MAX_FETCH_BYTES:
        text += "\n...[输出已截断]"
    return text


async def read_file(path: str) -> str:
    """读取工作区内的文本文件。path 是相对工作区的路径。"""
    return await asyncio.to_thread(_read_file_sync, path)


async def write_file(path: str, content: str) -> str:
    """把文本写入工作区内的文件。父目录不存在时会创建。path 是相对工作区的路径。"""
    return await asyncio.to_thread(_write_file_sync, path, content)


async def edit_file(path: str, old_text: str, new_text: str) -> str:
    """替换工作区文件中唯一一处匹配的文本。path 是相对工作区的路径。"""
    return await asyncio.to_thread(_edit_file_sync, path, old_text, new_text)


async def glob_files(pattern: str) -> str:
    """按 glob 列出工作区内的文件。例如 *.md 或 conversations/*.md。"""
    return await asyncio.to_thread(_glob_files_sync, pattern)


async def grep_files(pattern: str, glob_pattern: str = "**/*") -> str:
    """在工作区文件中搜索正则。glob_pattern 用来缩小文件范围。"""
    return await asyncio.to_thread(_grep_files_sync, pattern, glob_pattern)


async def run_command(command: str) -> str:
    """在工作区执行一条命令。Windows 使用 PowerShell，其他系统使用 bash。工作目录固定为工作区。"""
    return await asyncio.to_thread(_run_command_sync, command)


async def fetch_url(url: str) -> str:
    """抓取 http 或 https 页面的文本内容。"""
    return await asyncio.to_thread(_fetch_url_sync, url)


FILE_TOOLS = [
    function_tool(read_file),
    function_tool(write_file),
    function_tool(edit_file),
    function_tool(glob_files),
    function_tool(grep_files),
    function_tool(run_command),
    function_tool(fetch_url),
]

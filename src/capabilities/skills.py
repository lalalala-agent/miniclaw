"""扫描 skills 目录。提示里只放名称和描述，正文按需用 read_skill 读取。"""

import os
from dataclasses import dataclass
from pathlib import Path

from agents import function_tool

from ..config import POWERPOINT_SCRIPTS, SKILLS_DIR, wiki_relative

_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "logs"}


@dataclass(frozen=True)
class Skill:
    """一份已登记的技能。目录阶段只用名称和描述。"""

    name: str
    description: str
    path: Path
    listed: bool


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    meta: dict[str, str] = {}
    lines = text[3:end].strip("\n").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line or line[0] in " \t#" or ":" not in line:
            index += 1
            continue
        key, raw = line.split(":", 1)
        key = key.strip()
        raw = raw.strip()
        if raw in {">", ">-", "|", "|-"}:
            index += 1
            parts: list[str] = []
            while index < len(lines) and (not lines[index] or lines[index][0] in " \t"):
                parts.append(lines[index].strip())
                index += 1
            meta[key] = " ".join(part for part in parts if part)
            continue
        meta[key] = _unquote(raw)
        index += 1
    return meta


def _iter_skill_files(root: Path):
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if not name.startswith(".") and name not in _SKIP_DIRS)
        if "SKILL.md" in filenames:
            yield Path(dirpath) / "SKILL.md"


def _is_listed(meta: dict[str, str]) -> bool:
    flag = meta.get("disable-model-invocation", "").strip().lower()
    return flag not in {"1", "true", "yes"}


def load_skills() -> list[Skill]:
    """读每个 SKILL.md 的 frontmatter。没有 description 的不登记。"""
    found: list[Skill] = []
    seen: set[str] = set()
    for path in _iter_skill_files(SKILLS_DIR):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        meta = _frontmatter(text)
        description = " ".join(meta.get("description", "").split())
        if not description:
            continue
        name = meta.get("name") or path.parent.name
        if name in seen:
            continue
        seen.add(name)
        found.append(Skill(name=name, description=description, path=path, listed=_is_listed(meta)))
    return sorted(found, key=lambda skill: skill.name)


def _lookup(name: str) -> Skill | None:
    wanted = name.strip()
    if not wanted:
        return None
    skills = load_skills()
    for skill in skills:
        if skill.name == wanted or skill.path.parent.name == wanted:
            return skill
    candidate = Path(wanted).expanduser()
    if not candidate.is_absolute():
        candidate = SKILLS_DIR / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    root = SKILLS_DIR.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        return None
    file = resolved / "SKILL.md" if resolved.is_dir() else resolved
    for skill in skills:
        if skill.path.resolve() == file:
            return skill
    return None


def _render(skill: Skill, text: str) -> str:
    replacements = {
        "{{SKILL_DIR}}": str(skill.path.parent),
        "{{WIKI}}": wiki_relative(),
        "{{PPTX_SCRIPTS}}": str(POWERPOINT_SCRIPTS),
    }
    for token, value in replacements.items():
        text = text.replace(token, value)
    return f"技能目录：{skill.path.parent}\n\n{text}"


def skill_instructions() -> str:
    """每轮提示里的技能目录。只有名称、描述和文件位置。"""
    listed = [skill for skill in load_skills() if skill.listed]
    if not listed:
        return ""
    lines = [
        "下列技能只提供名称、描述和文件位置。用户请求与某条描述相符时，先调用 read_skill，参数用技能名称，再按正文执行。",
        "技能正文里的相对路径，相对于该技能目录（SKILL.md 的上一级）解析成绝对路径后再交给工具。",
        "",
        "<available_skills>",
    ]
    for skill in listed:
        lines.append("  <skill>")
        lines.append(f"    <name>{_escape(skill.name)}</name>")
        lines.append(f"    <description>{_escape(skill.description)}</description>")
        lines.append(f"    <location>{_escape(str(skill.path))}</location>")
        lines.append("  </skill>")
    lines.append("</available_skills>")
    return "\n".join(lines)


async def read_skill(name: str) -> str:
    """按名称读取技能正文。仅当用户请求与该技能的描述相符时调用。"""
    skill = _lookup(name)
    if skill is None:
        names = "、".join(item.name for item in load_skills()) or "（无）"
        return f"没有这个技能。可用：{names}"
    try:
        text = skill.path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return f"无法读取技能：{exc}"
    return _render(skill, text)


SKILL_TOOLS = [function_tool(read_skill)]

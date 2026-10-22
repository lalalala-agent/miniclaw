"""能力层。新的工具、Skill 或插件在这里登记一个提供者。"""

from ..work import Work
from .files import FILE_TOOLS
from .host import host_tools
from .skills import SKILL_TOOLS


def tools_for(work: Work, gateway) -> list:
    """返回这一轮工作可用的工具。"""
    return [*FILE_TOOLS, *host_tools(work, gateway), *SKILL_TOOLS]

"""Read agent definitions from .claude/agents/*.md frontmatter.

Reads only the YAML frontmatter (name, description, tools, team).
Never executes agents, never modifies definitions.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = ROOT / ".claude" / "agents"

# Team membership by role name (derived from TEAM.md)
SYSTEM_TEAM = {
    "system-architect",
    "data-source-steward",
    "data-quality-engineer",
    "backtest-engineer",
    "security-monitor",
    "integrations-engineer",
    "kronos-evaluator",
}
TRADING_TEAM = {
    "macro-researcher",
    "mtf-analyst",
    "news-analyst",
    "strategy-researcher",
    "risk-guardian",
    "execution-officer",
    "post-trade-reviewer",
}

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_KV_RE = re.compile(r"^(\w[\w-]*):\s*(.+)$", re.MULTILINE)


def _parse_frontmatter(text: str) -> dict[str, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    return {k: v.strip() for k, v in _KV_RE.findall(m.group(1))}


def list_agents() -> list[dict]:
    """Return agent metadata from frontmatter, sorted by team then name."""
    agents: list[dict] = []
    for path in sorted(AGENTS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        fm = _parse_frontmatter(text)
        name = fm.get("name", path.stem)
        team = "system" if name in SYSTEM_TEAM else "trading" if name in TRADING_TEAM else "unknown"
        agents.append({
            "name": name,
            "description": fm.get("description", ""),
            "tools": fm.get("tools", ""),
            "team": team,
        })
    # system team first, then trading
    agents.sort(key=lambda a: (0 if a["team"] == "system" else 1, a["name"]))
    return agents

"""Conservative shell command risk classification."""

from __future__ import annotations

import re

from .base import RiskLevel


class ShellSafetyPolicy:
    """Classify shell text before it reaches an operating-system shell."""

    _blocked = (
        (re.compile(r"\b(?:format|mkfs(?:\.\w+)?)\b", re.I), "disk formatting"),
        (re.compile(r"\b(?:diskpart|fdisk|parted)\b", re.I), "partition management"),
        (re.compile(r"\bdd\b.+\bof=/dev/", re.I), "raw device write"),
        (
            re.compile(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\s+/(?:\s|$)", re.I),
            "root deletion",
        ),
        (
            re.compile(r"\bremove-item\s+(?:[a-zA-Z]:\\|/)\s+.*-(?:recurse|r)\b", re.I),
            "root deletion",
        ),
    )
    _high = (
        (re.compile(r"\b(?:rm|rmdir|del|erase|remove-item)\b", re.I), "file deletion"),
        (
            re.compile(r"\b(?:sudo|runas|start-process\b.*-verb\s+runas)\b", re.I),
            "privilege escalation",
        ),
        (
            re.compile(r"\b(?:git\s+reset\s+--hard|git\s+clean\s+-[a-z]*f)", re.I),
            "destructive git operation",
        ),
        (
            re.compile(r"\b(?:shutdown|reboot|restart-computer|stop-computer)\b", re.I),
            "system shutdown",
        ),
        (
            re.compile(
                r"\b(?:curl|wget|invoke-webrequest)\b.*(?:\||;|&&).*(?:sh|bash|powershell)", re.I
            ),
            "download and execute",
        ),
        (
            re.compile(r"\bpowershell(?:\.exe)?\b.*-(?:encodedcommand|enc)\b", re.I),
            "encoded script",
        ),
    )
    _review = (
        (re.compile(r"(?:^|\s)(?:>|>>)(?:\s|$)"), "output redirection"),
        (
            re.compile(r"\b(?:move-item|mv|ren|rename-item|chmod|chown)\b", re.I),
            "filesystem mutation",
        ),
        (
            re.compile(r"\b(?:pip|npm|pnpm|yarn|cargo)\s+(?:install|add|uninstall|remove)\b", re.I),
            "dependency mutation",
        ),
    )

    def assess(self, command: str) -> tuple[RiskLevel, str]:
        normalized = command.strip()
        if not normalized:
            return RiskLevel.BLOCKED, "empty command"
        for pattern, reason in self._blocked:
            if pattern.search(normalized):
                return RiskLevel.BLOCKED, reason
        for pattern, reason in self._high:
            if pattern.search(normalized):
                return RiskLevel.HIGH, reason
        for pattern, reason in self._review:
            if pattern.search(normalized):
                return RiskLevel.REVIEW, reason
        return RiskLevel.SAFE, "no dangerous pattern detected"

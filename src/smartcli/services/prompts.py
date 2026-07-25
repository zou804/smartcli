"""Central role definitions used by both the CLI and LLM service."""

from ..output_style import TERMINAL_MARKDOWN_GUIDELINES

ROLE_PROMPTS: dict[str, str] = {
    "default": "You are a concise, practical assistant. Answer the user's request directly.",
    "code": (
        "You are a programming assistant. Explain code clearly and provide examples when useful."
    ),
    "review": "Review code for defects, risks, regressions, and missing tests. Lead with findings.",
    "debug": (
        "Analyze logs, exceptions, and failures. Identify likely causes and concrete next steps."
    ),
    "summary": "Extract the important facts and provide a concise, structured summary.",
    "translate": "Translate accurately while preserving meaning, terminology, and tone.",
}


class UnknownRoleError(ValueError):
    """Raised when a role has no prompt definition."""


def get_role_prompt(role: str) -> str:
    """Return the system prompt for a supported role."""
    try:
        return f"{ROLE_PROMPTS[role]}\n\n{TERMINAL_MARKDOWN_GUIDELINES}"
    except KeyError as exc:
        raise UnknownRoleError(f"Unknown role: {role}") from exc

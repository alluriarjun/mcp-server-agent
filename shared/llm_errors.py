"""Turn a Claude API failure into an actionable message.

Used by any MCP tool that calls the Claude API directly (agent_worker's resolve node,
mcp_server's get_top_momentum_with_commentary) so a failure comes back as a structured,
readable result instead of an unhandled exception — which MCP surfaces to the caller as
an opaque "Error executing tool X" with no detail at all.
"""

import anthropic


def missing_api_key_error() -> str:
    return (
        "ANTHROPIC_API_KEY is not set in .env, so this can't call the Claude API. "
        "Get a key from console.anthropic.com (Settings > API Keys) and add it to "
        "mcp-server-agent/.env, then try again."
    )


def _unwrap(exc: BaseException) -> BaseException:
    """Walk into nested ExceptionGroups down to the real exception underneath.

    The MCP SDK's ClientSession/stdio_client use anyio TaskGroups internally, which
    wrap any exception raised inside them in a BaseExceptionGroup — sometimes several
    layers deep. Without this, isinstance checks below never match anything real; they
    just see "ExceptionGroup" and fall through to the generic, unhelpful branch.
    """
    while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
        exc = exc.exceptions[0]
    return exc


def describe_llm_error(exc: Exception) -> str:
    exc = _unwrap(exc)
    if isinstance(exc, anthropic.AuthenticationError):
        return "Claude API rejected the request — ANTHROPIC_API_KEY in .env is invalid or expired."
    if isinstance(exc, anthropic.RateLimitError):
        return "Claude API rate limit hit — wait a moment and try again."
    if isinstance(exc, anthropic.APIConnectionError):
        return f"Could not reach the Claude API: {exc}"
    if isinstance(exc, anthropic.APIStatusError):
        detail = exc.message
        if isinstance(exc.body, dict):
            detail = exc.body.get("error", {}).get("message", detail)
        return f"Claude API error ({exc.status_code}): {detail}"
    return f"{type(exc).__name__}: {exc}"

# ---------------------------------------------------------------------------
# Core model aliases — single source of truth for langywrap builtins.
#
# Project-specific aliases belong in each project's ralph.py:
#
#   config = Pipeline(
#       aliases={
#           "codex":     "openai/gpt-5.1-codex",
#           "codex-mini": "openai/codex-mini-latest",
#       },
#       ...
#   )
# ---------------------------------------------------------------------------

BUILTIN_ALIASES: dict[str, str] = {
    # Anthropic
    "haiku":  "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus":   "claude-opus-4-6",
    # Kimi (via NVIDIA NIM)
    "kimi":   "nvidia/moonshotai/kimi-k2.6",
    # Gemma 4 variants
    "gemma4":            "openrouter/google/gemma-4-31b-it",
    "gemma4-nvidia":     "nvidia/google/gemma-4-31b-it",
    "gemma4-openrouter": "openrouter/google/gemma-4-31b-it:free",
}

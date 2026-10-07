---
name: codex-compactions
description: Show how many context compactions the current or other terminal-attached Codex sessions have undergone. Use when the user asks how many times this session has compacted or requests a summary of attached Codex sessions.
---

# Codex Session Compactions

Use the `codex-compactions` command as the source of truth.

- For "this session" or "current session", pass the session's own ID with `codex-compactions --session "$CODEX_SESSION_ID" --json`. If that variable is unavailable, use `CODEX_THREAD_ID`; do not select a session by recency.
- For up to 100 terminal-attached sessions, run `codex-compactions`.

Report the session name, compaction count, and last activity shown by the command. Every listed session is terminal-attached; do not infer anything about detached sessions.

For the current session, use the JSON result's `range`, `ranges`, and `guidance` fields. Report the current range and its guidance in plain language. Do not recalculate the range from the count.

These ranges are workflow guidance, not official Codex limits. When reporting multiple sessions, summarize the yellow and red sessions without repeating the full guidance for every row.

If the command is unavailable, report that the tool is not installed or not on `PATH` instead of estimating from session age or transcript size.

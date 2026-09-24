# ai-tools

Tools and scripts related to AI agents.

## codex-compactions

`bin/codex-compactions` summarizes local Codex sessions by human-readable name,
last activity, and context compaction count. It shows only sessions attached to
a terminal. It uses the Python standard library, plus `/proc` on Linux or the
standard `lsof` and `ps` commands on macOS.

It reads Codex metadata and rollout files locally and makes no network requests.

```console
bin/codex-compactions
bin/codex-compactions --session "$CODEX_SESSION_ID"
```

The default view shows up to 100 terminal-attached sessions, sorted by session
name, and no detached session. Run `bin/codex-compactions --help` for all
options.

The compaction count is color-coded as workflow guidance: green for 0-5
compactions, yellow for 6-11, and red for 12 or more. Yellow suggests preparing
a handoff if the session starts to drift; red suggests continuing in a fresh
session when accumulated context matters. These are not official Codex limits.
Colors are disabled automatically when output is redirected or piped. Use
`--color always` or `--color never` to override detection.

When the count suggests moving to a fresh session, use the
`handover` skill from [`claude-plan-skills`](https://github.com/gjoranv/claude-plan-skills).
It reviews the current repository and session state, offers to persist unfinished
work, and generates a copy-pasteable prompt for continuing in a new session.

### Using the skill in Codex

After installing the skill, ask naturally from a Codex session:

```text
How many times has this session been compacted?
```

To invoke the skill explicitly, include its name:

```text
$codex-compactions
```

The skill supplies the current session ID to the command and reports the
compaction count with guidance for the green, yellow, or red range. It can also
summarize every terminal-attached session:

```text
Use $codex-compactions to summarize my terminal-attached Codex sessions.
```

## Installation

The tool requires Python 3 and supports Linux and macOS. Linux uses the standard
`/proc` filesystem without additional tools. macOS uses the standard `lsof` and
`ps` commands. Native Windows is not supported.

Choose a user-writable executable directory on `PATH`. The example below uses
the common `~/.local/bin` location. From the repository root, link the
executable and skill into their user-wide locations:

```sh
mkdir -p "$HOME/.local/bin" "$HOME/.agents/skills"
ln -sfn "$PWD/bin/codex-compactions" "$HOME/.local/bin/codex-compactions"
ln -sfn "$PWD/skills/codex-compactions" "$HOME/.agents/skills/codex-compactions"
```

If `~/.local/bin` is not already on `PATH`, add this to your startup file:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

Codex normally detects skill changes automatically. Restart Codex if the skill
does not appear.

## Compatibility

The current format support was verified with Codex CLI 0.155.1 on macOS. The
on-disk formats under `~/.codex` are implementation details and may change in
future Codex releases.

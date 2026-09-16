# ai-tools

Tools and scripts related to AI agents.

## codex-compactions

`bin/codex-compactions` summarizes local Codex sessions by human-readable name,
last activity, and context compaction count. It shows only sessions attached to
a terminal. It uses the Python standard library plus the standard macOS `lsof`
and `ps` commands.

```console
bin/codex-compactions
bin/codex-compactions --session "$CODEX_SESSION_ID"
```

The default view shows up to 100 terminal-attached sessions, sorted by session
name, and no detached session. Run `bin/codex-compactions --help` for all
options.

In a terminal, the header is bold and the compaction count uses a local health
heuristic: green for 0-5 compactions, yellow for 6-11, and red for 12 or more.
Colors are disabled automatically when output is redirected or piped. Use
`--color always` or `--color never` to override detection.

## Installation

The tool requires macOS, Python 3, `lsof`, and `ps`. From the repository root,
link the executable and skill into user-wide locations:

```sh
mkdir -p "$HOME/bin" "$HOME/.agents/skills"
ln -sfn "$PWD/bin/codex-compactions" "$HOME/bin/codex-compactions"
ln -sfn "$PWD/skills/codex-compactions" \
  "$HOME/.agents/skills/codex-compactions"
```

Ensure `~/bin` is on `PATH`. Fish users can run:

```fish
fish_add_path $HOME/bin
```

Codex normally detects skill changes automatically. Restart Codex if the skill
does not appear.

## Compatibility

The current format support was verified with Codex CLI 0.154.0 on macOS. The
tool reads local session metadata and rollout files under `~/.codex`; it does
not transmit them. These on-disk formats are implementation details and may
change in future Codex releases.

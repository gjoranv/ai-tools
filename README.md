# ai-tools

Tools and scripts related to AI agents.

## codex-compactions

Run `bin/codex-compactions` for a quick summary of terminal-attached Codex
sessions. It shows each session's human-readable name, last activity, and
context compaction count. Optional hooks report the count after each compaction
and on the first prompt after resuming a session. The optional
`codex-compactions` skill lets you ask for the count from within Codex. The hooks
and skill all query the CLI, and you can use them together.

The CLI reads Codex metadata and rollout files locally and makes no network
requests.

### Run the CLI

The tool requires Python 3 and supports macOS and Linux. Linux has been tested
in an Ubuntu container, but not yet against a live Codex session. Native Windows
is not supported.

From the repository root, run:

```sh
bin/codex-compactions
```

The default view shows up to 100 terminal-attached sessions, sorted by session
name. It excludes detached sessions. Run `bin/codex-compactions --help` for all
options.

To run `codex-compactions` from any directory, link it into a user-writable
executable directory on `PATH`. For example, from the repository root:

```sh
mkdir -p "$HOME/.local/bin"
ln -sfn "$PWD/bin/codex-compactions" "$HOME/.local/bin/codex-compactions"
```

If `~/.local/bin` is not already on `PATH`, add this to your shell startup file:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

### Interpret the output

The compaction count is color-coded as workflow guidance: green for 0-5
compactions, yellow for 6-11, and red for 12 or more. Yellow suggests preparing
a handover before the session loses track of its goal, constraints, or progress.
Red suggests moving to a fresh session before work that relies on earlier
details.
These are not official Codex limits.

Colors are disabled automatically when output is redirected or piped; use
`--color always` or `--color never` to override detection.

### Automatic compaction reports

Optional Codex PostCompact and SessionStart hooks show the current session's
compaction count after each compaction and on the first prompt after resuming a
session. Both use the same script and message. Green reports use one line;
yellow and red reports add handover guidance in a frame. For example:

```text
── Compaction status ──
🟡 9 compactions for this session, YELLOW range (6-11)
Prepare a handover before the session loses track of its goal, constraints, or progress.
───────────────────────
```

The status symbol follows the same green, yellow, and red ranges described above.
Its appearance depends on terminal emoji rendering; the range label remains
explicit. If the count cannot be determined, the hook stays silent.
A resume report repeats the current total; it does not indicate a new compaction.

To install the hook, link the hook script from the repository root:

```sh
mkdir -p "$HOME/.local/bin"
ln -sfn "$PWD/hooks/codex-compaction-status" "$HOME/.local/bin/codex-compaction-status"
```

Add these entries to `~/.codex/hooks.json`, preserving other hooks. If either
event already runs this script under the old `codex-post-compact` name or the new
`codex-compaction-status` name, keep that handler and add only the missing one.
Codex runs every matching hook, so duplicate handlers produce duplicate reports.

```json
{
  "hooks": {
    "PostCompact": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.local/bin/codex-compaction-status",
            "timeout": 35
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "^resume$",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.local/bin/codex-compaction-status",
            "timeout": 35
          }
        ]
      }
    ]
  }
}
```

In Codex, run `/hooks` to review and trust new or changed hook definitions. To
test, run `/compact` in a throwaway Codex session. Then exit, resume it, and
send a prompt to see the resume report.

To remove the reports, delete the compaction status `PostCompact` entry and the
`SessionStart` entry with matcher `^resume$` from `~/.codex/hooks.json`, then
remove the `codex-compaction-status` symlink from `~/.local/bin` (or
`codex-post-compact` for an existing installation).

### Ask within Codex with the codex-compactions skill

The skill is an optional way to ask about compactions during a conversation.
It takes longer than running the CLI directly because Codex must invoke the
skill and command. The skill runs `codex-compactions` by name, so complete the
CLI `PATH` setup above first. To install the skill from the repository root:

```sh
mkdir -p "$HOME/.agents/skills"
ln -sfn "$PWD/skills/codex-compactions" "$HOME/.agents/skills/codex-compactions"
```

Codex normally detects skill changes automatically. Restart Codex if the skill
does not appear. You can then ask naturally:

```text
How many times has this session been compacted?
```

Or invoke the skill explicitly:

```text
$codex-compactions
```

The skill supplies the current session ID to the command and reads its JSON
result, including the compaction count and guidance for the current range. It
can also summarize every terminal-attached session:

```text
Use $codex-compactions to summarize my terminal-attached Codex sessions.
```

### Optional next step: handover

When the count suggests moving to a fresh session, the `handover`
skill from [`claude-plan-skills`](https://github.com/gjoranv/claude-plan-skills)
can help. It reviews the current repository and session state, offers to persist
unfinished work, and generates a copy-pasteable prompt for continuing in a new
session.

## Compatibility

The current format support was verified with Codex CLI 0.157.1 and its shared
app-server daemon on macOS. For Codex 0.157 and later, daemon-loaded sessions
are included only when their stored originator is `codex-tui`; sessions from
Codex Desktop remain excluded. The on-disk formats under `~/.codex` are
implementation details and may change in future Codex releases.

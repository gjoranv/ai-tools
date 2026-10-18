import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import uuid


SCRIPT = Path(__file__).parents[1] / "bin" / "codex-compactions"
HOOK = Path(__file__).parents[1] / "hooks" / "codex-compaction-status"
LEGACY_HOOK = Path(__file__).parents[1] / "hooks" / "codex-post-compact"


class CodexSessionsTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary_directory.name)
        self.active = self.home / "sessions" / "2026" / "09" / "16"
        self.archived = self.home / "archived_sessions"
        self.rollouts = []
        self.active.mkdir(parents=True)
        self.archived.mkdir()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def create_rollout(self, session_id, records, archived=False, age=0):
        directory = self.archived if archived else self.active
        path = directory / f"rollout-2026-09-16T12-00-00-{session_id}.jsonl"
        with path.open("w") as output:
            for record in records:
                output.write(json.dumps(record) + "\n")
        timestamp = time.time() - age
        os.utime(path, (timestamp, timestamp))
        self.rollouts.append(path)
        return path

    def write_index(self, records):
        with (self.home / "session_index.jsonl").open("w") as output:
            for record in records:
                output.write(json.dumps(record) + "\n")

    def script_environment(
        self,
        attached_paths=None,
        daemon_paths=None,
        extra_environment=None,
    ):
        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(self.home)
        environment["COLUMNS"] = "100"
        if attached_paths is None:
            attached_paths = self.rollouts
        if daemon_paths is None:
            daemon_paths = []
        if sys.platform.startswith("linux"):
            proc_root = self.create_proc_tree(
                attached_paths, daemon_paths=daemon_paths
            )
            environment["CODEX_COMPACTIONS_PROC_ROOT"] = str(proc_root)
        else:
            tool_directory = self.create_attachment_tools(
                attached_paths, daemon_paths=daemon_paths
            )
            environment["PATH"] = (
                f"{tool_directory}{os.pathsep}{environment['PATH']}"
            )
        if extra_environment:
            environment.update(extra_environment)
        return environment

    def run_script(
        self,
        *arguments,
        attached_paths=None,
        daemon_paths=None,
        extra_environment=None,
    ):
        return subprocess.run(
            [str(SCRIPT), *arguments],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=self.script_environment(
                attached_paths, daemon_paths, extra_environment
            ),
        )

    def run_hook(self, event, attached_paths=None, hook=HOOK):
        return subprocess.run(
            [sys.executable, str(hook)],
            input=json.dumps(event),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=self.script_environment(attached_paths=attached_paths),
        )

    def create_hook_session(self, count):
        session_id = str(uuid.uuid4())
        self.create_rollout(
            session_id, [{"type": "compacted"} for _ in range(count)]
        )
        self.write_index(
            [
                {
                    "id": session_id,
                    "thread_name": "Hook session",
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            ]
        )
        return session_id

    def create_attachment_tools(self, rollout_paths, daemon_paths=None):
        if daemon_paths is None:
            daemon_paths = []
        tool_directory = self.home / "fake-tools"
        tool_directory.mkdir(exist_ok=True)
        lsof = tool_directory / "lsof"
        lsof_lines = ["#!/usr/bin/env python3", "print('p123')", "print('ccodex')"]
        lsof_lines.extend(
            f"print({('n' + str(path.resolve()))!r})" for path in rollout_paths
        )
        if daemon_paths:
            lsof_lines.extend(("print('p456')", "print('ccodex')"))
            lsof_lines.extend(
                f"print({('n' + str(path.resolve()))!r})" for path in daemon_paths
            )
        lsof.write_text("\n".join(lsof_lines) + "\n")
        ps = tool_directory / "ps"
        ps_lines = [
            "#!/usr/bin/env python3",
            "print(' 123 ttys001 codex')",
        ]
        if daemon_paths:
            ps_lines.append(
                "print(' 456 ?? codex app-server --listen unix:// --managed-daemon')"
            )
        ps.write_text("\n".join(ps_lines) + "\n")
        lsof.chmod(0o755)
        ps.chmod(0o755)
        return tool_directory

    def create_proc_tree(
        self,
        rollout_paths,
        daemon_paths=None,
        directory="proc",
        tty_number=34817,
    ):
        if daemon_paths is None:
            daemon_paths = []
        proc_root = self.home / directory
        self.create_proc_process(
            proc_root,
            pid=123,
            rollout_paths=rollout_paths,
            tty_number=tty_number,
            arguments=["codex"],
        )
        if daemon_paths:
            self.create_proc_process(
                proc_root,
                pid=456,
                rollout_paths=daemon_paths,
                tty_number=0,
                arguments=[
                    "codex",
                    "app-server",
                    "--listen",
                    "unix://",
                    "--managed-daemon",
                ],
            )
        return proc_root

    def create_proc_process(
        self, proc_root, pid, rollout_paths, tty_number, arguments
    ):
        process = proc_root / str(pid)
        descriptors = process / "fd"
        descriptors.mkdir(parents=True, exist_ok=True)
        (process / "comm").write_text("codex\n")
        (process / "stat").write_text(
            f"{pid} (codex) S 1 {pid} {pid} {tty_number} 0 0\n"
        )
        (process / "cmdline").write_bytes(
            b"\0".join(argument.encode() for argument in arguments) + b"\0"
        )
        for descriptor, path in enumerate(rollout_paths, 3):
            link = descriptors / str(descriptor)
            if not link.exists():
                link.symlink_to(path.resolve())

    def write_database(self, records):
        connection = sqlite3.connect(self.home / "state_5.sqlite")
        connection.execute(
            """
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                rollout_path TEXT NOT NULL,
                updated_at INTEGER NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0,
                name TEXT,
                title TEXT,
                originator TEXT
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO threads (
                id, rollout_path, updated_at, archived, name, title, originator
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            records,
        )
        connection.commit()
        connection.close()

    def test_latest_rename_and_exact_compaction_records(self):
        session_id = str(uuid.uuid4())
        self.create_rollout(
            session_id,
            [
                {"type": "session_meta", "payload": {"id": session_id}},
                {"type": "compacted", "payload": {}},
                {"type": "message", "payload": {"text": 'literal "type":"compacted"'}},
                {"type": "compacted", "payload": {}},
            ],
        )
        self.write_index(
            [
                {
                    "id": session_id,
                    "thread_name": "Old name",
                    "updated_at": "2026-01-01T00:00:00Z",
                },
                {
                    "id": session_id,
                    "thread_name": "Current name",
                    "updated_at": "2026-01-02T00:00:00Z",
                },
            ]
        )

        result = self.run_script()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Current name", result.stdout)
        self.assertNotIn("Old name", result.stdout)
        row = next(line for line in result.stdout.splitlines() if "Current name" in line)
        self.assertRegex(row, r"\b2\b")

    def test_default_shows_only_attached_non_archived_sessions(self):
        attached_id = str(uuid.uuid4())
        detached_id = str(uuid.uuid4())
        archived_id = str(uuid.uuid4())
        attached = self.create_rollout(attached_id, [{"type": "session_meta"}])
        self.create_rollout(detached_id, [{"type": "session_meta"}], age=10)
        archived = self.create_rollout(
            archived_id, [{"type": "session_meta"}], archived=True
        )
        self.write_index(
            [
                {
                    "id": attached_id,
                    "thread_name": "Attached session",
                    "updated_at": "2026-01-01T00:00:00Z",
                },
                {
                    "id": detached_id,
                    "thread_name": "Detached session",
                    "updated_at": "2026-01-01T00:00:00Z",
                },
                {
                    "id": archived_id,
                    "thread_name": "Archived session",
                    "updated_at": "2026-01-01T00:00:00Z",
                },
            ]
        )

        result = self.run_script(attached_paths=[attached, archived])

        self.assertIn("Attached session", result.stdout)
        self.assertNotIn("Detached session", result.stdout)
        self.assertNotIn("Archived session", result.stdout)

    def test_missing_index_uses_first_user_message(self):
        session_id = str(uuid.uuid4())
        self.create_rollout(
            session_id,
            [
                {"type": "session_meta", "payload": {"id": session_id}},
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "Fallback session title\nDetails",
                            }
                        ],
                    },
                },
            ],
        )

        result = self.run_script()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Fallback session title", result.stdout)
        self.assertRegex(result.stdout, r"\b0\b")

    def test_session_selects_explicit_id(self):
        first_id = str(uuid.uuid4())
        second_id = str(uuid.uuid4())
        self.create_rollout(first_id, [{"type": "session_meta"}])
        self.create_rollout(second_id, [{"type": "session_meta"}])
        self.write_index(
            [
                {
                    "id": first_id,
                    "thread_name": "First session",
                    "updated_at": "2026-01-01T00:00:00Z",
                },
                {
                    "id": second_id,
                    "thread_name": "Second session",
                    "updated_at": "2026-01-01T00:00:00Z",
                },
            ]
        )

        result = self.run_script("--session", first_id)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("First session", result.stdout)
        self.assertNotIn("Second session", result.stdout)

    def test_default_sorts_sessions_by_name_case_insensitively(self):
        records = []
        for name in ("Zulu session", "alpha session", "Beta session"):
            session_id = str(uuid.uuid4())
            self.create_rollout(session_id, [{"type": "session_meta"}])
            records.append(
                {
                    "id": session_id,
                    "thread_name": name,
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            )
        self.write_index(records)

        result = self.run_script()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertLess(
            result.stdout.index("alpha session"),
            result.stdout.index("Beta session"),
        )
        self.assertLess(
            result.stdout.index("Beta session"),
            result.stdout.index("Zulu session"),
        )

    def test_default_limits_attached_sessions_to_100(self):
        index_records = []
        last_session_id = None
        for position in range(101):
            session_id = str(uuid.uuid4())
            last_session_id = session_id
            self.create_rollout(
                session_id,
                [{"type": "session_meta"}],
                age=position,
            )
            index_records.append(
                {
                    "id": session_id,
                    "thread_name": f"Session position {position:03d}",
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            )
        self.write_index(index_records)

        result = self.run_script()
        explicit = self.run_script("--session", last_session_id)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(101, len(result.stdout.splitlines()))
        self.assertIn("Session position 099", result.stdout)
        self.assertNotIn("Session position 100", result.stdout)
        self.assertIn("Session position 100", explicit.stdout)

    def test_colorizes_counts_and_bolds_header_when_forced(self):
        records = []
        for name, compactions in (
            ("Green session", 5),
            ("Yellow session", 6),
            ("Red session", 12),
        ):
            session_id = str(uuid.uuid4())
            rollout_records = [{"type": "session_meta"}]
            rollout_records.extend({"type": "compacted"} for _ in range(compactions))
            self.create_rollout(session_id, rollout_records)
            records.append(
                {
                    "id": session_id,
                    "thread_name": name,
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            )
        self.write_index(records)

        result = self.run_script("--color", "always")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(result.stdout.startswith("\033[1mCOMPACT"))
        self.assertRegex(result.stdout, "\033\\[32m\\s*5\033\\[0m")
        self.assertRegex(result.stdout, "\033\\[33m\\s*6\033\\[0m")
        self.assertRegex(result.stdout, "\033\\[31m\\s*12\033\\[0m")

    def test_json_reports_selected_session_and_guidance(self):
        sessions = {}
        for name, count in (("Green", 5), ("Yellow", 6), ("Red", 12)):
            session_id = str(uuid.uuid4())
            self.create_rollout(
                session_id,
                [{"type": "session_meta"}]
                + [{"type": "compacted"} for _ in range(count)],
            )
            sessions[name] = session_id
        self.write_index(
            [
                {
                    "id": session_id,
                    "thread_name": name,
                    "updated_at": "2026-01-01T00:00:00Z",
                }
                for name, session_id in sessions.items()
            ]
        )

        expected_ranges = {"green": "0-5", "yellow": "6-11", "red": "12+"}
        for name, count, status in (
            ("Green", 5, "green"),
            ("Yellow", 6, "yellow"),
            ("Red", 12, "red"),
        ):
            with self.subTest(name=name):
                result = self.run_script("--session", sessions[name], "--json")
                self.assertEqual(0, result.returncode, result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(sessions[name], report["session_id"])
                self.assertEqual(name, report["name"])
                self.assertEqual(count, report["compactions"])
                self.assertEqual(status, report["range"])
                self.assertEqual(expected_ranges, report["ranges"])
                self.assertTrue(report["guidance"])

        result = self.run_script("--json")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("--json requires --session", result.stderr)

    def test_post_compact_reports_selected_session(self):
        selected_id = str(uuid.uuid4())
        other_id = str(uuid.uuid4())
        self.create_rollout(
            selected_id,
            [{"type": "compacted"} for _ in range(6)],
        )
        self.create_rollout(
            other_id,
            [{"type": "compacted"} for _ in range(12)],
        )
        self.write_index(
            [
                {
                    "id": selected_id,
                    "thread_name": "Selected session",
                    "updated_at": "2026-01-01T00:00:00Z",
                },
                {
                    "id": other_id,
                    "thread_name": "Other session",
                    "updated_at": "2026-01-01T00:00:00Z",
                },
            ]
        )

        result = self.run_hook(
            {
                "hook_event_name": "PostCompact",
                "session_id": selected_id,
                "trigger": "auto",
            }
        )

        self.assertEqual(0, result.returncode, result.stderr)
        message = json.loads(result.stdout)["systemMessage"]
        self.assertEqual("", message.splitlines()[0])
        self.assertEqual("── Compaction status ──", message.splitlines()[1])
        self.assertEqual(
            "🟡 6 compactions for this session, YELLOW range (6-11)",
            message.splitlines()[2],
        )
        self.assertEqual(
            "Prepare a handover before the session loses track of "
            "its goal, constraints, or progress.",
            message.splitlines()[3],
        )
        self.assertEqual("───────────────────────", message.splitlines()[4])
        self.assertNotIn("\033[", message)
        self.assertNotIn("Selected session", message)
        self.assertNotIn("Other session", message)

    def test_legacy_hook_path_reports_the_same_status(self):
        session_id = self.create_hook_session(6)
        event = {"hook_event_name": "PostCompact", "session_id": session_id}

        current = self.run_hook(event)
        legacy = self.run_hook(event, hook=LEGACY_HOOK)

        self.assertEqual(0, current.returncode, current.stderr)
        self.assertEqual(0, legacy.returncode, legacy.stderr)
        self.assertEqual(current.stdout, legacy.stdout)

    def test_post_compact_formats_each_range(self):
        for count, status, interval, symbol in (
            (1, "GREEN", "0-5", "🟢"),
            (6, "YELLOW", "6-11", "🟡"),
            (12, "RED", "12+", "🔴"),
        ):
            with self.subTest(status=status):
                session_id = self.create_hook_session(count)
                messages = []
                for event in (
                    {"hook_event_name": "PostCompact", "session_id": session_id},
                    {
                        "hook_event_name": "SessionStart",
                        "source": "resume",
                        "session_id": session_id,
                    },
                ):
                    result = self.run_hook(event)
                    self.assertEqual(0, result.returncode, result.stderr)
                    messages.append(json.loads(result.stdout)["systemMessage"])
                self.assertEqual(messages[0], messages[1])
                message = messages[0]
                noun = "compaction" if count == 1 else "compactions"
                lines = message.splitlines()
                self.assertEqual("", lines[0])
                count_line = 1 if status == "GREEN" else 2
                self.assertEqual(
                    f"{symbol} {count} {noun} for this session, "
                    f"{status} range ({interval})",
                    lines[count_line],
                )
                if status == "GREEN":
                    self.assertEqual(2, len(lines))
                else:
                    self.assertEqual("── Compaction status ──", lines[1])
                    self.assertEqual("───────────────────────", lines[4])
                    self.assertEqual(5, len(lines))
                self.assertNotIn("\033[", message)
                self.assertNotIn("Hook session", message)

    def test_post_compact_is_silent_for_unattached_or_invalid_session(self):
        session_id = str(uuid.uuid4())
        self.create_rollout(session_id, [{"type": "compacted"}])
        event = {"hook_event_name": "PostCompact", "session_id": session_id}

        for candidate, paths in (
            (event, []),
            ({"hook_event_name": "PostCompact"}, None),
            ({"hook_event_name": "PreCompact", "session_id": session_id}, None),
            (
                {
                    "hook_event_name": "SessionStart",
                    "source": "startup",
                    "session_id": session_id,
                },
                None,
            ),
            (
                {
                    "hook_event_name": "SessionStart",
                    "source": "compact",
                    "session_id": session_id,
                },
                None,
            ),
            ({"hook_event_name": "SessionStart", "session_id": session_id}, None),
        ):
            with self.subTest(candidate=candidate, paths=paths):
                result = self.run_hook(candidate, attached_paths=paths)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("", result.stdout)

    def test_post_compact_skips_subagent_with_attached_parent(self):
        parent_id = str(uuid.uuid4())
        child_id = str(uuid.uuid4())
        self.create_rollout(
            parent_id,
            [{"type": "compacted"} for _ in range(12)],
        )

        for event in (
            {
                "hook_event_name": "PostCompact",
                "session_id": parent_id,
                "agent_id": child_id,
                "agent_type": "default",
                "trigger": "auto",
            },
            {
                "hook_event_name": "SessionStart",
                "source": "resume",
                "session_id": parent_id,
                "agent_id": child_id,
                "agent_type": "default",
            },
        ):
            with self.subTest(event=event["hook_event_name"]):
                result = self.run_hook(event)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("", result.stdout)

    def test_auto_color_is_disabled_when_output_is_not_a_terminal(self):
        session_id = str(uuid.uuid4())
        self.create_rollout(session_id, [{"type": "session_meta"}])
        self.write_index(
            [
                {
                    "id": session_id,
                    "thread_name": "Plain session",
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            ]
        )

        result = self.run_script()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("\033[", result.stdout)

    def test_managed_daemon_includes_only_codex_tui_sessions(self):
        tui_id = str(uuid.uuid4())
        desktop_id = str(uuid.uuid4())
        tui_rollout = self.create_rollout(tui_id, [{"type": "session_meta"}])
        desktop_rollout = self.create_rollout(
            desktop_id, [{"type": "session_meta"}]
        )
        self.write_database(
            [
                (
                    tui_id,
                    str(tui_rollout),
                    int(time.time()),
                    0,
                    "Daemon TUI session",
                    "",
                    "codex-tui",
                ),
                (
                    desktop_id,
                    str(desktop_rollout),
                    int(time.time()),
                    0,
                    "Desktop session",
                    "",
                    "Codex Desktop",
                ),
            ]
        )

        result = self.run_script(
            attached_paths=[], daemon_paths=[tui_rollout, desktop_rollout]
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Daemon TUI session", result.stdout)
        self.assertNotIn("Desktop session", result.stdout)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux-specific test")
    def test_linux_ignores_codex_process_without_terminal(self):
        session_id = str(uuid.uuid4())
        rollout = self.create_rollout(session_id, [{"type": "session_meta"}])
        proc_root = self.create_proc_tree(
            [rollout], directory="proc-without-terminal", tty_number=0
        )

        result = self.run_script(
            extra_environment={"CODEX_COMPACTIONS_PROC_ROOT": str(proc_root)}
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("No terminal-attached Codex sessions found.\n", result.stdout)


if __name__ == "__main__":
    unittest.main()

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import uuid


SCRIPT = Path(__file__).parents[1] / "bin" / "codex-compactions"


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

    def run_script(self, *arguments, attached_paths=None, extra_environment=None):
        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(self.home)
        environment["COLUMNS"] = "100"
        if attached_paths is None:
            attached_paths = self.rollouts
        tool_directory = self.create_attachment_tools(attached_paths)
        environment["PATH"] = f"{tool_directory}{os.pathsep}{environment['PATH']}"
        if extra_environment:
            environment.update(extra_environment)
        return subprocess.run(
            [str(SCRIPT), *arguments],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )

    def create_attachment_tools(self, rollout_paths):
        tool_directory = self.home / "fake-tools"
        tool_directory.mkdir(exist_ok=True)
        lsof = tool_directory / "lsof"
        lsof_lines = ["#!/usr/bin/env python3", "print('p123')", "print('ccodex')"]
        lsof_lines.extend(
            f"print({('n' + str(path.resolve()))!r})" for path in rollout_paths
        )
        lsof.write_text("\n".join(lsof_lines) + "\n")
        ps = tool_directory / "ps"
        ps.write_text("#!/usr/bin/env python3\nprint(' 123 ttys001')\n")
        lsof.chmod(0o755)
        ps.chmod(0o755)
        return tool_directory

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


if __name__ == "__main__":
    unittest.main()

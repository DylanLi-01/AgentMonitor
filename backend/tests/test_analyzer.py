import unittest

from app.analyzer import analyze_session
from app.models import SessionStatus


class AnalyzeSessionTest(unittest.TestCase):
    def test_error_has_highest_priority(self) -> None:
        result = analyze_session("Done\nTraceback from test", 0, True)
        self.assertEqual(result.status, SessionStatus.ERROR)

    def test_codex_status_footer_overrides_keyword_rules(self) -> None:
        tail = "\n".join(
            [
                "Earlier command failed but it was resolved.",
                "```yaml",
                "CODEX_STATUS:",
                "status: done",
                'summary: "Fixed the issue and tests passed."',
                "needs_user: false",
                'next_action: "none"',
                "```",
            ]
        )
        result = analyze_session(tail, 0, False)
        self.assertEqual(result.status, SessionStatus.DONE)
        self.assertIn("CODEX_STATUS=done", result.attention_reason or "")

    def test_codex_status_footer_supports_blocked(self) -> None:
        tail = "\n".join(
            [
                "CODEX_STATUS:",
                "status: blocked",
                'summary: "Waiting on an external service."',
                "needs_user: true",
                'next_action: "Retry after service recovers."',
            ]
        )
        result = analyze_session(tail, 0, False)
        self.assertEqual(result.status, SessionStatus.BLOCKED)
        self.assertIn("needs user", result.attention_reason or "")

    def test_codex_status_footer_supports_partial(self) -> None:
        tail = "\n".join(
            [
                "CODEX_STATUS:",
                "status: partial",
                'summary: "Implemented code but tests were unavailable."',
                "needs_user: false",
                'next_action: "Run tests when CI is back."',
            ]
        )
        result = analyze_session(tail, 0, False)
        self.assertEqual(result.status, SessionStatus.PARTIAL)

    def test_needs_input_beats_done(self) -> None:
        result = analyze_session("Tests passed\nShould I update schema?", 0, False)
        self.assertEqual(result.status, SessionStatus.NEEDS_INPUT)

    def test_changed_output_is_working(self) -> None:
        result = analyze_session("Editing files", 3, True)
        self.assertEqual(result.status, SessionStatus.WORKING)

    def test_stale_working_keyword_is_idle(self) -> None:
        result = analyze_session("Running tests", 130, False)
        self.assertEqual(result.status, SessionStatus.IDLE)

    def test_idle_after_threshold(self) -> None:
        result = analyze_session("No changes", 130, False)
        self.assertEqual(result.status, SessionStatus.IDLE)

    def test_old_error_outside_signal_window_is_ignored(self) -> None:
        tail = "fatal: old git failure\n" + "\n".join(
            f"recent harmless line {index}" for index in range(20)
        )
        result = analyze_session(tail, 0, False)
        self.assertEqual(result.status, SessionStatus.UNKNOWN)

    def test_old_error_outside_signal_window_does_not_beat_changed_output(self) -> None:
        tail = "Traceback from earlier\n" + "\n".join(
            f"recent harmless line {index}" for index in range(20)
        )
        result = analyze_session(tail, 0, True)
        self.assertEqual(result.status, SessionStatus.WORKING)

    def test_broken_pipe_traceback_is_ignored(self) -> None:
        tail = "\n".join(
            [
                "Traceback (most recent call last):",
                'File "/usr/lib/python3.10/http/server.py", line 539, in flush_headers',
                "self.wfile.write(b''.join(self._headers_buffer))",
                "BrokenPipeError: [Errno 32] Broken pipe",
                '127.0.0.1 - "GET /api/runs HTTP/1.1" 200 -',
            ]
        )
        result = analyze_session(tail, 0, False)
        self.assertEqual(result.status, SessionStatus.UNKNOWN)

    def test_recent_real_error_still_counts(self) -> None:
        result = analyze_session("Running tests\nRuntimeError: boom", 0, False)
        self.assertEqual(result.status, SessionStatus.ERROR)

    def test_negated_error_phrase_is_ignored(self) -> None:
        result = analyze_session("目前没看到 fatal error，只有 warning", 0, False)
        self.assertEqual(result.status, SessionStatus.UNKNOWN)

    def test_zero_failed_metric_is_ignored(self) -> None:
        result = analyze_session("remaining 4592 shards, current failed=0", 0, False)
        self.assertEqual(result.status, SessionStatus.UNKNOWN)

    def test_curl_failed_writing_body_is_ignored(self) -> None:
        result = analyze_session("curl: (23) Failed writing body", 0, False)
        self.assertEqual(result.status, SessionStatus.UNKNOWN)


if __name__ == "__main__":
    unittest.main()

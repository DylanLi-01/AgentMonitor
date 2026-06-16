import unittest

from app.analyzer import analyze_session
from app.models import SessionStatus


class AnalyzeSessionTest(unittest.TestCase):
    def test_codex_status_yaml_footer_sets_status(self) -> None:
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

    def test_codex_status_json_footer_sets_status(self) -> None:
        tail = "\n".join(
            [
                "Final response:",
                "```json",
                "{",
                '  "CODEX_STATUS": {',
                '    "status": "blocked",',
                '    "summary": "Waiting on an external service.",',
                '    "needs_user": true,',
                '    "next_action": "Retry after service recovers."',
                "  }",
                "}",
                "```",
            ]
        )

        result = analyze_session(tail, 0, False)

        self.assertEqual(result.status, SessionStatus.BLOCKED)
        self.assertIn("needs user", result.attention_reason or "")
        self.assertIn("Retry after service recovers", result.attention_reason or "")

    def test_flat_json_footer_sets_status(self) -> None:
        tail = "\n".join(
            [
                "Final status:",
                '{"status":"partial","summary":"Tests unavailable","needs_user":false,"next_action":"Run CI later."}',
            ]
        )

        result = analyze_session(tail, 0, False)

        self.assertEqual(result.status, SessionStatus.PARTIAL)
        self.assertIn("Tests unavailable", result.attention_reason or "")

    def test_keywords_do_not_set_error_needs_input_or_done(self) -> None:
        tail = "\n".join(
            [
                "RuntimeError: boom",
                "Tests passed",
                "Should I update schema?",
                "Done",
            ]
        )

        result = analyze_session(tail, 0, False)

        self.assertEqual(result.status, SessionStatus.UNKNOWN)
        self.assertIsNone(result.attention_reason)

    def test_changed_output_without_structured_status_is_working(self) -> None:
        result = analyze_session("Editing files\nRuntimeError: old output", 3, True)

        self.assertEqual(result.status, SessionStatus.WORKING)

    def test_idle_after_threshold_without_structured_status(self) -> None:
        result = analyze_session("Running tests", 130, False)

        self.assertEqual(result.status, SessionStatus.IDLE)
        self.assertEqual(result.attention_reason, "No output change for 120s")

    def test_structured_status_overrides_activity_state(self) -> None:
        tail = "\n".join(
            [
                "Still printing logs",
                "CODEX_STATUS:",
                "status: done",
                'summary: "Finished and verified."',
                "needs_user: false",
                'next_action: "none"',
            ]
        )

        result = analyze_session(tail, 0, True)

        self.assertEqual(result.status, SessionStatus.DONE)

    def test_invalid_json_does_not_fall_back_to_keywords(self) -> None:
        tail = "```json\n{\"status\":\"error\"\n```\nTraceback from a resolved failure"

        result = analyze_session(tail, 0, False)

        self.assertEqual(result.status, SessionStatus.UNKNOWN)


if __name__ == "__main__":
    unittest.main()

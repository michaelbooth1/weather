import unittest

from weather.operations.power import (
    ES_AWAYMODE_REQUIRED,
    ES_CONTINUOUS,
    ES_SYSTEM_REQUIRED,
    SystemSleepInhibitor,
)


class TestPowerManagement(unittest.TestCase):
    def test_non_windows_is_noop(self):
        inhibitor = SystemSleepInhibitor("test worker", platform_name="posix")

        status = inhibitor.start()
        released = inhibitor.stop()

        self.assertEqual(status["status"], "not_supported")
        self.assertFalse(status["active"])
        self.assertEqual(released["status"], "inactive")

    def test_windows_sleep_inhibitor_sets_and_clears_execution_state(self):
        calls = []

        def fake_set_state(flags):
            calls.append(flags)
            return 7

        inhibitor = SystemSleepInhibitor(
            "test worker",
            set_thread_execution_state=fake_set_state,
            platform_name="nt",
        )

        status = inhibitor.start()
        released = inhibitor.stop()

        self.assertEqual(calls, [ES_CONTINUOUS | ES_SYSTEM_REQUIRED, ES_CONTINUOUS])
        self.assertEqual(status["status"], "active")
        self.assertTrue(status["active"])
        self.assertEqual(released["status"], "released")

    def test_away_mode_is_explicit(self):
        calls = []

        inhibitor = SystemSleepInhibitor(
            "test worker",
            away_mode=True,
            set_thread_execution_state=lambda flags: calls.append(flags) or 1,
            platform_name="nt",
        )

        inhibitor.start()
        inhibitor.stop()

        self.assertEqual(calls[0], ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED)

    def test_failed_start_does_not_clear_unowned_state(self):
        calls = []

        inhibitor = SystemSleepInhibitor(
            "test worker",
            set_thread_execution_state=lambda flags: calls.append(flags) or 0,
            platform_name="nt",
        )

        status = inhibitor.start()
        released = inhibitor.stop()

        self.assertEqual(calls, [ES_CONTINUOUS | ES_SYSTEM_REQUIRED])
        self.assertEqual(status["status"], "failed")
        self.assertFalse(status["active"])
        self.assertEqual(released["status"], "inactive")


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import populate_live


class PopulateLiveSafetyTests(unittest.TestCase):
    def test_requires_exact_remote_host_confirmation(self):
        url = "postgresql://loader:secret@db.example.com:5432/app"
        with self.assertRaisesRegex(ValueError, "confirm-host db.example.com"):
            populate_live._validate_live_database_url(
                url,
                confirmed_host="other.example.com",
            )

        target = populate_live._validate_live_database_url(
            url,
            confirmed_host="db.example.com",
        )
        self.assertEqual(target.host, "db.example.com")
        self.assertEqual(target.database, "app")

    def test_refuses_local_database(self):
        with self.assertRaisesRegex(ValueError, "refuses local"):
            populate_live._validate_live_database_url(
                "postgresql://user:password@localhost:5432/spike",
                confirmed_host="localhost",
            )

    def test_bounds_and_sorts_recent_announcements(self):
        now = datetime(2026, 8, 21, tzinfo=timezone.utc)
        announcements = [
            SimpleNamespace(date=now - timedelta(days=2), title="middle"),
            SimpleNamespace(date=now - timedelta(days=31), title="old"),
            SimpleNamespace(date=now - timedelta(days=1), title="new"),
            SimpleNamespace(date=now + timedelta(days=1), title="future"),
        ]
        result = populate_live._bounded_announcements(
            announcements,
            lookback_days=30,
            now=now,
        )
        self.assertEqual([item.title for item in result], ["new", "middle"])

    def test_redacts_database_urls_from_errors(self):
        error = RuntimeError("failed postgresql://user:secret@db.example.com:5432/app")
        safe = populate_live._safe_error(error)
        self.assertNotIn("secret", safe)
        self.assertIn("[database-url-redacted]", safe)


if __name__ == "__main__":
    unittest.main()

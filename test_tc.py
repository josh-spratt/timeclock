"""Tests for tc. Run with:  python3 -m unittest -v test_tc"""

import io
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, time, timedelta
from pathlib import Path

from tc import Action, CommandLine, Punch, PunchError, PunchStore, TimeClock, WorkDay, time_today

WEDNESDAY = date(2026, 11, 11)


def at(hour, minute=0, day=WEDNESDAY):
    return datetime(day.year, day.month, day.day, hour, minute)


class FakeClock:
    """Stands in for the current time so tests control it."""

    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class ActionTest(unittest.TestCase):
    def test_allowed_sequences(self):
        self.assertTrue(Action.OUT.can_be_followed_by(Action.IN))
        self.assertTrue(Action.IN.can_be_followed_by(Action.LUNCH))
        self.assertTrue(Action.IN.can_be_followed_by(Action.OUT))
        self.assertTrue(Action.LUNCH.can_be_followed_by(Action.IN))
        self.assertTrue(Action.LUNCH.can_be_followed_by(Action.OUT))

    def test_disallowed_sequences(self):
        for action in Action:
            with self.subTest(action=action):
                self.assertFalse(action.can_be_followed_by(action))
        self.assertFalse(Action.OUT.can_be_followed_by(Action.LUNCH))


class WorkDayTest(unittest.TestCase):
    def make_day(self, *punches, day=WEDNESDAY):
        return WorkDay(day, [Punch(at(h, m, day), action) for h, m, action in punches])

    def test_day_with_lunch(self):
        day = self.make_day(
            (8, 0, Action.IN), (12, 0, Action.LUNCH), (12, 45, Action.IN), (17, 15, Action.OUT)
        )
        self.assertEqual(day.time_worked(now=at(20)), timedelta(hours=8, minutes=30))

    def test_open_shift_today_counts_up_to_now(self):
        day = self.make_day((8, 0, Action.IN))
        self.assertEqual(day.time_worked(now=at(10, 30)), timedelta(hours=2, minutes=30))

    def test_open_shift_on_a_past_day_is_not_extended(self):
        day = self.make_day((8, 0, Action.IN), (12, 0, Action.LUNCH), (13, 0, Action.IN))
        tomorrow = at(9, day=WEDNESDAY + timedelta(days=1))
        self.assertEqual(day.time_worked(now=tomorrow), timedelta(hours=4))

    def test_time_at_lunch_is_not_work(self):
        day = self.make_day((8, 0, Action.IN), (12, 0, Action.LUNCH))
        self.assertEqual(day.time_worked(now=at(12, 40)), timedelta(hours=4))

    def test_empty_day(self):
        self.assertEqual(WorkDay(WEDNESDAY).time_worked(now=at(12)), timedelta())


class PunchStoreTest(unittest.TestCase):
    def setUp(self):
        self.store = PunchStore(":memory:")
        self.addCleanup(self.store.close)

    def test_empty_store_has_no_latest(self):
        self.assertIsNone(self.store.latest())

    def test_round_trip(self):
        punch = Punch(at(8, 5), Action.IN)
        self.store.add(punch)
        self.assertEqual(self.store.latest(), punch)

    def test_latest_is_by_time_not_insertion_order(self):
        self.store.add(Punch(at(12), Action.LUNCH))
        self.store.add(Punch(at(8), Action.IN))
        self.assertEqual(self.store.latest(), Punch(at(12), Action.LUNCH))

    def test_between_includes_start_and_excludes_end(self):
        thursday = WEDNESDAY + timedelta(days=1)
        self.store.add(Punch(at(23, 59, day=WEDNESDAY - timedelta(days=1)), Action.OUT))
        self.store.add(Punch(at(0, 0), Action.IN))
        self.store.add(Punch(at(23, 59), Action.OUT))
        self.store.add(Punch(at(0, 0, day=thursday), Action.IN))

        punches = self.store.between(WEDNESDAY, thursday)
        self.assertEqual([p.when for p in punches], [at(0, 0), at(23, 59)])

    def test_schema_rejects_unknown_actions(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.store._db.execute(
                "INSERT INTO punches (punched_at, action) VALUES ('2026-11-11T08:00', 'nap')"
            )

    def test_punches_survive_reopening(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "punches.db"
            with PunchStore(path) as store:
                store.add(Punch(at(8), Action.IN))
            with PunchStore(path) as store:
                self.assertEqual(store.latest(), Punch(at(8), Action.IN))


class TimeClockTest(unittest.TestCase):
    def setUp(self):
        self.store = PunchStore(":memory:")
        self.addCleanup(self.store.close)
        self.now = FakeClock(at(8))
        self.clock = TimeClock(self.store, now=self.now)

    def work_until(self, hour, minute=0):
        self.now.now = at(hour, minute)

    def test_starts_clocked_out(self):
        self.assertIs(self.clock.state, Action.OUT)

    def test_full_day(self):
        self.clock.punch(Action.IN)
        self.work_until(12)
        self.clock.punch(Action.LUNCH)
        self.work_until(12, 45)
        self.clock.punch(Action.IN)
        self.work_until(17, 15)
        self.clock.punch(Action.OUT)

        self.assertIs(self.clock.state, Action.OUT)
        today = self.clock.day(WEDNESDAY)
        self.assertEqual(len(today.punches), 4)
        self.assertEqual(today.time_worked(self.clock.now()), timedelta(hours=8, minutes=30))

    def test_punch_uses_the_current_time_by_default(self):
        self.assertEqual(self.clock.punch(Action.IN).when, at(8))

    def test_backfilled_punch(self):
        self.work_until(9)
        self.assertEqual(self.clock.punch(Action.IN, at=at(8, 15)).when, at(8, 15))

    def test_rejects_disallowed_sequence(self):
        with self.assertRaisesRegex(PunchError, "clocked out"):
            self.clock.punch(Action.LUNCH)
        self.clock.punch(Action.IN)
        with self.assertRaisesRegex(PunchError, "clocked in"):
            self.clock.punch(Action.IN)
        self.assertEqual(len(self.clock.day(WEDNESDAY).punches), 1)

    def test_rejects_punch_before_the_last_one(self):
        self.work_until(9)
        self.clock.punch(Action.IN)
        with self.assertRaisesRegex(PunchError, "before your last punch"):
            self.clock.punch(Action.OUT, at=at(8, 30))

    def test_rejects_future_punch(self):
        with self.assertRaisesRegex(PunchError, "hasn't happened yet"):
            self.clock.punch(Action.IN, at=at(9))

    def test_week_runs_monday_to_sunday(self):
        week = self.clock.week(WEDNESDAY)
        self.assertEqual([day.date.strftime("%a") for day in week],
                         ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
        self.assertEqual(week[0].date, date(2026, 11, 9))

    def test_week_groups_punches_and_totals_them(self):
        monday, tuesday = date(2026, 11, 9), date(2026, 11, 10)
        next_monday = date(2026, 11, 16)
        for day, start, end in [(monday, 9, 17), (tuesday, 9, 16), (next_monday, 9, 10)]:
            self.store.add(Punch(at(start, day=day), Action.IN))
            self.store.add(Punch(at(end, day=day), Action.OUT))

        week = self.clock.week(WEDNESDAY)
        self.assertEqual(len(week[0].punches), 2)
        self.assertEqual(len(week[1].punches), 2)
        self.assertEqual(self.clock.total_worked(week), timedelta(hours=15))


class CommandLineTest(unittest.TestCase):
    def setUp(self):
        self.store = PunchStore(":memory:")
        self.addCleanup(self.store.close)
        self.now = FakeClock(at(8))
        self.cli = CommandLine(TimeClock(self.store, now=self.now))

    def run_command(self, command, when=None):
        output = io.StringIO()
        with redirect_stdout(output):
            self.cli.run(command, when)
        return output.getvalue()

    def test_punch_confirms(self):
        self.assertEqual(self.run_command("in"), "08:00  Clocked in.\n")
        self.now.now = at(12)
        self.assertEqual(self.run_command("lunch"), "12:00  At lunch.\n")

    def test_today(self):
        self.run_command("in")
        self.now.now = at(10, 30)
        output = self.run_command("today")
        self.assertIn("You're clocked in.", output)
        self.assertIn("08:00  in", output)
        self.assertIn("Today:     2h 30m", output)
        self.assertIn("This week: 2h 30m", output)

    def test_week(self):
        self.run_command("in")
        self.now.now = at(16)
        self.run_command("out")
        output = self.run_command("week")
        self.assertIn("Wed Nov 11   8h 00m", output)
        self.assertIn("Mon Nov 09   0h 00m", output)
        self.assertIn("Total        8h 00m", output)


class TimeTodayTest(unittest.TestCase):
    def test_parses_hours_and_minutes_as_today(self):
        self.assertEqual(time_today("8:30"), datetime.combine(date.today(), time(8, 30)))

    def test_rejects_invalid_times(self):
        for text in ["25:00", "8", "noon"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                time_today(text)


if __name__ == "__main__":
    unittest.main()

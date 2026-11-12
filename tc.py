#!/usr/bin/env python3
"""A simple time clock.

    tc in       start the day, or come back from lunch
    tc lunch    step out for lunch
    tc out      done for the day
    tc          show today's punches and totals
    tc week     show this week, day by day

Add --at HH:MM to record a punch you forgot, e.g. `tc out --at 17:30`.
Punches are saved in a SQLite database at ~/.timeclock.db.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional

DEFAULT_DB = Path(os.environ.get("TIMECLOCK_DB", Path.home() / ".timeclock.db"))


def current_minute() -> datetime:
    return datetime.now().replace(second=0, microsecond=0)


class Action(Enum):
    IN = "in"
    LUNCH = "lunch"
    OUT = "out"

    @property
    def description(self) -> str:
        return {
            Action.IN: "clocked in",
            Action.LUNCH: "at lunch",
            Action.OUT: "clocked out",
        }[self]

    def can_be_followed_by(self, other: Action) -> bool:
        """After clocking out you can only clock in; otherwise anything but a repeat."""
        if self is Action.OUT:
            return other is Action.IN
        return other is not self


@dataclass(frozen=True)
class Punch:
    when: datetime
    action: Action


class PunchError(Exception):
    """A punch that doesn't make sense, like clocking in twice."""


class PunchStore:
    """Keeps punches in a SQLite database."""

    SCHEMA = """
        CREATE TABLE IF NOT EXISTS punches (
            id         INTEGER PRIMARY KEY,
            punched_at TEXT NOT NULL,
            action     TEXT NOT NULL CHECK (action IN ('in', 'lunch', 'out'))
        );
        CREATE INDEX IF NOT EXISTS punches_by_time ON punches (punched_at);
    """

    def __init__(self, path: Path):
        self._db = sqlite3.connect(path)
        self._db.executescript(self.SCHEMA)

    def __enter__(self) -> PunchStore:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()

    def add(self, punch: Punch) -> None:
        with self._db:  # commits on success, rolls back on error
            self._db.execute(
                "INSERT INTO punches (punched_at, action) VALUES (?, ?)",
                (self._encode(punch.when), punch.action.value),
            )

    def latest(self) -> Optional[Punch]:
        row = self._db.execute(
            "SELECT punched_at, action FROM punches ORDER BY punched_at DESC, id DESC LIMIT 1"
        ).fetchone()
        return self._decode(row) if row else None

    def between(self, start: date, end: date) -> List[Punch]:
        """Punches from the start of `start` up to, but not including, `end`."""
        rows = self._db.execute(
            "SELECT punched_at, action FROM punches"
            " WHERE punched_at >= ? AND punched_at < ? ORDER BY punched_at, id",
            (start.isoformat(), end.isoformat()),
        )
        return [self._decode(row) for row in rows]

    # Timestamps are stored as ISO text ("2026-11-11T08:00"), which sorts by time.
    @staticmethod
    def _encode(when: datetime) -> str:
        return when.isoformat(timespec="minutes")

    @staticmethod
    def _decode(row: tuple) -> Punch:
        punched_at, action = row
        return Punch(datetime.fromisoformat(punched_at), Action(action))


@dataclass
class WorkDay:
    date: date
    punches: List[Punch] = field(default_factory=list)

    def time_worked(self, now: datetime) -> timedelta:
        """Time between each clock-in and the lunch or clock-out that follows it."""
        total = timedelta()
        clocked_in_at = None
        for punch in self.punches:
            if punch.action is Action.IN:
                clocked_in_at = punch.when
            elif clocked_in_at:
                total += punch.when - clocked_in_at
                clocked_in_at = None
        if clocked_in_at and self.date == now.date():
            total += now - clocked_in_at
        return total


class TimeClock:
    """The rules for punching in and out, and for reading back your hours."""

    def __init__(self, store: PunchStore, now: Callable[[], datetime] = current_minute):
        self._store = store
        self._now = now

    def now(self) -> datetime:
        return self._now()

    @property
    def state(self) -> Action:
        latest = self._store.latest()
        return latest.action if latest else Action.OUT

    def punch(self, action: Action, at: Optional[datetime] = None) -> Punch:
        when = at or self.now()
        latest = self._store.latest()
        state = latest.action if latest else Action.OUT

        if not state.can_be_followed_by(action):
            raise PunchError(f"You're {state.description}, so `tc {action.value}` doesn't apply right now.")
        if latest and when < latest.when:
            raise PunchError(f"{when:%H:%M} is before your last punch ({latest.when:%H:%M}).")
        if when > self.now():
            raise PunchError(f"{when:%H:%M} hasn't happened yet.")

        punch = Punch(when, action)
        self._store.add(punch)
        return punch

    def day(self, day: date) -> WorkDay:
        return WorkDay(day, self._store.between(day, day + timedelta(days=1)))

    def week(self, containing: date) -> List[WorkDay]:
        """Monday through Sunday of the week that includes `containing`."""
        monday = containing - timedelta(days=containing.weekday())
        days = {monday + timedelta(days=i): WorkDay(monday + timedelta(days=i)) for i in range(7)}
        for punch in self._store.between(monday, monday + timedelta(days=7)):
            days[punch.when.date()].punches.append(punch)
        return list(days.values())

    def total_worked(self, days: List[WorkDay]) -> timedelta:
        now = self.now()
        return sum((day.time_worked(now) for day in days), timedelta())


class CommandLine:
    """Turns commands into time clock calls, and results into text."""

    def __init__(self, clock: TimeClock):
        self._clock = clock

    def run(self, command: str, at: Optional[datetime] = None) -> None:
        if command in {action.value for action in Action}:
            self.punch(Action(command), at)
        elif command == "week":
            self.show_week()
        else:
            self.show_today()

    def punch(self, action: Action, at: Optional[datetime]) -> None:
        punch = self._clock.punch(action, at)
        print(f"{punch.when:%H:%M}  {action.description.capitalize()}.")

    def show_today(self) -> None:
        now = self._clock.now()
        today = self._clock.day(now.date())

        print(f"You're {self._clock.state.description}.\n")
        for punch in today.punches:
            print(f"  {punch.when:%H:%M}  {punch.action.value}")
        print(f"\nToday:     {self._duration(today.time_worked(now))}")
        print(f"This week: {self._duration(self._clock.total_worked(self._clock.week(now.date())))}")

    def show_week(self) -> None:
        now = self._clock.now()
        week = self._clock.week(now.date())

        for day in week:
            print(f"  {day.date:%a %b %d}   {self._duration(day.time_worked(now))}")
        print(f"\n  Total        {self._duration(self._clock.total_worked(week))}")

    @staticmethod
    def _duration(duration: timedelta) -> str:
        hours, minutes = divmod(int(duration.total_seconds()) // 60, 60)
        return f"{hours}h {minutes:02d}m"


def time_today(text: str) -> datetime:
    """Parse 'HH:MM' as a time today (used for --at)."""
    clock_time = datetime.strptime(text, "%H:%M").time()
    return datetime.combine(date.today(), clock_time)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", nargs="?", default="today",
                        choices=[action.value for action in Action] + ["today", "week"])
    parser.add_argument("--at", type=time_today, metavar="HH:MM",
                        help="record the punch at this time instead of now")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    with PunchStore(DEFAULT_DB) as store:
        try:
            CommandLine(TimeClock(store)).run(args.command, args.at)
        except PunchError as error:
            print(error, file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

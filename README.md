# timeclock

A simple command-line time clock. Python 3.8+ standard library only, stores
punches in a local SQLite database, and makes no network calls.

```
tc in       start the day, or come back from lunch
tc lunch    step out for lunch
tc out      done for the day
tc          show today's punches and totals
tc week     show this week, day by day
```

Add `--at HH:MM` to record a punch you forgot, e.g. `tc out --at 17:30`.

Punches are saved to `~/.timeclock.db` (set `TIMECLOCK_DB` to use another path).

## Running it

```sh
python3 tc.py in
```

Or make it a command: `ln -s "$PWD/tc.py" ~/.local/bin/tc`

## Tests

```sh
python3 -m unittest -v test_tc
```

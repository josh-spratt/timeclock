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

## Install

You need Python 3.8 or newer. Check with `python3 --version` (on Windows, `py --version`).

### macOS / Linux

```sh
git clone https://github.com/josh-spratt/timeclock.git ~/timeclock
mkdir -p ~/.local/bin
ln -s ~/timeclock/tc.py ~/.local/bin/tc
```

`~/.local/bin` isn't on your PATH by default on macOS, so add it once:

```sh
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

Now `tc` works from any folder. To update later: `git -C ~/timeclock pull`.

No git on your work computer? Download just the script instead of cloning:

```sh
mkdir -p ~/.local/bin
curl -fsSL https://raw.githubusercontent.com/josh-spratt/timeclock/main/tc.py -o ~/.local/bin/tc
chmod +x ~/.local/bin/tc
```

### Windows

1. Save [`tc.py`](https://raw.githubusercontent.com/josh-spratt/timeclock/main/tc.py)
   into a folder such as `%USERPROFILE%\timeclock`.
2. In that folder, create a file named `tc.cmd` containing this one line:

   ```bat
   @py "%~dp0tc.py" %*
   ```

3. Add the folder to your PATH: open Start, search for
   **Edit environment variables for your account**, select **Path**, click **Edit**,
   then **New**, and paste the folder's path.
4. Open a new terminal. `tc` now works from anywhere.

## Tests

```sh
python3 -m unittest -v test_tc
```

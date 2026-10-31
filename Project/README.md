# Process Monitor

A C and GTK 3 desktop application for launching real child processes and reporting how each one terminates. It uses POSIX process and signal APIs and keeps GTK responsive while commands run.

## Features

- Dashboard with live launched, running, successful, and signal-terminated process counts.
- Command execution with captured stdout and stderr, PID, exit status, signal, and core dump report.
- Live process history table with searchable records and export.
- Real normal, SIGTERM, and SIGKILL child-process tests.
- Searchable process history, completed-history clearing, and text export.
- Dark navy theme, responsive GTK layout, live clock, and project information page.
- Original terminal utility remains available as `make cli`.

## Architecture

- `src/main.c` starts the GUI.
- `src/gui.c` builds the GTK pages and manages the child process lifecycle, output capture, process history, and dashboard statistics.
- `src/gui.h` declares the GUI entry point.
- `resources/style.css` contains the visual theme. `resources/icons/` is reserved for optional icon assets.
- `main.c`, `process_manager.c`, `process_manager.h`, `signal_handler.c`, and `signal_handler.h` preserve the original terminal application.

The GUI creates a nonblocking self-pipe before installing its SIGCHLD handler. The handler only writes one notification byte. GLib watches the pipe and reaps children with `waitpid(-1, ..., WNOHANG)` in the GTK main loop. Each child gets a separate output pipe, and GLib watches it for stdout and stderr without blocking the interface. Commands are passed to `execvp("sh", ...)` so arguments and shell syntax work; only run commands you trust.

## Install dependencies

Ubuntu/Debian:

```sh
sudo apt update
sudo apt install build-essential pkg-config libgtk-3-dev
```

macOS with Homebrew:

```sh
brew install pkgconf gtk+3
```

## Build and run

```sh
cd Process-Termination-Messages
make
make run
```

`make` builds the GTK desktop application. `make run` builds if needed and launches it. `make clean` removes generated files.

To run the original terminal menu instead:

```sh
make cli
./process_monitor
```

## GUI smoke test

The GUI executable has an automated mode that launches actual children, captures `ls` output, checks exit codes 0 and 1, sends SIGTERM and SIGKILL to test children, checks that the GTK event loop remains active, and verifies there are no unreaped children:

```sh
make
./process_monitor_gui --self-test
```

The self-test opens the GTK window while it runs and exits with a nonzero status if a check fails.

## Notes

`WCOREDUMP()` is used when the platform provides it. Otherwise the history marks core dump detection as unsupported. Signal termination does not automatically imply that a core dump was created. GTK 3 development files and `pkg-config` are required to build the GUI.

import os
import platform
import pwd
import queue
import subprocess
import threading
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import ttk


COLORS = {
    "background": "#111b1a",
    "surface": "#192523",
    "surface_alt": "#202f2c",
    "line": "#34433f",
    "text": "#e7eee9",
    "muted": "#93a49c",
    "accent": "#a7d66d",
    "accent_dark": "#30472b",
    "orange": "#e4a76b",
}


PROCESS_STATES = {
    "R": "running",
    "S": "sleeping",
    "D": "disk sleep",
    "Z": "zombie",
    "T": "stopped",
    "t": "tracing stop",
    "X": "dead",
    "I": "idle",
}


def _process_state(state):
    return PROCESS_STATES.get(state[:1], state or "unknown")


def _elapsed_seconds(value):
    days = 0
    if "-" in value:
        day_part, value = value.split("-", 1)
        days = int(day_part)
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours, (minutes, seconds) = 0, parts
    else:
        hours, minutes, seconds = 0, 0, parts[0]
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _read_linux_processes():
    records = {}
    ticks_per_second = os.sysconf("SC_CLK_TCK")
    boot_time = 0
    try:
        with open("/proc/stat", encoding="ascii") as system_stat:
            for line in system_stat:
                if line.startswith("btime "):
                    boot_time = int(line.split()[1])
                    break
    except (OSError, ValueError):
        pass

    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            with open(f"/proc/{pid}/stat", encoding="utf-8") as process_stat:
                stat = process_stat.read()
            name_end = stat.rfind(")")
            name = stat[stat.find("(") + 1:name_end]
            fields = stat[name_end + 2:].split()
            state = fields[0]
            parent_pid = int(fields[1])
            started = boot_time + int(fields[19]) / ticks_per_second if boot_time else None

            user_id = None
            memory = 0
            threads = 0
            with open(f"/proc/{pid}/status", encoding="utf-8") as process_status:
                for line in process_status:
                    if line.startswith("Uid:"):
                        user_id = int(line.split()[1])
                    elif line.startswith("VmRSS:"):
                        memory = int(line.split()[1]) * 1024
                    elif line.startswith("Threads:"):
                        threads = int(line.split()[1])

            try:
                user = pwd.getpwuid(user_id).pw_name if user_id is not None else "-"
            except KeyError:
                user = str(user_id) if user_id is not None else "-"

            with open(f"/proc/{pid}/cmdline", "rb") as process_cmdline:
                command = process_cmdline.read().replace(b"\0", b" ").decode(errors="replace").strip()
            records[pid] = {
                "pid": pid,
                "ppid": parent_pid,
                "name": name or "Unknown",
                "user": user,
                "status": _process_state(state),
                "memory": memory,
                "started": started,
                "command": command or name,
                "threads": threads,
            }
        except (FileNotFoundError, ProcessLookupError, PermissionError, OSError, ValueError, IndexError):
            continue

    return records


def _read_ps_processes():
    result = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,user=,stat=,rss=,etime=,command="],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    records = {}
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 6)
        if len(fields) != 7:
            continue
        try:
            pid, parent_pid = int(fields[0]), int(fields[1])
            command = fields[6]
            name = os.path.basename(command.split(None, 1)[0]) if command else "Unknown"
            started = datetime.now() - timedelta(seconds=_elapsed_seconds(fields[5]))
            records[pid] = {
                "pid": pid,
                "ppid": parent_pid,
                "name": name,
                "user": fields[2],
                "status": _process_state(fields[3]),
                "memory": int(fields[4]) * 1024,
                "started": started.timestamp(),
                "command": command,
                "threads": 0,
            }
        except (ValueError, IndexError):
            continue
    return records


def read_processes():
    return _read_linux_processes() if platform.system() == "Linux" else _read_ps_processes()


def format_memory(byte_count):
    value = float(byte_count)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return "0 B"


class ProcessTreeVisualizer:
    def __init__(self, root):
        self.root = root
        self.root.title("Process Tree Visualizer")
        self.root.geometry("1260x790")
        self.root.minsize(900, 580)
        self.root.configure(bg=COLORS["background"])

        self.snapshots = queue.Queue()
        self.scanning = False
        self.auto_refresh = tk.BooleanVar(value=True)
        self.interval = tk.StringVar(value="2 seconds")
        self.query = tk.StringVar()
        self.selected_pid = None
        self.current_records = {}
        self.displayed_records = {}
        self.last_refresh = tk.StringVar(value="Waiting for first snapshot")

        self._configure_style()
        self._build_interface()
        self.query.trace_add("write", self._filter_changed)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self._start_scan()
        self.root.after(150, self._check_snapshot)

    def _configure_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "App.TFrame",
            background=COLORS["background"],
        )
        style.configure(
            "Panel.TFrame",
            background=COLORS["surface"],
        )
        style.configure(
            "Title.TLabel",
            background=COLORS["background"],
            foreground=COLORS["text"],
            font=("Avenir Next", 23, "bold"),
        )
        style.configure(
            "Eyebrow.TLabel",
            background=COLORS["background"],
            foreground=COLORS["accent"],
            font=("Menlo", 9, "bold"),
        )
        style.configure(
            "Muted.TLabel",
            background=COLORS["background"],
            foreground=COLORS["muted"],
            font=("Avenir Next", 10),
        )
        style.configure(
            "PanelTitle.TLabel",
            background=COLORS["surface"],
            foreground=COLORS["text"],
            font=("Avenir Next", 12, "bold"),
        )
        style.configure(
            "DetailKey.TLabel",
            background=COLORS["surface"],
            foreground=COLORS["muted"],
            font=("Avenir Next", 9),
        )
        style.configure(
            "DetailValue.TLabel",
            background=COLORS["surface"],
            foreground=COLORS["text"],
            font=("Menlo", 9),
        )
        style.configure(
            "TButton",
            background=COLORS["surface_alt"],
            foreground=COLORS["text"],
            borderwidth=0,
            padding=(12, 8),
            font=("Avenir Next", 10, "bold"),
        )
        style.map("TButton", background=[("active", COLORS["accent_dark"])])
        style.configure(
            "TCheckbutton",
            background=COLORS["background"],
            foreground=COLORS["text"],
            font=("Avenir Next", 10),
        )
        style.map("TCheckbutton", background=[("active", COLORS["background"])])
        style.configure(
            "TCombobox",
            fieldbackground=COLORS["surface"],
            background=COLORS["surface"],
            foreground=COLORS["text"],
            arrowcolor=COLORS["accent"],
            padding=6,
        )
        style.configure(
            "Treeview",
            background=COLORS["surface"],
            fieldbackground=COLORS["surface"],
            foreground=COLORS["text"],
            rowheight=27,
            borderwidth=0,
            font=("Menlo", 9),
        )
        style.configure(
            "Treeview.Heading",
            background=COLORS["surface_alt"],
            foreground=COLORS["muted"],
            relief="flat",
            font=("Avenir Next", 9, "bold"),
            padding=(8, 9),
        )
        style.map(
            "Treeview",
            background=[("selected", COLORS["accent_dark"])],
            foreground=[("selected", COLORS["text"])],
        )

    def _build_interface(self):
        shell = ttk.Frame(self.root, style="App.TFrame", padding=(28, 23, 28, 18))
        shell.pack(fill="both", expand=True)

        header = ttk.Frame(shell, style="App.TFrame")
        header.pack(fill="x")

        title_group = ttk.Frame(header, style="App.TFrame")
        title_group.pack(side="left", fill="y")
        ttk.Label(title_group, text="SYSTEMS / OBSERVABILITY", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(title_group, text="Process tree", style="Title.TLabel").pack(anchor="w", pady=(3, 0))

        self.platform_label = ttk.Label(
            header,
            text=f"LIVE SNAPSHOT  /  {platform.system().upper()}",
            style="Eyebrow.TLabel",
        )
        self.platform_label.pack(side="right", anchor="n", pady=(9, 0))

        toolbar = ttk.Frame(shell, style="App.TFrame")
        toolbar.pack(fill="x", pady=(20, 15))

        self.search_entry = tk.Entry(
            toolbar,
            textvariable=self.query,
            bg=COLORS["surface"],
            fg=COLORS["text"],
            insertbackground=COLORS["accent"],
            relief="flat",
            font=("Avenir Next", 11),
            highlightthickness=1,
            highlightbackground=COLORS["line"],
            highlightcolor=COLORS["accent"],
        )
        self.search_entry.pack(side="left", fill="x", expand=True, ipady=9, padx=(0, 12))
        self.search_entry.insert(0, "")
        ttk.Checkbutton(
            toolbar,
            text="Auto refresh",
            variable=self.auto_refresh,
            command=self._refresh_timing_changed,
        ).pack(side="left", padx=(0, 14))
        ttk.Combobox(
            toolbar,
            textvariable=self.interval,
            values=("1 second", "2 seconds", "5 seconds", "10 seconds"),
            state="readonly",
            width=11,
        ).pack(side="left", padx=(0, 10))
        ttk.Button(toolbar, text="Refresh now", command=self._start_scan).pack(side="left")

        overview = ttk.Frame(shell, style="App.TFrame")
        overview.pack(fill="x", pady=(0, 14))
        self.process_count = self._metric(overview, "PROCESSES", "--")
        self.visible_count = self._metric(overview, "IN VIEW", "--")
        self.snapshot_label = self._metric(overview, "LAST SNAPSHOT", "Waiting")

        content = ttk.Frame(shell, style="App.TFrame")
        content.pack(fill="both", expand=True)

        tree_panel = ttk.Frame(content, style="Panel.TFrame", padding=(0, 0, 0, 0))
        tree_panel.pack(side="left", fill="both", expand=True)
        columns = ("pid", "user", "state", "memory")
        self.tree = ttk.Treeview(tree_panel, columns=columns, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="PROCESS", anchor="w")
        self.tree.heading("pid", text="PID", anchor="e")
        self.tree.heading("user", text="OWNER", anchor="w")
        self.tree.heading("state", text="STATE", anchor="w")
        self.tree.heading("memory", text="RSS", anchor="e")
        self.tree.column("#0", width=250, minwidth=150, stretch=True)
        self.tree.column("pid", width=78, minwidth=65, anchor="e", stretch=False)
        self.tree.column("user", width=125, minwidth=75, stretch=False)
        self.tree.column("state", width=105, minwidth=75, stretch=False)
        self.tree.column("memory", width=95, minwidth=75, anchor="e", stretch=False)
        self.tree.tag_configure("root", foreground=COLORS["accent"], font=("Avenir Next", 10, "bold"))
        self.tree.tag_configure("zombie", foreground=COLORS["orange"])
        self.tree.bind("<<TreeviewSelect>>", self._selection_changed)
        self.tree.bind("<Double-1>", self._toggle_open)
        scrollbar = ttk.Scrollbar(tree_panel, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        detail = ttk.Frame(content, style="Panel.TFrame", padding=(18, 18, 18, 14), width=285)
        detail.pack(side="right", fill="y", padx=(14, 0))
        detail.pack_propagate(False)
        ttk.Label(detail, text="PROCESS DETAILS", style="PanelTitle.TLabel").pack(anchor="w")
        ttk.Label(
            detail,
            text="Select a process in the tree",
            style="DetailKey.TLabel",
            wraplength=245,
        ).pack(anchor="w", pady=(5, 17))

        self.detail_values = {}
        for key, label in (
            ("pid", "PID"),
            ("ppid", "PARENT PID"),
            ("status", "STATE"),
            ("user", "OWNER"),
            ("memory", "RESIDENT MEMORY"),
            ("threads", "THREADS"),
            ("started", "STARTED"),
        ):
            ttk.Label(detail, text=label, style="DetailKey.TLabel").pack(anchor="w", pady=(8, 2))
            value = ttk.Label(detail, text="-", style="DetailValue.TLabel", wraplength=245)
            value.pack(anchor="w")
            self.detail_values[key] = value

        ttk.Label(detail, text="COMMAND", style="DetailKey.TLabel").pack(anchor="w", pady=(15, 4))
        self.command_value = ttk.Label(
            detail,
            text="-",
            style="DetailValue.TLabel",
            wraplength=245,
            justify="left",
        )
        self.command_value.pack(anchor="w", fill="x")

        footer = ttk.Frame(shell, style="App.TFrame")
        footer.pack(fill="x", pady=(11, 0))
        ttk.Label(footer, textvariable=self.last_refresh, style="Muted.TLabel").pack(side="left")
        ttk.Label(footer, text="READ ONLY", style="Eyebrow.TLabel").pack(side="right")

    def _metric(self, parent, label, value):
        group = ttk.Frame(parent, style="App.TFrame")
        group.pack(side="left", padx=(0, 34))
        ttk.Label(group, text=label, style="Eyebrow.TLabel").pack(anchor="w")
        number = tk.Label(
            group,
            text=value,
            bg=COLORS["background"],
            fg=COLORS["text"],
            font=("Avenir Next", 15, "bold"),
        )
        number.pack(anchor="w", pady=(2, 0))
        return number

    def _start_scan(self):
        if self.scanning:
            return
        self.scanning = True

        def scan():
            try:
                self.snapshots.put((read_processes(), None))
            except Exception as error:
                self.snapshots.put((None, str(error)))

        threading.Thread(target=scan, daemon=True).start()

    def _check_snapshot(self):
        try:
            records, error = self.snapshots.get_nowait()
        except queue.Empty:
            self.root.after(150, self._check_snapshot)
            return

        self.scanning = False
        if error:
            self.last_refresh.set(f"Snapshot failed: {error}")
        else:
            self.current_records = records
            stamp = datetime.now().strftime("%H:%M:%S")
            self.last_refresh.set(f"Updated {stamp}")
            self.process_count.configure(text=f"{len(records):,}")
            self.snapshot_label.configure(text=stamp)
            self._render_tree()

        if self.auto_refresh.get():
            self.root.after(self._interval_ms(), self._start_scan)
        self.root.after(150, self._check_snapshot)

    def _interval_ms(self):
        seconds = int(self.interval.get().split()[0])
        return seconds * 1000

    def _refresh_timing_changed(self):
        if self.auto_refresh.get() and not self.scanning:
            self._start_scan()

    def _filter_changed(self, *_):
        if self.current_records:
            self._render_tree()

    def _render_tree(self):
        records = self.current_records
        query = self.query.get().strip().lower()
        visible = set(records)

        if query:
            visible.clear()
            for pid, record in records.items():
                searchable = " ".join(
                    (record["name"], str(pid), record["user"], record["command"])
                ).lower()
                if query in searchable:
                    current = pid
                    while current in records and current not in visible:
                        visible.add(current)
                        current = records[current]["ppid"]

        self.displayed_records = {pid: records[pid] for pid in visible}
        self.visible_count.configure(text=f"{len(visible):,}")

        open_pids = set()
        pending = list(self.tree.get_children(""))
        while pending:
            item = pending.pop()
            if item.isdigit() and self.tree.item(item, "open"):
                open_pids.add(int(item))
            pending.extend(self.tree.get_children(item))
        for item in self.tree.get_children(""):
            self.tree.delete(item)

        self.tree.insert(
            "",
            "end",
            iid="process-root",
            text=f"Running processes  ({len(records):,})",
            values=("", "", "", ""),
            tags=("root",),
            open=True,
        )

        children = {}
        for pid in visible:
            parent_pid = records[pid]["ppid"]
            parent = parent_pid if parent_pid in visible else "process-root"
            children.setdefault(parent, []).append(pid)

        for child_pids in children.values():
            child_pids.sort(key=lambda item: (records[item]["name"].lower(), item))

        stack = [("process-root", pid, 1) for pid in reversed(children.get("process-root", []))]
        while stack:
            parent, pid, depth = stack.pop()
            record = records[pid]
            tags = ("zombie",) if record["status"] == "zombie" else ()
            self.tree.insert(
                parent,
                "end",
                iid=str(pid),
                text=record["name"],
                values=(pid, record["user"], record["status"], format_memory(record["memory"])),
                tags=tags,
                open=pid in open_pids or depth == 1,
            )
            for child_pid in reversed(children.get(pid, [])):
                stack.append((str(pid), child_pid, depth + 1))

        if self.selected_pid in self.displayed_records:
            selected = str(self.selected_pid)
            self.tree.selection_set(selected)
            self._show_details(self.selected_pid)
        else:
            self.selected_pid = None
            self._clear_details()

    def _selection_changed(self, _event=None):
        selection = self.tree.selection()
        if not selection or selection[0] == "process-root":
            self.selected_pid = None
            self._clear_details()
            return
        self.selected_pid = int(selection[0])
        self._show_details(self.selected_pid)

    def _show_details(self, pid):
        record = self.displayed_records.get(pid)
        if not record:
            return
        parent = self.current_records.get(record["ppid"])
        parent_pid = record["ppid"] if parent else f"{record['ppid']} (not visible)"
        started = record["started"]
        values = {
            "pid": pid,
            "ppid": parent_pid,
            "status": record["status"],
            "user": record["user"],
            "memory": format_memory(record["memory"]),
            "threads": record["threads"],
            "started": datetime.fromtimestamp(started).strftime("%Y-%m-%d %H:%M:%S") if started else "-",
        }
        for key, value in values.items():
            self.detail_values[key].configure(text=str(value))
        self.command_value.configure(text=record["command"] or record["name"])

    def _clear_details(self):
        for value in self.detail_values.values():
            value.configure(text="-")
        self.command_value.configure(text="-")

    def _toggle_open(self, event):
        item = self.tree.identify_row(event.y)
        if item and item != "process-root":
            self.tree.item(item, open=not self.tree.item(item, "open"))

    def _close(self):
        self.root.destroy()


def main():
    root = tk.Tk()
    ProcessTreeVisualizer(root)
    root.mainloop()


if __name__ == "__main__":
    main()
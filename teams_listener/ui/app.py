"""Main Tk window: Start/Stop, mic mute, meters, transcription progress, recent meetings, settings."""
from __future__ import annotations

import logging
import os
import queue
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..audio import devices
from ..audio.recorder import Recorder
from ..config import ALLOWED_MODELS, Settings, load_settings, save_settings
from ..hotkeys import MuteHotkeys
from ..meeting import MeetingMeta, list_meetings, make_meeting_dir, read_meta, write_meta
from ..transcribe.pipeline import TranscriptionQueue
from .status import mic_display
from .tray import Tray

log = logging.getLogger(__name__)
DEFAULT_MIC_LABEL = "Default communications mic"


def _fmt_eta(eta: float | None) -> str:
    if eta is None:
        return "estimating…"
    m = int(eta // 60)
    return f"~{m} min left" if m >= 1 else "<1 min left"


class App:
    def __init__(self):
        self.settings: Settings = load_settings()
        self.root = tk.Tk()
        self.root.title("Teams Listener")
        self.root.geometry("520x560")
        self.root.minsize(460, 480)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._ui: queue.Queue = queue.Queue()

        self.recorder: Recorder | None = None
        self.folder: Path | None = None
        self.meta: MeetingMeta | None = None
        self.rec_started = 0.0
        self.transcribing: dict[Path, float] = {}
        self.hotkeys: MuteHotkeys | None = None
        self._shown_mic: str | None = None

        self.queue = TranscriptionQueue(
            None, lambda: self.settings,
            on_progress=lambda f, frac, eta: self.call(self._on_progress, f, frac, eta),
            on_done=lambda f, p: self.call(self._on_done, f, p),
            on_error=lambda f, e: self.call(self._on_error, f, e),
        )
        self.tray = Tray(
            on_show=lambda: self.call(self.show),
            on_start_stop=lambda: self.call(self.toggle_recording),
            on_mute=lambda: self.call(self.toggle_mute),
            on_quit=lambda: self.call(self.quit),
            is_recording=lambda: self.recorder is not None,
            is_muted=lambda: bool(self.recorder and self.recorder.muted),
        )
        self._build()
        self._restart_hotkeys()
        self.tray.start()
        self.refresh_meetings()
        self.root.after(100, self._tick)

    # ---- thread marshalling ------------------------------------------
    def call(self, fn, *args) -> None:
        self._ui.put((fn, args))

    def _tick(self) -> None:
        try:
            while True:
                fn, args = self._ui.get_nowait()
                try:
                    fn(*args)
                except Exception:  # noqa: BLE001
                    log.exception("UI callback failed")
        except queue.Empty:
            pass
        if self.recorder is not None:
            lv = self.recorder.levels()
            self.meter_others["value"] = min(100, lv["others"] * 300)
            self.meter_me["value"] = min(100, lv["me"] * 300)
            if self.recorder.mic_name != self._shown_mic:
                self._render_mic()
            el = int(time.monotonic() - self.rec_started)
            self.elapsed.set(f"{el // 3600:02d}:{el % 3600 // 60:02d}:{el % 60:02d}")
        self.root.after(100, self._tick)

    # ---- layout --------------------------------------------------------
    def _build(self) -> None:
        pad = {"padx": 10, "pady": 4}
        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Meeting title (optional):").pack(anchor="w")
        self.title_var = tk.StringVar()
        self.title_entry = ttk.Entry(top, textvariable=self.title_var)
        self.title_entry.pack(fill="x")

        ctl = ttk.Frame(self.root)
        ctl.pack(fill="x", **pad)
        self.start_btn = ttk.Button(ctl, text="● Start recording", command=self.toggle_recording)
        self.start_btn.pack(side="left")
        self.elapsed = tk.StringVar(value="")
        ttk.Label(ctl, textvariable=self.elapsed, font=("Segoe UI", 12)).pack(side="left", padx=12)
        ttk.Button(ctl, text="Settings", command=self.open_settings).pack(side="right")

        self.mic_btn = tk.Button(self.root, text="MIC: —", font=("Segoe UI", 16, "bold"), height=2,
                                 state="disabled", command=self.toggle_mute, relief="raised", bg="#dddddd")
        self.mic_btn.pack(fill="x", **pad)
        ttk.Label(self.root, text="Mute shortcut works while Teams is focused (see Settings).",
                  foreground="#666").pack(anchor="w", padx=10)

        meters = ttk.Frame(self.root)
        meters.pack(fill="x", **pad)
        ttk.Label(meters, text="Others", width=8).grid(row=0, column=0, sticky="w")
        self.meter_others = ttk.Progressbar(meters, maximum=100)
        self.meter_others.grid(row=0, column=1, sticky="ew")
        ttk.Label(meters, text="Me", width=8).grid(row=1, column=0, sticky="w")
        self.meter_me = ttk.Progressbar(meters, maximum=100)
        self.meter_me.grid(row=1, column=1, sticky="ew")
        meters.columnconfigure(1, weight=1)

        prog = ttk.Frame(self.root)
        prog.pack(fill="x", **pad)
        self.prog_text = tk.StringVar(value="")
        ttk.Label(prog, textvariable=self.prog_text).pack(anchor="w")
        self.prog_bar = ttk.Progressbar(prog, maximum=100)
        self.prog_bar.pack(fill="x")

        ttk.Label(self.root, text="Recent meetings").pack(anchor="w", padx=10, pady=(10, 0))
        self.tree = ttk.Treeview(self.root, columns=("status",), height=8)
        self.tree.heading("#0", text="Meeting")
        self.tree.heading("status", text="Status")
        self.tree.column("status", width=120, stretch=False)
        self.tree.pack(fill="both", expand=True, padx=10)
        self.tree.bind("<Double-1>", lambda e: self.open_transcript())
        btns = ttk.Frame(self.root)
        btns.pack(fill="x", **pad)
        ttk.Button(btns, text="Open transcript", command=self.open_transcript).pack(side="left")
        ttk.Button(btns, text="Open folder", command=self.open_folder).pack(side="left", padx=6)
        ttk.Button(btns, text="Transcribe again", command=self.transcribe_again).pack(side="left")
        self._render_mic()

    # ---- recording -------------------------------------------------------
    def toggle_recording(self) -> None:
        if self.recorder is None:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self) -> None:
        now = datetime.now()
        title = self.title_var.get().strip() or "Meeting"
        try:
            self.folder = make_meeting_dir(Path(self.settings.output_dir), now, title)
            self.meta = MeetingMeta(title, now.replace(microsecond=0))
            write_meta(self.folder, self.meta)
            self.recorder = Recorder(self.folder, devices.list_output_loopbacks, devices.get_mic,
                                     self.settings.mic_device)
            self.queue.pause()  # spec: no transcription while recording (keeps the Teams call smooth)
            self.recorder.start()
        except Exception as e:  # noqa: BLE001
            log.exception("start failed")
            self.recorder = None
            self.queue.resume()
            messagebox.showerror("Teams Listener", f"Could not start recording:\n{e}")
            return
        self.rec_started = time.monotonic()
        if self.queue.busy:
            self.prog_text.set("Transcription paused while recording")
        self.start_btn.config(text="■ Stop recording")
        self.title_entry.config(state="disabled")
        self._render_mic()
        self.refresh_meetings()

    def stop_recording(self) -> None:
        rec, folder, meta = self.recorder, self.folder, self.meta
        if rec is None:
            return
        self.recorder = None
        summary = rec.stop()
        meta.end = datetime.now().replace(microsecond=0)
        meta.devices = summary.devices
        meta.events = summary.events
        write_meta(folder, meta)
        self.start_btn.config(text="● Start recording")
        self.title_entry.config(state="normal")
        self.title_var.set("")
        self.elapsed.set("")
        self.meter_others["value"] = self.meter_me["value"] = 0
        self._render_mic()
        self.queue.resume()
        self._submit(folder)

    def toggle_mute(self) -> None:
        if self.recorder is None:
            return
        self.recorder.muted = not self.recorder.muted
        self._render_mic()

    _MIC_STYLE = {
        "idle": ("disabled", "#dddddd", "#555", "#dddddd", "Teams Listener — idle"),
        "nomic": ("normal", "#e0a800", "black", "#c79500", "Teams Listener — recording Others only (no mic)"),
        "muted": ("normal", "#d72626", "white", "#b81f1f", "Teams Listener — recording, mic MUTED"),
        "live": ("normal", "#28aa46", "white", "#1f8c39", "Teams Listener — recording, mic LIVE"),
    }

    def _render_mic(self) -> None:
        rec = self.recorder
        mic = rec.mic_name if rec else None
        self._shown_mic = mic
        state, text = mic_display(rec is not None, bool(rec and rec.muted), mic)
        btn_state, bg, fg, active_bg, tooltip = self._MIC_STYLE[state]
        self.mic_btn.config(text=text, state=btn_state, bg=bg, fg=fg, activebackground=active_bg)
        self.tray.set_state(state, tooltip)

    # ---- transcription ---------------------------------------------------
    def _submit(self, folder: Path) -> None:
        self.transcribing[folder] = 0.0
        self.queue.submit(folder)
        self.prog_text.set(f"Queued: {folder.name}")
        self.refresh_meetings()

    def _on_progress(self, folder: Path, frac: float, eta: float | None) -> None:
        self.transcribing[folder] = frac
        self.prog_bar["value"] = frac * 100
        self.prog_text.set(f"Transcribing {folder.name}: {frac:.0%} — {_fmt_eta(eta)}")

    def _on_done(self, folder: Path, path: Path) -> None:
        self.transcribing.pop(folder, None)
        self.prog_bar["value"] = 0
        self.prog_text.set(f"Done: {folder.name}")
        self.refresh_meetings()

    def _on_error(self, folder: Path, e: Exception) -> None:
        self.transcribing.pop(folder, None)
        self.prog_bar["value"] = 0
        log.error("transcription failed for %s: %r", folder, e)
        self.prog_text.set(f"Failed: {folder.name} (audio kept — use Transcribe again)")
        self.refresh_meetings()
        messagebox.showerror("Teams Listener", f"Transcription failed for {folder.name}:\n{e}\n\n"
                             "The audio is kept. Use 'Transcribe again' to retry.")

    # ---- meetings list ---------------------------------------------------
    def refresh_meetings(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for m in list_meetings(Path(self.settings.output_dir)):
            status = m.status
            if self.folder == m.folder and self.recorder is not None:
                status = "recording"
            elif m.folder in self.transcribing:
                status = "transcribing"
            self.tree.insert("", "end", iid=str(m.folder), text=m.folder.name, values=(status,))

    def _selected(self) -> Path | None:
        sel = self.tree.selection()
        return Path(sel[0]) if sel else None

    def open_transcript(self) -> None:
        f = self._selected()
        if f and (f / "transcript.md").exists():
            os.startfile(f / "transcript.md")
        elif f:
            messagebox.showinfo("Teams Listener", "This meeting has no transcript yet.")

    def open_folder(self) -> None:
        f = self._selected()
        if f:
            os.startfile(f)

    def transcribe_again(self) -> None:
        f = self._selected()
        if not f:
            return
        if self.recorder is not None and f == self.folder:
            messagebox.showinfo("Teams Listener", "This meeting is still recording.")
            return
        if f in self.transcribing:
            return
        if not (f / "meta.json").exists():
            write_meta(f, MeetingMeta(f.name, datetime.fromtimestamp(f.stat().st_ctime).replace(microsecond=0)))
        self._submit(f)

    # ---- settings ----------------------------------------------------------
    def _restart_hotkeys(self) -> None:
        if self.hotkeys:
            self.hotkeys.stop()
            self.hotkeys = None
        try:
            self.hotkeys = MuteHotkeys(self.settings.hotkey, self.settings.follow_teams_shortcut,
                                       lambda: self.call(self.toggle_mute))
            self.hotkeys.start()
        except ValueError:
            messagebox.showwarning("Teams Listener", f"Invalid hotkey '{self.settings.hotkey}'. Check Settings.")

    def open_settings(self) -> None:
        SettingsDialog(self)

    def apply_settings(self, s: Settings) -> None:
        self.settings = s
        save_settings(s)
        self._restart_hotkeys()
        self.refresh_meetings()

    # ---- window lifecycle ------------------------------------------------
    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def on_close(self) -> None:
        if self.recorder is not None:
            ans = messagebox.askyesnocancel("Teams Listener",
                                            "A meeting is being recorded.\n\nStop recording and save it?\n"
                                            "(No = keep recording in the tray)")
            if ans is None:
                return
            if ans:
                self.stop_recording()
        self.root.withdraw()

    def quit(self) -> None:
        if self.recorder is not None:
            if not messagebox.askyesno("Teams Listener", "Stop the recording, save it and quit?"):
                return
            self.stop_recording()
        if self.queue.busy and not messagebox.askyesno(
                "Teams Listener", "A transcription is still running. Quit anyway?\n"
                "You can finish it later with 'Transcribe again'."):
            return
        if self.hotkeys:
            self.hotkeys.stop()
        self.tray.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


class SettingsDialog:
    def __init__(self, app: App):
        self.app = app
        s = app.settings
        w = self.win = tk.Toplevel(app.root)
        w.title("Settings")
        w.transient(app.root)
        w.grab_set()
        f = ttk.Frame(w, padding=12)
        f.pack(fill="both", expand=True)

        self.model = tk.StringVar(value=s.model)
        self.model_path = tk.StringVar(value=s.model_path or "")
        self.mic = tk.StringVar(value=s.mic_device or DEFAULT_MIC_LABEL)
        self.hotkey = tk.StringVar(value=s.hotkey)
        self.follow = tk.BooleanVar(value=s.follow_teams_shortcut)
        self.delete = tk.BooleanVar(value=s.delete_audio_after)
        self.out = tk.StringVar(value=s.output_dir)

        r = 0
        ttk.Label(f, text="Transcription model").grid(row=r, column=0, sticky="w")
        ttk.Combobox(f, textvariable=self.model, values=ALLOWED_MODELS, state="readonly").grid(row=r, column=1, sticky="ew")
        r += 1
        ttk.Label(f, text="small.en is faster; medium.en is more accurate (much slower on this laptop).",
                  foreground="#666").grid(row=r, column=0, columnspan=3, sticky="w")
        r += 1
        ttk.Label(f, text="Model folder (optional)").grid(row=r, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.model_path).grid(row=r, column=1, sticky="ew")
        ttk.Button(f, text="…", width=3, command=lambda: self._pick_dir(self.model_path)).grid(row=r, column=2)
        r += 1
        ttk.Label(f, text="Microphone").grid(row=r, column=0, sticky="w")
        ttk.Combobox(f, textvariable=self.mic, values=[DEFAULT_MIC_LABEL, *devices.list_mic_names()],
                     state="readonly").grid(row=r, column=1, sticky="ew")
        r += 1
        ttk.Label(f, text="Mute shortcut").grid(row=r, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.hotkey).grid(row=r, column=1, sticky="ew")
        r += 1
        ttk.Checkbutton(f, text="Also toggle when Teams' Ctrl+Shift+M is pressed (can drift out of sync "
                        "if you click Teams' mute button)", variable=self.follow).grid(row=r, column=0, columnspan=3, sticky="w")
        r += 1
        ttk.Checkbutton(f, text="Delete audio after a successful transcription",
                        variable=self.delete).grid(row=r, column=0, columnspan=3, sticky="w")
        r += 1
        ttk.Label(f, text="Save meetings in").grid(row=r, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.out).grid(row=r, column=1, sticky="ew")
        ttk.Button(f, text="…", width=3, command=lambda: self._pick_dir(self.out)).grid(row=r, column=2)
        r += 1
        b = ttk.Frame(f)
        b.grid(row=r, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(b, text="Cancel", command=w.destroy).pack(side="right")
        ttk.Button(b, text="Save", command=self.save).pack(side="right", padx=6)
        f.columnconfigure(1, weight=1)

    def _pick_dir(self, var: tk.StringVar) -> None:
        d = filedialog.askdirectory(parent=self.win, initialdir=var.get() or None)
        if d:
            var.set(d)

    def save(self) -> None:
        from pynput.keyboard import HotKey

        try:
            HotKey.parse(self.hotkey.get())
        except ValueError:
            messagebox.showerror("Settings", "That shortcut isn't valid. Example: <ctrl>+<alt>+m", parent=self.win)
            return
        mic = self.mic.get()
        s = Settings(
            model=self.model.get(),
            model_path=self.model_path.get().strip() or None,
            mic_device=None if mic == DEFAULT_MIC_LABEL else mic,
            hotkey=self.hotkey.get().strip(),
            follow_teams_shortcut=self.follow.get(),
            delete_audio_after=self.delete.get(),
            output_dir=self.out.get().strip() or Settings().output_dir,
        )
        self.app.apply_settings(s)
        self.win.destroy()

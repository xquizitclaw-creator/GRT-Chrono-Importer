"""
plugin_main.py - GRT Chrono Importer plugin entry point.

Launched by GRT as:   GRTChronoImporter.exe --ipcport <port>

Flow:
  1. Connect back to GRT on 127.0.0.1:<port>. The plugin must be launched from
     GRT; if no port is supplied or the connection fails, it shows a message and
     exits rather than running in a degraded standalone mode.
  2. Show a small window: pick chronograph files, choose device + file unit +
     import mode, optionally load a base .grtload.
  3. Build the .grtload, SAVE it to disk (user chooses location), then OFFER to
     open it in GRT via the Load_File socket command.

GUI uses Tkinter (stdlib) so the frozen binary stays small and dependency-light.
"""
import os
import re
import sys
import threading
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import chrono_import
from grt_ipc import GRTClient, parse_args_for_port


class ImporterApp:
    def __init__(self, root, client):
        self.root = root
        self.client = client
        self.chrono_files = []
        self.base_path = None
        self.last_output = None

        root.title("GRT Chrono Importer")
        root.geometry("600x640")
        root.minsize(560, 600)

        pad = {"padx": 10, "pady": 6}

        # Connection status
        self.status_var = tk.StringVar(value="Connected to GRT")
        ttk.Label(root, textvariable=self.status_var, foreground="#2c7").pack(
            anchor="w", **pad)

        # 1. Base file
        f1 = ttk.LabelFrame(root, text="1. Base .grtload (optional)")
        f1.pack(fill="x", **pad)
        self.base_var = tk.StringVar(value="No base file - a fresh file will be created.")
        ttk.Label(f1, textvariable=self.base_var, wraplength=480).pack(
            anchor="w", padx=8, pady=4)
        ttk.Button(f1, text="Select base .grtload", command=self.pick_base).pack(
            anchor="w", padx=8, pady=(0, 6))

        # 2. Chronograph files
        f2 = ttk.LabelFrame(root, text="2. Chronograph files")
        f2.pack(fill="both", expand=True, **pad)

        opts = ttk.Frame(f2)
        opts.pack(fill="x", padx=8, pady=4)
        ttk.Label(opts, text="Device:").grid(row=0, column=0, sticky="w")
        self.device = tk.StringVar(value="Garmin Xero C1 Pro")
        ttk.Combobox(opts, textvariable=self.device, state="readonly",
                     values=["Garmin Xero C1 Pro", "Athlon Rangecraft Velocity Pro"],
                     width=28).grid(row=0, column=1, sticky="w", padx=6)

        ttk.Label(opts, text="File unit:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.unit = tk.StringVar(value="imperial")
        uf = ttk.Frame(opts)
        uf.grid(row=1, column=1, sticky="w", padx=6, pady=(4, 0))
        ttk.Radiobutton(uf, text="Imperial (ft/s)", value="imperial",
                        variable=self.unit).pack(side="left")
        ttk.Radiobutton(uf, text="Metric (m/s)", value="metric",
                        variable=self.unit).pack(side="left", padx=(10, 0))

        # Import mode
        ttk.Label(opts, text="Mode:").grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.mode = tk.StringVar(value="standard")
        mf = ttk.Frame(opts)
        mf.grid(row=2, column=1, sticky="w", padx=6, pady=(4, 0))
        ttk.Radiobutton(mf, text="Standard", value="standard",
                        variable=self.mode, command=self._on_mode_change).pack(side="left")
        ttk.Radiobutton(mf, text="Ladder", value="ladder",
                        variable=self.mode, command=self._on_mode_change).pack(side="left", padx=(10, 0))
        ttk.Radiobutton(mf, text="Sessions", value="sessions",
                        variable=self.mode, command=self._on_mode_change).pack(side="left", padx=(10, 0))

        # Ladder options (shown only in ladder mode)
        self.ladder_frame = ttk.Frame(f2)
        lf = self.ladder_frame
        row = ttk.Frame(lf); row.pack(fill="x", padx=8, pady=(2, 0))
        ttk.Label(row, text="Steps:").pack(side="left")
        self.ladder_steps = tk.IntVar(value=5)
        self.steps_combo = ttk.Combobox(row, textvariable=self.ladder_steps,
                                        state="readonly", width=4,
                                        values=[str(n) for n in range(3, 11)])
        self.steps_combo.pack(side="left", padx=(4, 14))
        ttk.Label(row, text="Top charge (gr):").pack(side="left")
        self.top_charge = tk.StringVar(value="")
        ttk.Entry(row, textvariable=self.top_charge, width=8).pack(side="left", padx=(4, 14))
        ttk.Label(row, text="Step size (gr):").pack(side="left")
        self.step_size = tk.StringVar(value="")
        ttk.Entry(row, textvariable=self.step_size, width=7).pack(side="left", padx=(4, 0))
        hint = ttk.Label(lf, foreground="#888",
                         text="Assign one chronograph file to each charge weight below.")
        hint.pack(anchor="w", padx=8, pady=(2, 2))

        # Chrono vs Sim
        srow = ttk.Frame(lf); srow.pack(fill="x", padx=8, pady=(4, 0))
        self.cvs_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(srow, text="Chrono vs Sim", variable=self.cvs_enabled,
                        command=self._on_cvs_toggle).pack(side="left")
        self.cvs_chart = tk.BooleanVar(value=True)
        self.cvs_chart_cb = ttk.Checkbutton(srow, text="include chart",
                                            variable=self.cvs_chart)
        self.cvs_chart_cb.pack(side="left", padx=(10, 0))
        self.sim_json_path = None
        self.sim_btn = ttk.Button(srow, text="Select sim JSON...",
                                  command=self.pick_sim_json)
        self.sim_btn.pack(side="left", padx=(10, 0))
        self.sim_var = tk.StringVar(value="no sim file")
        ttk.Label(srow, textvariable=self.sim_var, foreground="#888").pack(
            side="left", padx=(8, 0))
        self._on_cvs_toggle()

        # Rebuild the per-charge rows whenever the ladder definition changes.
        self.top_charge.trace_add("write", lambda *a: self._rebuild_charge_rows())
        self.step_size.trace_add("write", lambda *a: self._rebuild_charge_rows())
        self.ladder_steps.trace_add("write", lambda *a: self._rebuild_charge_rows())

        # One row per charge weight: index (0 = top charge) -> file path.
        self.charge_files = {}
        self.charge_rows_frame = ttk.Frame(lf)
        self.charge_rows_frame.pack(fill="x", padx=8, pady=(4, 4))

        # Standard / Sessions file picker
        self.std_btn = ttk.Button(f2, text="Select chronograph files...",
                                  command=self.pick_files)
        self.std_btn.pack(anchor="w", padx=8, pady=6)

        self.files_list = tk.Listbox(f2, height=8)
        self.files_list.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # 3. Actions
        f3 = ttk.Frame(root)
        f3.pack(fill="x", **pad)
        ttk.Button(f3, text="Build & Save .grtload",
                   command=self.build_and_save).pack(side="left")
        self.open_btn = ttk.Button(f3, text="Open in GRT",
                                   command=self.open_in_grt, state="disabled")
        self.open_btn.pack(side="left", padx=8)
        ttk.Button(f3, text="Close", command=self.on_close).pack(side="right")

        root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _on_mode_change(self):
        if self.mode.get() == "ladder":
            self.ladder_frame.pack(fill="x", before=self.std_btn)
            self.std_btn.pack_forget()
            self.files_list.pack_forget()
            self._apply_ladder_defaults()
            self._rebuild_charge_rows()
        else:
            self.ladder_frame.pack_forget()
            self.std_btn.pack(anchor="w", padx=8, pady=6)
            self.files_list.pack(fill="both", expand=True, padx=8, pady=(0, 8))
            if self.mode.get() == "sessions":
                self.std_btn.config(text="Select Sessions file...")
            else:
                self.std_btn.config(text="Select chronograph files...")
            self._refresh_file_list()

    def _charge_weights_desc(self):
        """Return charge weights in DESCENDING order (top first), or None."""
        try:
            top_gr = float(self.top_charge.get())
            step_gr = float(self.step_size.get())
            n = int(self.ladder_steps.get())
        except (ValueError, TypeError):
            return None
        if top_gr <= 0 or step_gr <= 0 or n < 1:
            return None
        return [top_gr - i * step_gr for i in range(n)]

    def _rebuild_charge_rows(self):
        """Rebuild the per-charge file rows (descending charge order)."""
        if not hasattr(self, "charge_rows_frame"):
            return
        for w in self.charge_rows_frame.winfo_children():
            w.destroy()
        if self.mode.get() != "ladder":
            return
        weights = self._charge_weights_desc()
        if weights is None:
            ttk.Label(self.charge_rows_frame, foreground="#a00",
                      text="Enter top charge and step size to list charges.").pack(
                anchor="w")
            return
        self.charge_row_vars = []
        for i, w in enumerate(weights):
            row = ttk.Frame(self.charge_rows_frame)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text="%.2f gr" % w, width=9).pack(side="left")
            ttk.Button(row, text="Select",
                       command=lambda idx=i: self._pick_charge_file(idx)).pack(
                side="left", padx=(4, 6))
            var = tk.StringVar(value=os.path.basename(self.charge_files.get(i) or "")
                               or "(no file)")
            self.charge_row_vars.append(var)
            fg = "#888" if not self.charge_files.get(i) else "#222"
            ttk.Label(row, textvariable=var, foreground=fg).pack(side="left")

    def _pick_charge_file(self, idx):
        p = filedialog.askopenfilename(
            title="Select chronograph file for this charge",
            filetypes=[("Chronograph files", "*.csv *.xls *.xlsx"),
                       ("All files", "*.*")],
        )
        if p:
            self.charge_files[idx] = p
            if idx < len(self.charge_row_vars):
                self.charge_row_vars[idx].set(os.path.basename(p))
                self._rebuild_charge_rows()

    def _apply_ladder_defaults(self):
        """Pre-fill top charge / step / count from the base file's ladder."""
        if not self.base_path:
            return
        try:
            with open(self.base_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            return
        d = chrono_import.read_base_ladder_defaults(content)
        if d.get("top_gr"):
            self.top_charge.set("%.3f" % d["top_gr"])
        if d.get("step_gr"):
            self.step_size.set("%.3f" % d["step_gr"])
        if d.get("count"):
            self.ladder_steps.set(int(d["count"]))

    def _on_cvs_toggle(self):
        on = self.cvs_enabled.get()
        state = "normal" if on else "disabled"
        self.sim_btn.config(state=state)
        self.cvs_chart_cb.config(state=state)

    def pick_sim_json(self):
        p = filedialog.askopenfilename(
            title="Select GRT simulation-results JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if p:
            self.sim_json_path = p
            self.sim_var.set(os.path.basename(p))

    def pick_base(self):
        p = filedialog.askopenfilename(
            title="Select base .grtload",
            filetypes=[("GRT load files", "*.grtload *.grt"), ("All files", "*.*")],
        )
        if p:
            self.base_path = p
            self.base_var.set(os.path.basename(p))
            if self.mode.get() == "ladder":
                self._apply_ladder_defaults()

    def pick_files(self):
        paths = filedialog.askopenfilenames(
            title="Select chronograph files",
            filetypes=[("Chronograph files", "*.csv *.xls *.xlsx"),
                       ("All files", "*.*")],
        )
        if paths:
            self.chrono_files = list(paths)
            self._refresh_file_list()

    def _refresh_file_list(self):
        self.files_list.delete(0, tk.END)
        # In ladder mode, show the charge weight each file maps to.
        weights = None
        if self.mode.get() == "ladder":
            try:
                top_gr = float(self.top_charge.get())
                step_gr = float(self.step_size.get())
                n = len(self.chrono_files)
                weights = [top_gr - (n - 1 - i) * step_gr for i in range(n)]
            except (ValueError, TypeError):
                weights = None
        for i, p in enumerate(self.chrono_files):
            label = os.path.basename(p)
            if weights is not None:
                label = "%.2f gr   <-  %s" % (weights[i], label)
            self.files_list.insert(tk.END, label)

    def build_and_save(self):
        if self.mode.get() in ("standard", "sessions") and not self.chrono_files:
            messagebox.showwarning("No files", "Please select at least one chronograph file.")
            return
        base_content = None
        if self.base_path:
            try:
                with open(self.base_path, "r", encoding="utf-8", errors="replace") as f:
                    base_content = f.read()
            except OSError as e:
                messagebox.showerror("Base file error", str(e))
                return
        try:
            if self.mode.get() == "ladder":
                try:
                    top_gr = float(self.top_charge.get())
                    step_gr = float(self.step_size.get())
                    steps = int(self.ladder_steps.get())
                except (ValueError, TypeError):
                    messagebox.showwarning(
                        "Missing ladder values",
                        "Enter a numeric top charge and step size (in grains).\n\n"
                        "Tip: load a base .grtload that already has a ladder and these "
                        "are filled in for you.")
                    return
                if top_gr <= 0 or step_gr <= 0:
                    messagebox.showwarning(
                        "Invalid ladder values",
                        "Top charge and step size must be greater than zero.")
                    return
                # Every charge row must have a file.
                missing = [i for i in range(steps) if not self.charge_files.get(i)]
                if missing:
                    weights = self._charge_weights_desc() or []
                    miss_lbl = ", ".join("%.2f gr" % weights[i] for i in missing
                                         if i < len(weights))
                    messagebox.showwarning(
                        "Missing charge files",
                        "Assign a chronograph file to every charge.\n\nStill needed: %s"
                        % miss_lbl)
                    return
                # Rows are top-first; import_ladder wants low -> high.
                ladder_files = [self.charge_files[i] for i in range(steps)][::-1]

                sim_data = None
                if self.cvs_enabled.get():
                    if not self.sim_json_path:
                        messagebox.showwarning(
                            "No sim JSON",
                            "Chrono vs Sim is enabled but no simulation JSON is selected.\n\n"
                            "Export it from GRT (\"Export simulation results\") and choose it, "
                            "or uncheck Chrono vs Sim.")
                        return
                    try:
                        with open(self.sim_json_path, "r", encoding="utf-8",
                                  errors="replace") as f:
                            sim_data = f.read()
                    except OSError as e:
                        messagebox.showerror("Sim JSON error", str(e))
                        return

                grt_text, summary = chrono_import.import_ladder(
                    ladder_files, top_gr=top_gr, step_gr=step_gr,
                    file_unit=self.unit.get(), base_content=base_content,
                    name_mode="weight",
                    sim_json=sim_data, device=self.device.get(),
                    make_chart=self.cvs_chart.get())

                if summary.get("sim_error"):
                    messagebox.showwarning(
                        "Chrono vs Sim",
                        "Imported, but the sim comparison hit a problem:\n%s\n\n"
                        "The ladder tab was still created."
                        % summary["sim_error"])
                elif summary.get("chart_unavailable"):
                    messagebox.showwarning(
                        "Chart unavailable",
                        "The Analysis tab was created, but the Chrono vs Sim chart could "
                        "not be generated (the imaging library is unavailable in this "
                        "build). The data is still in the Analysis tab.")
            elif self.mode.get() == "sessions":
                if not self.chrono_files:
                    messagebox.showwarning("No file", "Select a Garmin Sessions file (.xls/.xlsx).")
                    return
                grt_text, summary = chrono_import.import_sessions(
                    self.chrono_files[0], file_unit=self.unit.get(),
                    base_content=base_content)
            else:
                grt_text, summary = chrono_import.import_files(
                    self.chrono_files, file_unit=self.unit.get(),
                    base_content=base_content)
        except Exception as e:
            messagebox.showerror("Import failed", str(e))
            return

        if summary["files"] == 0:
            messagebox.showwarning(
                "Nothing imported",
                "No velocity data was found. Check the device and file unit, or that "
                "the files contain a velocity column.")
            return

        # Default output name: base file stem, else first chrono file, plus a
        # timestamp so repeated imports don't overwrite each other.
        if self.base_path:
            stem = os.path.splitext(os.path.basename(self.base_path))[0]
        elif self.mode.get() == "ladder" and self.charge_files:
            first = next((self.charge_files[k] for k in sorted(self.charge_files)
                          if self.charge_files[k]), None)
            stem = os.path.splitext(os.path.basename(first))[0] if first else "Ladder"
        elif self.chrono_files:
            stem = os.path.splitext(os.path.basename(self.chrono_files[0]))[0]
        else:
            stem = "ChronoImport"

        stem = stem.replace(" ", "_").replace(".", "")
        stem = re.sub(r"[^A-Za-z0-9_\-]", "", stem)

        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        default_name = f"{stem}_{stamp}.grtload"

        init_dir = os.path.dirname(self.base_path) if self.base_path else ""

        out = filedialog.asksaveasfilename(
            title="Save .grtload",
            defaultextension=".grtload",
            filetypes=[("GRT load files", "*.grtload"), ("All files", "*.*")],
            initialfile=default_name,
            initialdir=init_dir,
        )
        if not out:
            return
        try:
            with open(out, "w", encoding="utf-8") as f:
                f.write(grt_text)
        except OSError as e:
            messagebox.showerror("Save failed", str(e))
            return

        self.last_output = out
        self.open_btn.config(state="normal")

        msg = (f"Saved {summary['files']} file(s), {summary['total_shots']} shots.\n\nSaved to:\n"
               f"{out}")
        if messagebox.askyesno("Open in GRT?",
                               msg + "\n\nOpen this file in GRT now?"):
            self.open_in_grt()

    def open_in_grt(self):
        if not self.last_output:
            return
        try:
            self.client.load_file(self.last_output)
        except Exception as e:
            messagebox.showerror("GRT communication failed", str(e))

    def on_grt_event(self, name, payload):
        # Called from the socket thread; marshal onto the Tk thread.
        self.root.after(0, lambda: self._handle_event(name, payload))

    def _handle_event(self, name, payload):
        if name in ("Event_WindowClosed", "Event_Disconnected"):
            # GRT went away; nothing left to talk to.
            self.on_close()

    def on_close(self):
        try:
            if self.client:
                self.client.close()
        finally:
            self.root.destroy()


def main():
    port = parse_args_for_port(sys.argv)
    root = tk.Tk()

    if not port:
        root.withdraw()
        messagebox.showerror(
            "GRT Chrono Importer",
            "This is a GRT plugin. Please launch it from inside Gordon's Reloading "
            "Tool using the Chrono Importer toolbar button or menu item, not by "
            "running the program directly.",
        )
        root.destroy()
        return

    client = GRTClient(port)
    try:
        client.connect(timeout=5.0)
    except OSError:
        root.withdraw()
        messagebox.showerror(
            "GRT Chrono Importer",
            "Could not connect to GRT. Please close this and re-launch the plugin "
            "from the Chrono Importer button inside GRT.",
        )
        root.destroy()
        return

    app = ImporterApp(root, client)
    client.on_event = app.on_grt_event
    root.mainloop()


if __name__ == "__main__":
    main()

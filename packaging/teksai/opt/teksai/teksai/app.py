"""TeksAI desktop GUI (Tkinter)."""

from __future__ import annotations

import queue
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__, config, detector

APP_DIR = __file__.rsplit("/teksai/", 1)[0]
PAD = 8


def _colour(score: float) -> str:
    if score >= 0.65:
        return "ai_high"
    if score >= 0.4:
        return "ai_mid"
    return ""


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"TeksAI {__version__}: Pengesan AI & Humanizer")
        self.geometry("1100x760")
        self.minsize(760, 520)
        self.q: queue.Queue = queue.Queue()
        self.busy = False

        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Big.TLabel", font=("TkDefaultFont", 20, "bold"))
        style.configure("Accent.TButton", padding=(14, 6))

        self.status = tk.StringVar(value="Sedia.")
        ttk.Label(self, textvariable=self.status, anchor="w").pack(side="bottom", fill="x", padx=PAD, pady=(0, PAD))
        nb = self.nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=PAD, pady=PAD)
        nb.add(self._detect_tab(nb), text="  Pengesan AI  ")
        nb.add(self._humanize_tab(nb), text="  Humanizer  ")
        nb.add(self._rules_tab(nb), text="  Peraturan Humanizer  ")
        nb.add(self._settings_tab(nb), text="  Tetapan  ")

        self.after(50, self._poll)

    # ------------------------------------------------------------------ utils
    def _textbox(self, parent, **kw) -> tk.Text:
        frame = ttk.Frame(parent)
        t = tk.Text(frame, wrap="word", undo=True, font=("TkDefaultFont", 11), padx=6, pady=6, **kw)
        sb = ttk.Scrollbar(frame, command=t.yview)
        t.configure(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        t.frame = frame  # type: ignore[attr-defined]
        return t

    def _run(self, label: str, fn, done) -> None:
        if self.busy:
            return
        self.busy = True
        self.status.set(label)

        def work():
            try:
                self.q.put((done, fn(), None))
            except Exception as e:  # noqa: BLE001 - shown to the user
                self.q.put((done, None, e))

        threading.Thread(target=work, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                item = self.q.get_nowait()
                if item[0] == "call":
                    item[1]()
                    continue
                done, result, err = item
                self.busy = False
                done(result, err)
        except queue.Empty:
            pass
        self.after(50, self._poll)

    def _open_into(self, box: tk.Text) -> None:
        path = filedialog.askopenfilename(filetypes=[("Teks", "*.txt *.md"), ("Semua", "*")])
        if path:
            with open(path, encoding="utf-8", errors="replace") as f:
                box.delete("1.0", "end")
                box.insert("1.0", f.read())

    # ------------------------------------------------------------- detect tab
    def _detect_tab(self, nb) -> ttk.Frame:
        f = ttk.Frame(nb, padding=PAD)
        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Label(top, text="Tampal teks untuk disemak:").pack(side="left")
        ttk.Button(top, text="Buka fail…", command=lambda: self._open_into(self.d_in)).pack(side="right")
        ttk.Button(top, text="Kosongkan", command=lambda: self.d_in.delete("1.0", "end")).pack(side="right", padx=4)

        self.d_engine = tk.StringVar(value="auto")
        eng = ttk.Frame(f)
        eng.pack(fill="x", pady=(4, 0))
        ttk.Label(eng, text="Enjin:").pack(side="left")
        for val, lab in (("auto", "Auto"), ("heuristic", "Heuristik"), ("gpt2", "GPT-2 perplexity")):
            ttk.Radiobutton(eng, text=lab, value=val, variable=self.d_engine).pack(side="left", padx=4)
        gpt = "dipasang" if detector.gpt2_available() else "tidak dipasang (lihat Tetapan)"
        ttk.Label(eng, text=f"   GPT-2: {gpt}", foreground="#666").pack(side="left")

        btns = ttk.Frame(f)
        btns.pack(side="bottom", fill="x")
        ttk.Button(btns, text="Semak teks", style="Accent.TButton", command=self._do_detect).pack(side="left")
        ttk.Button(btns, text="Hantar ke Humanizer →", command=self._send_to_humanizer).pack(side="left", padx=PAD)
        ttk.Label(btns, text="Merah = ciri AI kuat · Kuning = sederhana", foreground="#666").pack(side="right")

        pane = ttk.PanedWindow(f, orient="horizontal")
        pane.pack(fill="both", expand=True, pady=PAD)

        self.d_in = self._textbox(pane)
        self.d_in.tag_configure("ai_high", background="#ffd2d2")
        self.d_in.tag_configure("ai_mid", background="#fff1c2")
        pane.add(self.d_in.frame, weight=3)

        right = ttk.Frame(pane, padding=(PAD, 0))
        pane.add(right, weight=2)
        self.d_pct = tk.StringVar(value="–")
        self.d_verdict = tk.StringVar(value="Tekan 'Semak teks' untuk mula.")
        ttk.Label(right, textvariable=self.d_pct, style="Big.TLabel").pack(anchor="w")
        ttk.Label(right, textvariable=self.d_verdict, wraplength=360).pack(anchor="w", pady=(0, PAD))
        self.d_bar = ttk.Progressbar(right, maximum=100)
        self.d_bar.pack(fill="x")
        self.d_metrics = self._textbox(right, height=14, state="disabled", background="#f6f6f6")
        self.d_metrics.frame.pack(fill="both", expand=True, pady=PAD)

        return f

    def _do_detect(self) -> None:
        text = self.d_in.get("1.0", "end-1c")
        engine = self.d_engine.get()
        label = "Memuatkan GPT-2 dan menganalisis…" if engine != "heuristic" and detector.gpt2_available() else "Menganalisis…"
        self._run(label, lambda: detector.detect(text, engine), self._show_report)

    def _show_report(self, rep, err) -> None:
        if err:
            self.status.set("Ralat.")
            messagebox.showerror("Pengesan", str(err))
            return
        for tag in ("ai_high", "ai_mid"):
            self.d_in.tag_remove(tag, "1.0", "end")
        for s in rep.sentences:
            tag = _colour(s.ai_score)
            if tag:
                self.d_in.tag_add(tag, f"1.0+{s.start}c", f"1.0+{s.end}c")
        self.d_pct.set(f"{rep.ai_percent:.0f}% AI")
        self.d_verdict.set(rep.verdict)
        self.d_bar["value"] = rep.ai_percent
        lines = [f"Enjin: {rep.engine}", ""]
        lines += [f"{k}: {v}" for k, v in rep.metrics.items()]
        flagged = [s for s in rep.sentences if s.reasons and _colour(s.ai_score)]
        if flagged:
            lines += ["", "Ayat yang ditanda:"]
            for s in flagged[:25]:
                lines.append(f"• \"{s.text[:70]}{'…' if len(s.text) > 70 else ''}\"\n   → {'; '.join(s.reasons)}")
        lines += ["", rep.note,
                  "Amaran: tiada pengesan AI yang tepat 100%. Jangan guna skor ini sebagai bukti."]
        self.d_metrics.configure(state="normal")
        self.d_metrics.delete("1.0", "end")
        self.d_metrics.insert("1.0", "\n".join(lines))
        self.d_metrics.configure(state="disabled")
        self.status.set("Selesai.")

    def _send_to_humanizer(self) -> None:
        self.h_in.delete("1.0", "end")
        self.h_in.insert("1.0", self.d_in.get("1.0", "end-1c"))
        self.nb.select(1)

    # ----------------------------------------------------------- humanize tab
    def _humanize_tab(self, nb) -> ttk.Frame:
        from .humanizer import MODELS
        f = ttk.Frame(nb, padding=PAD)
        opts = ttk.Frame(f)
        opts.pack(fill="x")
        ttk.Label(opts, text="Model:").pack(side="left")
        saved = config.load()
        self.h_model = tk.StringVar(value=saved.get("model_label", next(iter(MODELS))))
        ttk.Combobox(opts, textvariable=self.h_model, values=list(MODELS), state="readonly", width=30).pack(side="left", padx=4)
        ttk.Label(opts, text="Usaha:").pack(side="left", padx=(PAD, 0))
        self.h_effort = tk.StringVar(value=saved.get("effort", "medium"))
        ttk.Combobox(opts, textvariable=self.h_effort, values=["low", "medium", "high"], state="readonly", width=8).pack(side="left", padx=4)
        ttk.Button(opts, text="Buka fail…", command=lambda: self._open_into(self.h_in)).pack(side="right")

        btns = ttk.Frame(f)
        btns.pack(side="bottom", fill="x")
        ttk.Button(btns, text="Humanize", style="Accent.TButton", command=self._do_humanize).pack(side="left")
        ttk.Button(btns, text="Salin hasil", command=self._copy_out).pack(side="left", padx=PAD)
        ttk.Button(btns, text="Simpan hasil…", command=self._save_out).pack(side="left")
        ttk.Button(btns, text="Semak semula hasil di Pengesan", command=self._recheck).pack(side="left", padx=PAD)

        pane = ttk.PanedWindow(f, orient="horizontal")
        pane.pack(fill="both", expand=True, pady=PAD)
        left = ttk.Frame(pane)
        ttk.Label(left, text="Teks asal:").pack(anchor="w")
        self.h_sample = self._textbox(left, height=5)
        self.h_sample.frame.pack(side="bottom", fill="x")
        ttk.Label(left, text="Contoh tulisan anda sendiri (pilihan, untuk padankan gaya):").pack(side="bottom", anchor="w", pady=(PAD, 0))
        self.h_in = self._textbox(left)
        self.h_in.frame.pack(fill="both", expand=True)
        pane.add(left, weight=1)

        right = ttk.Frame(pane, padding=(PAD, 0, 0, 0))
        ttk.Label(right, text="Hasil:").pack(anchor="w")
        self.h_out = self._textbox(right)
        self.h_out.frame.pack(fill="both", expand=True)
        pane.add(right, weight=1)
        return f

    def _do_humanize(self) -> None:
        from . import humanizer
        text = self.h_in.get("1.0", "end-1c").strip()
        if not text:
            messagebox.showinfo("Humanizer", "Masukkan teks dahulu.")
            return
        model = humanizer.MODELS[self.h_model.get()]
        effort, sample = self.h_effort.get(), self.h_sample.get("1.0", "end-1c")
        cfg = config.load()
        cfg.update(model_label=self.h_model.get(), effort=effort)
        config.save(cfg)
        self.h_out.delete("1.0", "end")

        def chunk(t: str) -> None:
            self.q.put(("call", lambda: (self.h_out.insert("end", t), self.h_out.see("end"))))

        def done(result, err):
            if err:
                self.status.set("Ralat.")
                messagebox.showerror("Humanizer", str(err))
                return
            self.h_out.delete("1.0", "end")
            self.h_out.insert("1.0", result)
            self.status.set("Selesai. Semak hasil: pastikan fakta dan maksud tidak berubah.")

        self._run(f"Menulis semula dengan {model}…",
                  lambda: humanizer.humanize(text, model, effort, sample, on_text=chunk), done)

    def _copy_out(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.h_out.get("1.0", "end-1c"))
        self.status.set("Hasil disalin ke papan klip.")

    def _save_out(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Teks", "*.txt")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.h_out.get("1.0", "end-1c"))
            self.status.set(f"Disimpan: {path}")

    def _recheck(self) -> None:
        self.d_in.delete("1.0", "end")
        self.d_in.insert("1.0", self.h_out.get("1.0", "end-1c"))
        self.nb.select(0)
        self._do_detect()

    # -------------------------------------------------------------- rules tab
    def _rules_tab(self, nb) -> ttk.Frame:
        from .humanizer import SKILL_PATH
        f = ttk.Frame(nb, padding=PAD)
        ttk.Label(f, text="Peraturan dari github.com/blader/humanizer (lesen MIT). Inilah arahan yang dihantar kepada model.",
                  foreground="#666").pack(anchor="w")
        t = self._textbox(f)
        t.frame.pack(fill="both", expand=True, pady=(4, 0))
        try:
            t.insert("1.0", SKILL_PATH.read_text(encoding="utf-8"))
        except OSError as e:
            t.insert("1.0", f"Tidak dapat membaca {SKILL_PATH}: {e}")
        t.configure(state="disabled")
        return f

    # ----------------------------------------------------------- settings tab
    def _settings_tab(self, nb) -> ttk.Frame:
        f = ttk.Frame(nb, padding=PAD * 2)
        ttk.Label(f, text="Kunci API Anthropic (untuk Humanizer)", font=("TkDefaultFont", 12, "bold")).pack(anchor="w")
        ttk.Label(f, text="Dapatkan kunci di platform.claude.com. Disimpan dalam ~/.config/teksai/config.json (hanya boleh dibaca oleh anda). "
                          "Jika kosong, pembolehubah ANTHROPIC_API_KEY digunakan.", wraplength=800).pack(anchor="w", pady=4)
        row = ttk.Frame(f)
        row.pack(fill="x")
        self.s_key = tk.StringVar(value=config.load().get("api_key", ""))
        ent = ttk.Entry(row, textvariable=self.s_key, show="•", width=60)
        ent.pack(side="left")
        ttk.Checkbutton(row, text="Tunjuk", command=lambda: ent.configure(show="" if ent.cget("show") else "•")).pack(side="left", padx=4)
        ttk.Button(row, text="Simpan", command=self._save_key).pack(side="left", padx=4)

        ttk.Separator(f).pack(fill="x", pady=PAD * 2)
        ttk.Label(f, text="Enjin GPT-2 (pilihan, untuk pengesan lebih baik)", font=("TkDefaultFont", 12, "bold")).pack(anchor="w")
        ttk.Label(f, text="Memasang PyTorch (CPU) dan transformers ke dalam venv app ini (~1 GB muat turun). "
                          "Model GPT-2 (~500 MB) dimuat turun dari Hugging Face kali pertama digunakan. Perlukan kata laluan sudo.",
                  wraplength=800).pack(anchor="w", pady=4)
        ttk.Button(f, text="Pasang enjin GPT-2", command=self._install_gpt2).pack(anchor="w")
        ttk.Label(f, text="Atau di terminal:  sudo teksai --install-gpt2", foreground="#666").pack(anchor="w", pady=4)

        ttk.Separator(f).pack(fill="x", pady=PAD * 2)
        ttk.Label(f, text=f"TeksAI {__version__}. Humanizer: blader/humanizer (MIT). Fail di {APP_DIR}", foreground="#666").pack(anchor="w")
        return f

    def _save_key(self) -> None:
        cfg = config.load()
        cfg["api_key"] = self.s_key.get().strip()
        config.save(cfg)
        self.status.set("Kunci API disimpan.")

    def _install_gpt2(self) -> None:
        if not messagebox.askyesno("Pasang GPT-2", "Muat turun dan pasang torch + transformers (~1 GB)?"):
            return

        def work():
            r = subprocess.run(["pkexec", "/usr/bin/teksai", "--install-gpt2"], capture_output=True, text=True)
            return r

        def done(r, err):
            if err or r.returncode != 0:
                messagebox.showerror("Pasang GPT-2", str(err or r.stderr[-1500:] or "Gagal."))
                self.status.set("Pemasangan gagal.")
            else:
                messagebox.showinfo("Pasang GPT-2", "Siap. Buka semula TeksAI untuk menggunakan enjin GPT-2.")
                self.status.set("Enjin GPT-2 dipasang.")

        self._run("Memasang enjin GPT-2 (boleh ambil masa beberapa minit)…", work, done)


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()

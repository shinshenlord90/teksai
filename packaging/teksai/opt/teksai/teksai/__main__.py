"""Entry point: GUI by default, or a small CLI.

  teksai                      open the GUI
  teksai detect FILE          print an AI-likelihood report for FILE ("-" = stdin)
  teksai humanize FILE        print a rewritten version of FILE
  teksai --install-gpt2       install torch + transformers into the app venv (root)
"""

import argparse
import subprocess
import sys


def main() -> int:
    ap = argparse.ArgumentParser(prog="teksai", description="Pengesan AI & Humanizer")
    ap.add_argument("--install-gpt2", action="store_true", help="pasang enjin GPT-2 (perlu root)")
    sub = ap.add_subparsers(dest="cmd")
    d = sub.add_parser("detect", help="semak teks")
    d.add_argument("file")
    d.add_argument("--engine", choices=["auto", "heuristic", "gpt2"], default="auto")
    h = sub.add_parser("humanize", help="tulis semula teks")
    h.add_argument("file")
    h.add_argument("--model", default="claude-opus-5-5")
    h.add_argument("--effort", choices=["low", "medium", "high"], default="medium")
    a = ap.parse_args()

    if a.install_gpt2:
        pip = [sys.executable, "-m", "pip", "install", "--no-cache-dir"]
        r = subprocess.run(pip + ["torch", "--index-url", "https://download.pytorch.org/whl/cpu"])
        if r.returncode == 0:
            r = subprocess.run(pip + ["transformers"])
        return r.returncode

    if a.cmd is None:
        from .app import main as gui
        gui()
        return 0

    text = sys.stdin.read() if a.file == "-" else open(a.file, encoding="utf-8").read()
    if a.cmd == "detect":
        from .detector import detect
        try:
            rep = detect(text, a.engine)
        except ValueError as e:
            print(f"Ralat: {e}", file=sys.stderr)
            return 1
        print(f"{rep.ai_percent:.0f}% AI  ({rep.verdict})  [enjin: {rep.engine}]")
        for k, v in rep.metrics.items():
            print(f"  {k}: {v}")
        for s in rep.sentences:
            if s.reasons and s.ai_score >= 0.4:
                print(f"  - {s.text[:80]}\n      {'; '.join(s.reasons)}")
        return 0

    from .humanizer import HumanizeError, humanize
    try:
        humanize(text, a.model, a.effort, on_text=lambda t: print(t, end="", flush=True))
        print()
    except HumanizeError as e:
        print(f"Ralat: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

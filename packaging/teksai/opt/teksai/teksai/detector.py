"""Local AI-text detection for TeksAI.

Two engines:

* ``heuristic`` - standard library only, always available. Scores stylometric
  signals: sentence-length variation ("burstiness"), vocabulary variety,
  stock AI vocabulary and structural tells from the humanizer rules.
* ``gpt2`` - optional. Needs ``torch`` and ``transformers`` in the app's venv.
  Scores each sentence by GPT-2 perplexity; text a language model finds very
  predictable (low perplexity, low variation between sentences) is more
  likely to be machine-written.

No detector of this kind is reliable enough to prove who wrote a text. The
score is a hint, never evidence.
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Sentence splitting
# --------------------------------------------------------------------------

_SENT_RE = re.compile(r"[^.!?\n]+(?:[.!?]+[\"')\]]*|\n|$)")


def split_sentences(text: str) -> list[tuple[int, int, str]]:
    """Return (start, end, sentence) spans for every non-empty sentence."""
    out = []
    for m in _SENT_RE.finditer(text):
        s = m.group(0)
        if s.strip() and len(s.strip()) > 1:
            lead = len(s) - len(s.lstrip())
            trail = len(s) - len(s.rstrip())
            out.append((m.start() + lead, m.end() - trail, s.strip()))
    return out


_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ']+")


def words(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)]


# --------------------------------------------------------------------------
# Tells (English and Malay). Taken from patterns described in the humanizer
# rules (blader/humanizer SKILL.md) plus common Malay equivalents.
# --------------------------------------------------------------------------

STOCK_WORDS = {
    # English
    "delve", "delves", "delving", "tapestry", "testament", "pivotal",
    "crucial", "seamless", "seamlessly", "leverage", "leveraging", "robust",
    "multifaceted", "intricate", "intricacies", "underscore", "underscores",
    "showcase", "showcases", "showcasing", "realm", "landscape", "vibrant",
    "foster", "fostering", "holistic", "nuanced", "paramount", "commendable",
    "meticulous", "meticulously", "embark", "navigate", "navigating",
    "unwavering", "transformative", "groundbreaking", "furthermore",
    "moreover", "additionally", "notably", "ultimately", "essentially",
    "comprehensive", "synergy", "empower", "empowering", "elevate",
    "streamline", "unlock", "unleash", "boasts", "invaluable", "enduring",
    # Malay
    "tuntasnya", "kesimpulannya", "selain itu", "tambahan pula",
    "secara keseluruhannya", "amat penting", "memainkan peranan",
    "tidak dapat dinafikan", "di samping itu", "justeru",
}

STRUCT_PATTERNS = [
    (re.compile(r"\bnot (?:just|only|merely) [^.,;]{1,60}[,;]? but\b", re.I),
     "kontras 'not just X but Y'"),
    (re.compile(r"\bit'?s not [^.]{1,60}[.;,] ?it'?s\b", re.I),
     "kontras 'it's not X, it's Y'"),
    (re.compile(r"\bbukan sahaja [^.]{1,60} malah\b", re.I),
     "kontras 'bukan sahaja ... malah'"),
    (re.compile(r"\bin (?:today'?s|the modern) (?:fast-paced |digital )?(?:world|era|landscape)\b", re.I),
     "pembuka klise"),
    (re.compile(r"\bin conclusion\b|\bto sum up\b|\boverall,", re.I),
     "penutup klise"),
    (re.compile(r"\b(?:it is|it's) (?:important|worth|crucial) (?:to note|noting|to remember)\b", re.I),
     "frasa pengisi"),
    (re.compile(r"\bplays? an? (?:crucial|vital|pivotal|key|significant) role\b", re.I),
     "dakwaan melambung"),
    (re.compile(r"\b(?:I hope this helps|Great question|Certainly!|As an AI)\b", re.I),
     "sisa chatbot"),
    (re.compile(r"—"), "em dash"),
]

_TRIAD_RE = re.compile(r"\b\w+(?: \w+)?, \w+(?: \w+)?,? (?:and|dan) \w+(?: \w+)?\b", re.I)


@dataclass
class SentenceResult:
    start: int
    end: int
    text: str
    ai_score: float  # 0..1
    reasons: list[str] = field(default_factory=list)


@dataclass
class Report:
    engine: str
    ai_percent: float
    verdict: str
    sentences: list[SentenceResult]
    metrics: dict[str, str]
    note: str = ""


def _verdict(p: float) -> str:
    if p < 20:
        return "Kemungkinan besar ditulis manusia"
    if p < 45:
        return "Kebanyakannya manusia, ada ciri AI"
    if p < 70:
        return "Campuran: sebahagian mungkin AI"
    return "Kemungkinan besar dijana AI"


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


# --------------------------------------------------------------------------
# Heuristic engine
# --------------------------------------------------------------------------


def _sentence_tells(sent: str) -> list[str]:
    reasons = []
    low = sent.lower()
    ws = set(words(sent))
    hits = sorted(w for w in STOCK_WORDS if (" " in w and w in low) or w in ws)
    if hits:
        reasons.append("perkataan stok AI: " + ", ".join(hits[:4]))
    for rx, label in STRUCT_PATTERNS:
        if rx.search(sent):
            reasons.append(label)
    # Triads are a weak tell: count one only next to another tell.
    if reasons and _TRIAD_RE.search(sent):
        reasons.append("senarai tiga serangkai")
    return reasons


def detect_heuristic(text: str) -> Report:
    sents = split_sentences(text)
    all_words = words(text)
    if len(all_words) < 40 or len(sents) < 3:
        raise ValueError("Teks terlalu pendek. Masukkan sekurang-kurangnya 40 perkataan dan 3 ayat.")

    lengths = [max(1, len(words(s))) for _, _, s in sents]
    mean_len = statistics.mean(lengths)
    cv = statistics.pstdev(lengths) / mean_len if mean_len else 0.0  # burstiness

    # Moving-average type-token ratio over 50-word windows (length-independent)
    win = 50
    if len(all_words) > win:
        ttrs = [len(set(all_words[i:i + win])) / win for i in range(0, len(all_words) - win + 1, 10)]
        mattr = statistics.mean(ttrs)
    else:
        mattr = len(set(all_words)) / len(all_words)

    per_sent = []
    tell_total = 0
    for (a, b, s), n in zip(sents, lengths):
        reasons = _sentence_tells(s)
        tell_total += len(reasons)
        # Sentences close to the mean length are "uniform", a mild AI signal.
        uniform = abs(n - mean_len) / mean_len < 0.25
        sc = 0.15 + 0.25 * min(len(reasons), 3) + (0.1 if uniform else 0.0)
        if uniform and reasons:
            reasons.append("panjang ayat seragam")
        per_sent.append(SentenceResult(a, b, s, min(sc, 1.0), reasons))

    tell_rate = tell_total / len(sents)
    # Low burstiness and a high rate of tells push towards AI. Weights were
    # set by hand, not trained; MATTR is reported but not scored.
    z = (0.45 - cv) / 0.12 + (tell_rate - 0.3) / 0.2
    doc_score = _sigmoid(z)
    # Share of words that sit in flagged sentences, like a per-sentence detector.
    flagged = sum(n for s, n in zip(per_sent, lengths) if s.ai_score >= 0.4)
    share = flagged / sum(lengths)
    ai = (0.35 * doc_score + 0.65 * share) * 100

    metrics = {
        "Bilangan perkataan": str(len(all_words)),
        "Bilangan ayat": str(len(sents)),
        "Purata panjang ayat": f"{mean_len:.1f} perkataan",
        "Burstiness (CV panjang ayat)": f"{cv:.2f}  (manusia biasanya > 0.5)",
        "Kepelbagaian kosa kata (MATTR)": f"{mattr:.2f}",
        "Ciri AI dikesan": f"{tell_total} ({tell_rate:.2f} setiap ayat)",
        "Perkataan dalam ayat ditanda": f"{share * 100:.0f}%",
    }
    return Report("Heuristik", round(ai, 1), _verdict(ai), per_sent, metrics,
                  note="Enjin heuristik: anggaran kasar berdasarkan gaya. Paling sesuai untuk teks Inggeris.")


# --------------------------------------------------------------------------
# GPT-2 perplexity engine (optional)
# --------------------------------------------------------------------------

_MODEL = None


def gpt2_available() -> bool:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        return True
    except Exception:
        return False


def _load_gpt2():
    global _MODEL
    if _MODEL is None:
        from transformers import AutoModelForCausalLM, AutoTokenizer
        name = "openai-community/gpt2"
        tok = AutoTokenizer.from_pretrained(name)
        model = AutoModelForCausalLM.from_pretrained(name)
        model.eval()
        _MODEL = (tok, model)
    return _MODEL


def _perplexity(text: str) -> float:
    import torch
    tok, model = _load_gpt2()
    ids = tok(text, return_tensors="pt", truncation=True, max_length=1024).input_ids
    if ids.shape[1] < 2:
        return float("nan")
    with torch.no_grad():
        loss = model(ids, labels=ids).loss
    return float(torch.exp(loss))


def detect_gpt2(text: str) -> Report:
    sents = split_sentences(text)
    if len(words(text)) < 40 or len(sents) < 3:
        raise ValueError("Teks terlalu pendek. Masukkan sekurang-kurangnya 40 perkataan dan 3 ayat.")
    ppls = []
    per_sent = []
    for a, b, s in sents:
        p = _perplexity(s)
        if math.isnan(p):
            continue
        ppls.append(p)
        # Below ~40 is very predictable for GPT-2; above ~120 is typical of people.
        sc = _sigmoid((60 - p) / 20)
        reasons = [f"perplexity {p:.0f}"] + _sentence_tells(s)
        per_sent.append(SentenceResult(a, b, s, sc, reasons))
    overall = _perplexity(text)
    burst = statistics.pstdev(ppls) / statistics.mean(ppls) if ppls else 0.0
    z = (60 - overall) / 18 + (0.6 - burst) / 0.25
    share = sum(1 for s in per_sent if s.ai_score >= 0.5) / max(1, len(per_sent))
    ai = (0.5 * _sigmoid(z) + 0.5 * share) * 100
    metrics = {
        "Bilangan ayat": str(len(sents)),
        "Perplexity keseluruhan": f"{overall:.1f}  (rendah = lebih mudah diramal)",
        "Burstiness perplexity": f"{burst:.2f}  (manusia biasanya lebih tinggi)",
        "Perplexity min / maks ayat": f"{min(ppls):.0f} / {max(ppls):.0f}",
    }
    return Report("GPT-2 perplexity", round(ai, 1), _verdict(ai), per_sent, metrics,
                  note="Enjin GPT-2: berasaskan model bahasa Inggeris. Teks Melayu akan dapat perplexity tinggi dan skor rendah.")


def detect(text: str, engine: str = "auto") -> Report:
    if engine == "gpt2" or (engine == "auto" and gpt2_available()):
        return detect_gpt2(text)
    return detect_heuristic(text)

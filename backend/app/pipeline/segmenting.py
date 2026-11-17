"""Turn Whisper word timestamps into precise, sentence-sized dubbing lines.

Whisper's own segments are up to 30 s, pad silence at both ends and often
contain two people. Cutting at sentence ends and pauses gives lines that
start and stop exactly when someone speaks, are complete sentences (better
translation) and usually hold a single speaker (correct voice).
"""
from __future__ import annotations

SENTENCE_END = (".", "?", "!", "…")


def resegment(words: list[dict], max_gap: float = 0.6, sentence_gap: float = 0.12,
              max_len: float = 12.0, comma_split_after: float = 7.0) -> list[dict]:
    """words: [{"start", "end", "word"}] in time order -> [{"start", "end", "text"}]."""
    words = [w for w in words if w.get("start") is not None and w.get("end") is not None
             and str(w.get("word", "")).strip()]
    lines: list[dict] = []
    cur: list[dict] = []

    def flush():
        if cur:
            text = "".join(w["word"] for w in cur).strip()
            lines.append({"start": round(cur[0]["start"], 3), "end": round(cur[-1]["end"], 3),
                          "text": " ".join(text.split())})
            cur.clear()

    for w in words:
        if cur:
            prev = cur[-1]["word"].strip()
            gap = w["start"] - cur[-1]["end"]
            length = cur[-1]["end"] - cur[0]["start"]
            if (gap > max_gap
                    or (prev.endswith(SENTENCE_END) and gap > sentence_gap)
                    or (length > comma_split_after and prev.endswith((",", ";", ":")))
                    or w["end"] - cur[0]["start"] > max_len):
                flush()
        cur.append(w)
    flush()
    return lines

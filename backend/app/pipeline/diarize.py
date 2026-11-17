"""Speaker diarization without any gated model / token.

Every transcript segment gets an ECAPA speaker embedding (SpeechBrain). All
embeddings of the WHOLE video are clustered together, so a character keeps the
same speaker id from the first minute to the last - this is what keeps each
dubbed voice consistent.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

MIN_EMBED_SECONDS = 0.8
MAX_EMBED_SECONDS = 10.0


def _normalise(x: np.ndarray) -> np.ndarray:
    return x / (np.linalg.norm(x, axis=1, keepdims=True) + 1e-9)


MIN_SPEAKER_SECONDS = 4.0  # less speech than this is not a real character
SINGLE_VOICE_SILHOUETTE = 0.1  # below this, the "groups" are just one voice


def _agglomerate(emb: np.ndarray, k: int) -> np.ndarray:
    from sklearn.cluster import AgglomerativeClustering

    return AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average").fit_predict(emb)


def estimate_speakers(emb: np.ndarray, max_speakers: int, threshold: float = 0.7) -> np.ndarray:
    """Automatic character count: try k = 2..max groupings and keep the one whose
    voices are most clearly separated (silhouette score); one voice if none is."""
    n = len(emb)
    if n == 2:  # too few lines to score: same voice if the two sound alike
        return np.array([0, 0 if float(emb[0] @ emb[1]) >= threshold else 1])
    from sklearn.metrics import silhouette_score

    best_score, best = -1.0, np.zeros(n, dtype=int)
    for k in range(2, min(max_speakers, n - 1) + 1):
        labels = _agglomerate(emb, k)
        score = float(silhouette_score(emb, labels, metric="cosine"))
        if score > best_score:
            best_score, best = score, labels
    return best if best_score >= SINGLE_VOICE_SILHOUETTE else np.zeros(n, dtype=int)


SAME_VOICE_SIMILARITY = 0.85  # two groups this alike are the same person


def merge_similar_speakers(labels: np.ndarray, emb: np.ndarray,
                           same: float = SAME_VOICE_SIMILARITY) -> np.ndarray:
    """Join groups whose average voices are nearly identical (an over-split)."""
    labels = labels.copy()
    while True:
        labs = sorted(set(labels.tolist()))
        if len(labs) < 2:
            return labels
        cents = _normalise(np.stack([_normalise(emb[labels == lab]).mean(axis=0) for lab in labs]))
        sim = cents @ cents.T
        np.fill_diagonal(sim, -1.0)
        i, j = np.unravel_index(int(np.argmax(sim)), sim.shape)
        if sim[i, j] < same:
            return labels
        labels[labels == labs[j]] = labs[i]


def merge_small_speakers(labels: np.ndarray, emb: np.ndarray, durations: np.ndarray,
                         min_seconds: float = MIN_SPEAKER_SECONDS) -> np.ndarray:
    """Groups with only a few seconds of speech are usually noise, music or a
    shout, not a character: give their lines to the closest real character."""
    labels = labels.copy()
    totals = {lab: float(durations[labels == lab].sum()) for lab in set(labels.tolist())}
    big = [lab for lab, t in totals.items() if t >= min_seconds]
    small = [lab for lab, t in totals.items() if t < min_seconds]
    if not big or not small:
        return labels
    centroids = np.stack([_normalise(emb[labels == lab]).mean(axis=0) for lab in big])
    for lab in small:
        idx = np.flatnonzero(labels == lab)
        nearest = assign_to_centroids(emb[idx], centroids)
        labels[idx] = np.array(big)[nearest]
    return labels


def cluster_embeddings(emb: np.ndarray, threshold: float, max_speakers: int,
                       n_speakers: int = 0, durations: np.ndarray | None = None) -> np.ndarray:
    """Group lines by voice. Labels are renumbered in order of first appearance
    (SPEAKER 0 = first person who talks). n_speakers > 0 forces exactly that
    many characters (set in the app); 0 = detect automatically."""
    n = len(emb)
    if n == 0:
        return np.zeros(0, dtype=int)
    if n == 1:
        return np.zeros(1, dtype=int)
    emb = _normalise(emb)
    if n_speakers > 0:
        return relabel_by_first_appearance(_agglomerate(emb, min(n_speakers, n)))
    labels = estimate_speakers(emb, max_speakers, threshold)
    labels = merge_similar_speakers(labels, emb)
    if durations is not None:
        labels = merge_small_speakers(labels, emb, np.asarray(durations, dtype=float))
    return relabel_by_first_appearance(labels)


def relabel_by_first_appearance(labels: np.ndarray) -> np.ndarray:
    mapping: dict[int, int] = {}
    for lab in labels:
        if lab not in mapping:
            mapping[int(lab)] = len(mapping)
    return np.array([mapping[int(lab)] for lab in labels], dtype=int)


def assign_to_centroids(emb: np.ndarray, centroids: np.ndarray) -> np.ndarray:
    if len(emb) == 0:
        return np.zeros(0, dtype=int)
    sims = _normalise(emb) @ _normalise(centroids).T
    return sims.argmax(axis=1)


def centroids_for(emb: np.ndarray, labels: np.ndarray) -> np.ndarray:
    k = int(labels.max()) + 1
    return np.stack([_normalise(emb[labels == i]).mean(axis=0) for i in range(k)])


def diarize(vocals16k: Path, segments: list[dict], work: Path, device: str,
            threshold: float, max_speakers: int, n_speakers: int = 0) -> list[dict]:
    cache = work / "diarized.json"
    if cache.exists():
        return json.loads(cache.read_text())
    if not segments:
        return segments

    import torch
    from speechbrain.inference.speaker import EncoderClassifier

    from . import audio

    wav, sr = audio.load(vocals16k, mono=True)
    wav = wav[:, 0]
    enc = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=str(work.parents[2] / "models" / "ecapa"),  # = HD_DATA_DIR/models, same as prefetch
        run_opts={"device": device},
    )
    embs = np.zeros((len(segments), 192), dtype=np.float32)
    usable = np.zeros(len(segments), dtype=bool)
    with torch.no_grad():
        for i, s in enumerate(segments):
            dur = s["end"] - s["start"]
            if dur < MIN_EMBED_SECONDS:
                continue
            mid = (s["start"] + s["end"]) / 2
            half = min(dur, MAX_EMBED_SECONDS) / 2
            clip = wav[int((mid - half) * sr): int((mid + half) * sr)]
            if len(clip) < MIN_EMBED_SECONDS * sr:
                continue
            e = enc.encode_batch(torch.from_numpy(clip).unsqueeze(0).to(device))
            embs[i] = e.squeeze().cpu().numpy()
            usable[i] = True

    labels = np.zeros(len(segments), dtype=int)
    if usable.any():
        durs = np.array([segments[i]["end"] - segments[i]["start"] for i in np.flatnonzero(usable)])
        labels[usable] = cluster_embeddings(embs[usable], threshold, max_speakers, n_speakers, durs)
        if (~usable).any():
            # Too-short lines: copy the speaker of the nearest usable neighbour.
            idx_usable = np.flatnonzero(usable)
            for i in np.flatnonzero(~usable):
                nearest = idx_usable[np.argmin(np.abs(idx_usable - i))]
                labels[i] = labels[nearest]
        labels = relabel_by_first_appearance(labels)

    out = [dict(s, speaker=int(lab)) for s, lab in zip(segments, labels, strict=True)]
    cache.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out

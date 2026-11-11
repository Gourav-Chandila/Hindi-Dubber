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


def cluster_embeddings(emb: np.ndarray, threshold: float, max_speakers: int) -> np.ndarray:
    """Agglomerative clustering on cosine similarity. Labels are renumbered in
    order of first appearance (SPEAKER 0 = first person who talks)."""
    n = len(emb)
    if n == 0:
        return np.zeros(0, dtype=int)
    if n == 1:
        return np.zeros(1, dtype=int)
    from sklearn.cluster import AgglomerativeClustering

    emb = _normalise(emb)
    labels = AgglomerativeClustering(
        n_clusters=None, metric="cosine", linkage="average",
        distance_threshold=1.0 - threshold,
    ).fit_predict(emb)
    if len(set(labels)) > max_speakers:
        labels = AgglomerativeClustering(
            n_clusters=max_speakers, metric="cosine", linkage="average",
        ).fit_predict(emb)
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
            threshold: float, max_speakers: int) -> list[dict]:
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
        savedir=str(work.parent.parent / "models" / "ecapa"),
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
        labels[usable] = cluster_embeddings(embs[usable], threshold, max_speakers)
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

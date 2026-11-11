import numpy as np

from app.pipeline import diarize


def _voices(rng, n_per, centres):
    out, truth = [], []
    for i, c in enumerate(centres):
        out.append(c + 0.05 * rng.standard_normal((n_per, len(c))))
        truth += [i] * n_per
    return np.vstack(out), np.array(truth)


def test_clusters_are_consistent_and_ordered():
    rng = np.random.default_rng(0)
    centres = [rng.standard_normal(192) for _ in range(3)]
    emb, truth = _voices(rng, 20, centres)
    order = rng.permutation(len(emb))
    labels = diarize.cluster_embeddings(emb[order], threshold=0.7, max_speakers=8)
    truth = truth[order]
    # Same true speaker -> same label everywhere (voice consistency).
    for t in range(3):
        assert len(set(labels[truth == t])) == 1
    assert len(set(labels)) == 3
    assert labels[0] == 0  # first speaker to talk is speaker 0


def test_max_speakers_cap():
    rng = np.random.default_rng(1)
    emb = rng.standard_normal((30, 192))
    labels = diarize.cluster_embeddings(emb, threshold=0.99, max_speakers=4)
    assert len(set(labels)) <= 4


def test_assign_to_centroids():
    c = np.eye(3, 192)
    assert list(diarize.assign_to_centroids(c[[2, 0, 1]] + 0.01, c)) == [2, 0, 1]

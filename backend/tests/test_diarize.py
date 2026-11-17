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


def test_auto_finds_the_right_number_of_characters():
    rng = np.random.default_rng(7)
    for true_k in (1, 2, 4, 6):
        centres = [rng.standard_normal(192) for _ in range(true_k)]
        emb, _ = _voices(rng, 12, centres)
        assert len(set(diarize.cluster_embeddings(emb, 0.7, max_speakers=8))) == true_k


def test_tiny_fake_character_is_merged_into_a_real_one():
    rng = np.random.default_rng(11)
    centres = [rng.standard_normal(192) for _ in range(3)]
    emb, _ = _voices(rng, 15, centres)
    # one odd line (a shout / music) that sounds a bit like nobody, only 1.2 s long
    odd = 0.6 * centres[0] + 0.4 * rng.standard_normal(192)
    emb = np.vstack([emb, odd, odd + 0.01])
    durations = np.r_[np.full(45, 3.0), 0.6, 0.6]
    labels = diarize.cluster_embeddings(emb, 0.7, max_speakers=8, durations=durations)
    assert len(set(labels)) == 3  # still exactly the 3 real characters

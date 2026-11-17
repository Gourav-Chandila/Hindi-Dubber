from app.pipeline.segmenting import resegment


def _w(start, end, word):
    return {"start": start, "end": end, "word": word}


def test_splits_at_sentence_end_and_pause_with_tight_times():
    words = [
        _w(1.20, 1.50, " Good"), _w(1.55, 1.90, " morning,"), _w(1.95, 2.40, " Priya."),
        # next speaker answers after a short gap
        _w(2.70, 2.90, " Hi"), _w(2.95, 3.30, " Arjun!"),
        # long pause, same speaker continues
        _w(4.50, 4.80, " Let's"), _w(4.85, 5.20, " go."),
    ]
    lines = resegment(words)
    assert [x["text"] for x in lines] == ["Good morning, Priya.", "Hi Arjun!", "Let's go."]
    assert lines[0]["start"] == 1.2 and lines[0]["end"] == 2.4  # exactly speech, no padding


def test_no_split_inside_a_flowing_sentence():
    words = [_w(i * 0.3, i * 0.3 + 0.25, f" w{i}") for i in range(10)]
    assert len(resegment(words)) == 1


def test_very_long_speech_is_cut():
    words = [_w(i * 0.4, i * 0.4 + 0.35, " word") for i in range(60)]  # 24 s, no punctuation
    lines = resegment(words, max_len=12.0)
    assert len(lines) >= 2 and all(x["end"] - x["start"] <= 12.0 for x in lines)


def test_ignores_words_without_timestamps():
    assert resegment([_w(None, None, " hi"), _w(1, 1.2, " ok.")])[0]["text"] == "ok."

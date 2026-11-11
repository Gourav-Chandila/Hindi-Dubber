import re

from app.pipeline.hindi_numbers import int_to_hindi, numbers_to_hindi


def test_basic_numbers():
    assert int_to_hindi(0) == "शून्य"
    assert int_to_hindi(7) == "सात"
    assert int_to_hindi(11) == "ग्यारह"
    assert int_to_hindi(99) == "निन्यानवे"
    assert int_to_hindi(100) == "एक सौ"
    assert int_to_hindi(105) == "एक सौ पाँच"
    assert int_to_hindi(2026) == "दो हज़ार छब्बीस"
    assert int_to_hindi(150000) == "एक लाख पचास हज़ार"
    assert int_to_hindi(25_000_000) == "दो करोड़ पचास लाख"


def test_text_has_no_digits_left():
    samples = [
        "कृपया इसे 11 बजे तक भेजें।",
        "मैंने 7 बजे के लिए टेबल बुक की है।",
        "चलो 6:30 बजे निकलते हैं।",
        "मेरे पास 14% बैटरी है।",
        "कीमत 1,000 रुपये है और 12.5 सेकंड",
        "११ लोग",
    ]
    for s in samples:
        out = numbers_to_hindi(s)
        assert not re.search(r"\d", out), out
    assert numbers_to_hindi("6:30 बजे") == "छह तीस बजे"
    assert numbers_to_hindi("14% बैटरी") == "चौदह प्रतिशत बैटरी"
    assert numbers_to_hindi("1,000") == "एक हज़ार"
    assert numbers_to_hindi("12.5") == "बारह दशमलव पाँच"

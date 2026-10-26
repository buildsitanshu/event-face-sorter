from convo_gallery.export_sorted import folder_name


def test_folder_name_is_capped_at_80():
    assert len(folder_name("x" * 200, 1)) == 80


def test_folder_name_collapses_spaces():
    assert folder_name("  a   b  ", 2) == "a b"


def test_folder_name_keeps_latin_accents():
    assert folder_name("José", 7) == "José"


def test_folder_name_keeps_devanagari():
    assert folder_name("प्रिया शर्मा", 7) == "प्रिया शर्मा"


def test_folder_name_drops_path_separators():
    assert folder_name("a/b\\c", 7) == "abc"


def test_folder_name_drops_punctuation():
    assert folder_name("Priya (bride)", 7) == "Priya bride"


def test_folder_name_normalises_decomposed_accent_to_nfc():
    assert folder_name("José", 7) == "José"


def test_folder_name_drops_zero_width_space():
    assert folder_name("a​b", 7) == "ab"

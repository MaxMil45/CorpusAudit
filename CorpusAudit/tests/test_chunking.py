from corpus_audit import _chunk_text

def test_empty_text_returns_no_chunks():
    assert _chunk_text("") == []

def test_short_text_is_one_chunk():
    assert _chunk_text("A short report.") == ["A short report."]

def test_long_text_is_split_and_overlaps():
    text = ("This is a sentence about a measurable research finding. " * 100)
    chunks = _chunk_text(text, size=300, overlap=40)
    assert len(chunks) > 1
    assert all(chunks)
    assert len(chunks[0]) <= 301

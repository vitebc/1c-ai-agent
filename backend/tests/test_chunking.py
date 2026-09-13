"""Тесты чанкера — без БД и сети."""

from app.rag import split_markdown


def test_empty() -> None:
    assert split_markdown("") == []
    assert split_markdown("   \n\n  ") == []


def test_heading_prepended() -> None:
    text = "# Возвраты\n\nСрок — 14 дней.\n\nДеньги — за 3 дня."
    chunks = split_markdown(text, max_chars=1000)
    assert len(chunks) == 1
    assert chunks[0].startswith("Возвраты")


def test_max_chars_respected() -> None:
    paras = [f"Абзац номер {i} с некоторым содержательным текстом." for i in range(30)]
    chunks = split_markdown("\n\n".join(paras), max_chars=300, overlap=0)
    assert len(chunks) > 3
    assert all(len(c) <= 300 for c in chunks)


def test_overlap_links_chunks() -> None:
    paras = [f"Уникальный абзац {i} про складской учёт." for i in range(10)]
    chunks = split_markdown("\n\n".join(paras), max_chars=120, overlap=60)
    assert len(chunks) > 1
    # Хвост первого чанка встречается в начале второго (пересечение, не дубль чанка)
    assert chunks[0][-40:] in chunks[1]
    assert chunks[0] != chunks[1]

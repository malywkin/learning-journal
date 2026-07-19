"""Публичный API сервиса заметок.

Тонкий слой над хранилищем: валидирует вход и делегирует в storage.
Именно этот модуль импортируют handlers и внешние потребители.
"""

from storage import read_all, write_all


def save_note(text: str, tags: list[str] | None = None) -> dict:
    """Сохранить заметку. Возвращает созданную запись с id.

    Параметр tags добавлен позже (в docs/api.md ещё старая сигнатура без него).
    """
    notes = read_all()
    note = {"id": len(notes) + 1, "text": text.strip(), "tags": tags or []}
    notes.append(note)
    write_all(notes)
    return note


def get_note(note_id: int) -> dict | None:
    """Достать заметку по id или None, если её нет."""
    for note in read_all():
        if note["id"] == note_id:
            return note
    return None


def delete_note(note_id: int) -> bool:
    """Удалить заметку по id. True — если что-то удалили."""
    notes = read_all()
    kept = [n for n in notes if n["id"] != note_id]
    write_all(kept)
    return len(kept) != len(notes)

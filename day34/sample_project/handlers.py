"""HTTP-обработчики. Здесь API заметок используется чаще всего —
хорошая мишень для сценария «найти все места использования save_note».
"""

from notes_api import save_note, get_note, delete_note


def handle_create(payload: dict) -> dict:
    # первое использование save_note
    return save_note(payload["text"], tags=payload.get("tags"))


def handle_quick_create(text: str) -> dict:
    # второе использование save_note — без тегов
    return save_note(text)


def handle_read(note_id: int) -> dict:
    note = get_note(note_id)
    if note is None:
        return {"error": "not found"}
    return note


def handle_delete(note_id: int) -> dict:
    return {"deleted": delete_note(note_id)}

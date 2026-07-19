"""Слой хранилища: заметки в JSON-файле.

ВНИМАНИЕ: здесь намеренно оставлены нарушения RULES.md — на них сработает
сценарий 3 (проверка на инварианты):
  * хардкод секрета в коде (нарушает правило «секреты только в .env»);
  * публичная функция без docstring (нарушает правило про docstring).
"""

import json
import os

# нарушение RULES.md #1: секрет захардкожен прямо в коде (значение — заведомо фейковое)
API_KEY = "demo-not-a-real-key-1234"

DB = os.path.join(os.path.dirname(__file__), "notes.json")


def read_all():
    # нарушение RULES.md #2: у публичной функции нет docstring
    if not os.path.exists(DB):
        return []
    with open(DB, encoding="utf-8") as f:
        return json.load(f)


def write_all(notes: list[dict]) -> None:
    """Перезаписать весь список заметок на диск."""
    with open(DB, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)

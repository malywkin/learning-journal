"""День 7 — долговременная память агента: два хранилища на выбор.

Задание дня: историю диалога (messages) хранить в JSON или SQLite, при
перезапуске загружать обратно и продолжать диалог, «как будто не выключался».

Делаем ОБА варианта с одинаковыми ручками, чтобы агенту было всё равно,
куда подшивают его «дело»:
    load()      → вернуть всю историю с диска (вызываем ОДИН раз, на старте);
    append(msg) → дописать одну реплику на диск (вызываем после КАЖДОГО хода —
                  упадёт программа, история всё равно цела);
    clear()     → стереть дело (команда /clear).

Разница характеров (увидим глазами):
    JsonMemory   — один текстовый файл; дописать строку «в середину» JSON нельзя,
                   поэтому каждый раз ПЕРЕЗАПИСЫВАЕМ файл целиком. Зато открыл
                   в редакторе — и видишь всю память как на ладони.
    SqliteMemory — база данных в одном файле (встроена в Python, ставить ничего
                   не надо). Реплика = строка таблицы, дописывается В КОНЕЦ без
                   перезаписи остального. Так делают взрослые системы (тот же
                   паттерн, что SQLiteSession у OpenAI Agents SDK).
"""
import json
import os
import sqlite3


class JsonMemory:
    """Память в JSON-файле: человекочитаемо, но пишем файл целиком каждый раз."""

    def __init__(self, path):
        self.path = path
        self._history = []                    # рабочая копия (чтобы не читать файл на каждый append)

    def load(self):
        """Достать дело с полки: прочитать файл, если он есть."""
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self._history = json.load(f)
        return list(self._history)

    def append(self, msg):
        """Подшить листок: добавить реплику и переписать файл целиком."""
        self._history.append(msg)
        tmp = self.path + ".tmp"              # сначала во временный файл, потом
        with open(tmp, "w", encoding="utf-8") as f:   # атомарная замена — если упадём
            json.dump(self._history, f, ensure_ascii=False, indent=2)  # на середине записи,
        os.replace(tmp, self.path)            # старый файл останется целым

    def clear(self):
        self._history = []
        if os.path.exists(self.path):
            os.remove(self.path)

    def raw_view(self):
        """Сырое содержимое файла — читаем заново с диска (для панели «на диске»)."""
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                return {"kind": "json", "text": f.read()}
        return {"kind": "json", "text": "[ файла на диске ещё нет — память пуста ]"}


class SqliteMemory:
    """Память в SQLite: каждая реплика — строка таблицы, дописывается в конец."""

    def __init__(self, path):
        self.path = path
        self.db = sqlite3.connect(path)
        # Таблица: номер (для порядка), кто сказал, что сказал.
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS messages ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " role TEXT NOT NULL,"
            " content TEXT NOT NULL)"
        )
        self.db.commit()

    def load(self):
        rows = self.db.execute(
            "SELECT role, content FROM messages ORDER BY id").fetchall()
        return [{"role": r, "content": c} for r, c in rows]

    def append(self, msg):
        self.db.execute("INSERT INTO messages (role, content) VALUES (?, ?)",
                        (msg["role"], msg["content"]))
        self.db.commit()                      # commit = «чернила высохли», запись на диске

    def clear(self):
        self.db.execute("DELETE FROM messages")
        self.db.commit()

    def raw_view(self):
        """Строки таблицы — читаем заново из БД (для панели «на диске»)."""
        rows = self.db.execute(
            "SELECT id, role, content FROM messages ORDER BY id").fetchall()
        return {"kind": "sqlite",
                "rows": [{"id": i, "role": r, "content": c} for i, r, c in rows]}

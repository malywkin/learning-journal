"""
День 17 — «любой API», вокруг которого мы строим MCP-сервер.

Это маленькая локальная CRM на SQLite: учёт клиентов. Никакой сети и ключей —
данные лежат рядом, в файле crm.db. Именно такой сервис задание называет «mock API»:
важно не где он живёт, а что MCP-сервер оборачивает ЧУЖОЙ код в инструмент для модели.

Тут нет ни слова про MCP и LLM — это просто предметная логика (как если бы у нас
была настоящая CRM с REST API). MCP-обёртка поверх неё — в mcp_server.py.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "crm.db"

# Допустимые стадии воронки. Держим списком, чтобы и схема инструмента, и проверки
# на входе ссылались на один источник правды.
STATUSES = ["lead", "active", "churned"]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # строки как словари, а не кортежи
    return conn


def init_db(seed: bool = True) -> None:
    """Создаёт таблицу и при первом запуске насыпает пару демо-клиентов."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clients (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                email      TEXT,
                status     TEXT NOT NULL DEFAULT 'lead',
                note       TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        if seed and conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0] == 0:
            demo = [
                ("Иванов Пётр", "petr@example.com", "active", "Договор на сопровождение ООО"),
                ("Смирнова Анна", "anna@example.com", "lead", "Запрос на консультацию по НДС"),
                ("Кузнецов Олег", "oleg@example.com", "active", "Спор с подрядчиком, арбитраж"),
                ("Васильева Мария", "maria@example.com", "churned", "Ушла к конкуренту в марте"),
            ]
            conn.executemany(
                "INSERT INTO clients (name, email, status, note, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                [(n, e, s, note, datetime.now().isoformat(timespec="seconds")) for n, e, s, note in demo],
            )


def search_clients(query: str = "", status: str | None = None, limit: int = 5) -> list[dict]:
    """Поиск клиентов по имени/почте/заметке, опционально с фильтром по стадии."""
    sql = "SELECT * FROM clients WHERE (name LIKE ? OR email LIKE ? OR note LIKE ?)"
    like = f"%{query}%"
    params: list = [like, like, like]
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def create_client(name: str, email: str = "", status: str = "lead", note: str = "") -> dict:
    """Заводит нового клиента и возвращает созданную запись (с присвоенным id)."""
    if status not in STATUSES:
        raise ValueError(f"status должен быть одним из {STATUSES}, а не {status!r}")
    created = datetime.now().isoformat(timespec="seconds")
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO clients (name, email, status, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (name, email, status, note, created),
        )
        new_id = cur.lastrowid
        row = conn.execute("SELECT * FROM clients WHERE id = ?", (new_id,)).fetchone()
    return dict(row)


if __name__ == "__main__":
    # Ручная проверка предметной логики без всякого MCP.
    init_db()
    print("Поиск 'НДС':", search_clients("НДС"))
    print("Все active:", search_clients(status="active"))

"""
День 21 — ЭКРАН СДАЧИ. Читает готовый index.db и показывает по чек-листу всё,
что требует задание: локальный индекс + эмбеддинги + метаданные + сравнение 2 стратегий.
Ничего не пересобирает — просто предъявляет результат (быстро, для видео).
"""
import sqlite3
import struct
from pathlib import Path

import sqlite_vec

DB = Path(__file__).with_name("index.db")
db = sqlite3.connect(DB)
db.enable_load_extension(True); sqlite_vec.load(db); db.enable_load_extension(False)

def line(): print("─" * 68)

print("\n РЕЗУЛЬТАТ ЗАДАНИЯ ДНЯ 21 — ИНДЕКСАЦИЯ ДОКУМЕНТОВ")
print(f" Корпус: Precious Little Sleep (Alexis Dubief), главы 1–3, ~48 страниц\n")

# [1] Локальный индекс с эмбеддингами
line(); print(" [1] ЛОКАЛЬНЫЙ ИНДЕКС С ЭМБЕДДИНГАМИ"); line()
total = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
print(f" Файл индекса : {DB.name}  ({DB.stat().st_size//1024} КБ на диске)")
print(f" Всего чанков : {total}")
# вытащим один эмбеддинг из vec_chunks и покажем, что это вектор чисел
blob = db.execute("SELECT embedding FROM vec_chunks LIMIT 1").fetchone()[0]
vec = struct.unpack(f"{len(blob)//4}f", blob)
print(f" Эмбеддинг    : bge-m3, размерность {len(vec)} чисел на чанк")
print(f" Пример вектора (первые 6): {[round(x,3) for x in vec[:6]]} …")

# [2] Метаданные к каждому чанку
line(); print(" [2] МЕТАДАННЫЕ К КАЖДОМУ ЧАНКУ (source, title, section, chunk_id)"); line()
for row in db.execute("""SELECT source,title,section,chunk_id,strategy
                         FROM chunks WHERE strategy='structural' LIMIT 2"""):
    src,title,sec,cid,strat = row
    print(f"   • source={src} | title={title}")
    print(f"     section={sec!r} | chunk_id={cid} | strategy={strat}\n")

# [3] Сравнение 2 стратегий chunking
line(); print(" [3] СРАВНЕНИЕ 2 СТРАТЕГИЙ CHUNKING"); line()
print(f" {'стратегия':12} | {'чанков':>6} | {'ср.размер':>9} | {'разброс':>12}")
for strat in ("fixed","structural"):
    rows = db.execute("SELECT length(text) FROM chunks WHERE strategy=?",(strat,)).fetchall()
    lens = [r[0] for r in rows]
    print(f" {strat:12} | {len(lens):>6} | {sum(lens)//len(lens):>7} с | {min(lens):>4}–{max(lens):<5} с")
print("\n Вывод: fixed — ровный размер, но границы механические;")
print("        structural — цельные разделы, но размер скачет (крупные куски).")

line(); print(" Наглядно глазами: scene_chunking.html (нарезка) · Datasette :8081 (метаданные)")
print("                   Embedding Atlas :5055 (карта векторов)"); line()
db.close()

"""
День 21 — узел «ретривал»: задаём вопрос ПО-РУССКИ и достаём из индекса
ближайшие по смыслу куски английской книги. Показываем близость и раздел.
"""
import sqlite3
from pathlib import Path

import sqlite_vec
from sentence_transformers import SentenceTransformer

DB = str(Path(__file__).parent / "index.db")
QUESTION = "В какой позе безопаснее всего укладывать младенца спать?"

model = SentenceTransformer("BAAI/bge-m3")
qemb = model.encode([QUESTION], normalize_embeddings=True)[0].tolist()

db = sqlite3.connect(DB)
db.enable_load_extension(True); sqlite_vec.load(db); db.enable_load_extension(False)

# KNN по индексу: база сама ищет ближайшие координаты
rows = db.execute("""
  SELECT c.strategy, c.section, c.text, v.distance
  FROM vec_chunks v JOIN chunks c ON c.id = v.rowid
  WHERE v.embedding MATCH ? AND k = 12
  ORDER BY v.distance
""", (sqlite_vec.serialize_float32(qemb),)).fetchall()

print(f"ВОПРОС (по-русски): {QUESTION}\n")
print("Ближайшие куски из книги (структурная нарезка), близость 1.0 = в точку:\n")
shown = 0
for strat, section, text, dist in rows:
    if strat != "structural":
        continue
    cos = 1 - dist*dist/2          # для нормализованных векторов
    snippet = " ".join(text.split())[:230]
    print(f"[близость {cos:.2f}] раздел: «{section}»")
    print(f"   {snippet}…\n")
    shown += 1
    if shown == 3:
        break
db.close()

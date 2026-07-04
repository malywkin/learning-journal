# Проверка на РЕАЛЬНОМ индексе книги (День 21): пересортирует ли реранкер живые куски.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "day22"))
from rag_core import retrieve
from rerank import rerank_full

q = "как уложить ребёнка спать"
cands = retrieve(q, k=20)
print("вопрос:", q)
print("поиск нашёл кандидатов:", len(cands))
graded = rerank_full(q, cands, top_k=5, threshold=0.30)
print("\n  cos   score  kept  раздел | текст")
for c in graded[:12]:
    mark = "✓" if c["kept"] else " "
    print(f"  {c['cos']:.3f}  {c['score']:.3f}   {mark}   {c['section'][:26]:26} | {c['text'][:52]}")

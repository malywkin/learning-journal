# Воспроизводим сложный "жизненный" вопрос — ловим, почему модель молчит.
import sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "day22" / ".env")
sys.path.insert(0, str(Path(__file__).parent))
import rag_plus

q = ("моему сыну 4 месяца, он просыпается каждые два часа за ночь и не засыпает "
     "без груди, нормально ли это и как научить его спать дольше?")
d = rag_plus.compare(q, top_k=5, threshold=0.30)
for name, r in [("БЫЛО (голый поиск)", d["baseline"]), ("СТАЛО (реранк)", d["improved"])]:
    print("=" * 64)
    print(name, "| diag:", r.get("diag"))
    print("ответ:", (r["answer"] or "")[:400])

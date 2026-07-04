# Проверка: реально ли bge-reranker-v2-m3 отличает "отвечает" от "на ту же тему".
# Даём одну вопрос и три куска — ждём высокую оценку релевантному, низкую мусорному.
from sentence_transformers import CrossEncoder

print("Гружу bge-reranker-v2-m3 (первый раз качает ~2.3 ГБ)…", flush=True)
model = CrossEncoder("BAAI/bge-reranker-v2-m3")

q = "как уложить ребёнка спать?"
chunks = [
    "Чтобы малыш легче заснул, выстройте вечерний ритуал: тёплая ванна, приглушённый свет, спокойная книжка.",
    "Нарушения сна у детей иногда бывают признаком неврологических проблем.",
    "Прикорм вводят примерно с шести месяцев, начиная с овощных пюре.",
]

pairs = [[q, c] for c in chunks]
scores = model.predict(pairs)  # чем выше — тем релевантнее

print("\nвопрос:", q)
for c, s in sorted(zip(chunks, scores), key=lambda x: -x[1]):
    print(f"  {s:6.3f}  {c[:60]}")

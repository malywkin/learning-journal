"""
День 23 — второй этап после поиска: реранкинг + фильтр.

Строим ПОВЕРХ Дня 22: поиск (bi-encoder, bge-m3) достаёт кандидатов «по теме»,
а тут cross-encoder (bge-reranker-v2-m3, из той же семьи BAAI) пересматривает
каждый кусок ВМЕСТЕ с вопросом и ставит оценку «отвечает ли». По ней и режем.

Два способа отсечь (задание просит оба):
  - top-K   — оставить K лучших по оценке;
  - порог   — оставить всех, у кого оценка ≥ threshold (может остаться 0 → «не знаю»).

Оценки reranker'а сырые (примерно −11…+11). Прогоняем через sigmoid → 0..1,
чтобы порог был человеко-понятным и сравнимым с косинусной близостью Дня 21.
"""
import math

from sentence_transformers import CrossEncoder

RERANK_MODEL = "BAAI/bge-reranker-v2-m3"   # родня эмбеддеру bge-m3 из Дня 21

_reranker = None


def _model() -> CrossEncoder:
    global _reranker
    if _reranker is None:                    # тяжёлая, грузим один раз
        _reranker = CrossEncoder(RERANK_MODEL)
    return _reranker


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def rerank(question: str, chunks: list[dict], top_k: int = 5,
           threshold: float = 0.0) -> list[dict]:
    """Пересортировать чанки по оценке cross-encoder и отсечь.

    chunks — то, что вернул поиск Дня 22 (каждый несёт cos-близость).
    Дописываем каждому 'score' (0..1) и 'kept' (прошёл ли фильтр), сортируем по score.
    Отсечение: сначала порог, потом top_k. Возвращаем ТОЛЬКО прошедшие.
    """
    if not chunks:
        return []
    pairs = [[question, c["text"]] for c in chunks]
    raw = _model().predict(pairs)                       # сырые логиты
    scored = []
    for c, r in zip(chunks, raw):
        scored.append({**c, "score": round(_sigmoid(float(r)), 3)})
    scored.sort(key=lambda c: c["score"], reverse=True)  # лучшие наверх
    kept = [c for c in scored if c["score"] >= threshold][:top_k]
    return kept


def rerank_full(question: str, chunks: list[dict], top_k: int = 5,
                threshold: float = 0.0) -> list[dict]:
    """Как rerank(), но возвращаем ВСЕ куски с пометкой kept — для витрины,
    чтобы показать, что именно отвалилось и почему."""
    if not chunks:
        return []
    pairs = [[question, c["text"]] for c in chunks]
    raw = _model().predict(pairs)
    scored = [{**c, "score": round(_sigmoid(float(r)), 3)} for c, r in zip(chunks, raw)]
    scored.sort(key=lambda c: c["score"], reverse=True)
    passed = 0
    for rank, c in enumerate(scored):
        c["rank"] = rank + 1
        keep = c["score"] >= threshold and passed < top_k
        c["kept"] = keep
        if keep:
            passed += 1
    return scored

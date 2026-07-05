"""
День 24 — цитаты, источники, анти-галлюцинации. Ядро поверх Дней 21–23.

Что добавляем к прошлым дням (ничего не изобретаем с нуля):
  - День 21 дал индекс (sqlite-vec) и эмбеддер bge-m3;
  - День 22 дал retrieve() + сборку контекста + golden set;
  - День 23 дал реранкер (cross-encoder) со score 0..1 и порог;
  - СЕГОДНЯ: контракт {answer, sources, quotes} + проверка цитат КОДОМ +
    порог-отказ по score реранкера + faithfulness (LLM-судья).

Два предохранителя (взрослый стандарт attribution-2026):
  ВХОД  — порог по score реранкера: слабая релевантность → «не знаю», не выдумываем;
  ВЫХОД — проверка цитат кодом (substring→fuzzy) + судья: чистим ответ от липы.

Провайдер переключается ключом в .env (развязка с Дня 1):
  DEEPSEEK_API_KEY есть → DeepSeek (сильнее, стабильнее, без 429);
  иначе → OpenRouter/gpt-oss (фолбэк).
Строгий response_format=json_schema не держит НИ ОДИН провайдер (проверено живьём:
gpt-oss игнорирует, DeepSeek 400) → берём мягкий json_object + шаблон + разбор кодом.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

from rapidfuzz import fuzz

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE.parent / "day22"))
sys.path.insert(0, str(BASE.parent / "day23"))

from rag_core import retrieve  # noqa: E402  (День 22: поиск по индексу Дня 21)
from rerank import rerank_full  # noqa: E402  (День 23: cross-encoder → score 0..1)

from openai import OpenAI  # noqa: E402

# ---------- .env (ключи не хардкодим) ----------
for _line in (BASE / ".env").read_text().splitlines() if (BASE / ".env").exists() else []:
    if "=" in _line and not _line.startswith("#"):
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

# ---------- Настройки конвейера (наследуем смысл Дня 23) ----------
CANDIDATES = 20      # сколько поиск отдаёт реранкеру
FINAL_K = 5          # сколько кусков уходит модели после фильтра
THRESHOLD = 0.54     # порог-отказ по score реранкера. Калибровано на golden set (05.07):
                     # свои легли 0.581..0.726, ловушки 0.500..0.501 → яма, черта в середину.
                     # 0.30 (с Дня 23) занижен: ловушки 0.50 проходили вход, отбивал только
                     # grounding модели. 0.54 ловит их уже на входе. Риск: слэнг может просесть
                     # к черте (грабля Дня 23) → редкий ложный отказ; в нашем домене отказ
                     # безопаснее вранья, поэтому черту держим наверху.
FUZZ_PASS = 90       # порог дословности цитаты (rapidfuzz partial_ratio, 0..100)


# ---------- Провайдер: DeepSeek или OpenRouter ----------
def _provider() -> tuple[str, str, str, str]:
    if os.getenv("DEEPSEEK_API_KEY"):
        return ("deepseek", "https://api.deepseek.com",
                os.environ["DEEPSEEK_API_KEY"], "deepseek-chat")
    return ("openrouter", "https://openrouter.ai/api/v1",
            os.environ["OPENROUTER_API_KEY"], "openai/gpt-oss-20b:free")


PROVIDER, _BASE_URL, _KEY, MODEL = _provider()
_client = None


def _chat(messages, json_mode=True, max_tokens=800, tries=5) -> str:
    """Вызов модели. json_mode → response_format=json_object (мягкий, его держат оба
    провайдера). Ретрай на 429/пустой ответ (наша боль free-tier)."""
    global _client
    if _client is None:
        _client = OpenAI(base_url=_BASE_URL, api_key=_KEY, timeout=90)
    kw = {}
    if json_mode:
        kw["response_format"] = {"type": "json_object"}
    if PROVIDER == "openrouter":                    # gpt-oss — reasoning-модель
        kw["extra_body"] = {"reasoning": {"effort": "low"}}
    last = ""
    for _ in range(tries):
        try:
            r = _client.chat.completions.create(
                model=MODEL, temperature=0, max_tokens=max_tokens, messages=messages, **kw)
            content = (r.choices[0].message.content or "").strip()
            if content:
                return content
            last = "(пустой ответ)"
        except Exception as e:
            last = f"({type(e).__name__})"
        time.sleep(4)
    return last


def _parse_json(raw: str) -> dict | None:
    """Толерантный разбор: берём первый {...} блок и парсим (модель иногда
    оборачивает JSON в markdown/текст)."""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


# ---------- Узел 1: контракт {answer, sources, quotes} ----------
CONTRACT_TEMPLATE = (
    "Ты — ассистент, отвечающий СТРОГО по источникам ниже.\n"
    "Верни ТОЛЬКО JSON-объект (без markdown, без пояснений) ровно такой формы:\n"
    '{"answer": "<ответ по-русски, кратко>", '
    '"sources": [{"chunk_id": <номер источника>, "section": "<раздел>"}], '
    '"quotes": ["<ДОСЛОВНЫЙ фрагмент из источника, слово в слово как в тексте, '
    'без перевода и без изменений>"]}\n'
    "Правила:\n"
    "1. Отвечай только по источникам, не добавляй знания из головы.\n"
    "2. sources — только те куски, на которые реально опёрся (не все подряд).\n"
    "3. quotes — дословные куски ИЗ текста источников, подтверждающие ответ.\n"
    "4. Если ответа в источниках нет — верни answer «В источниках нет.», "
    "sources и quotes пустыми."
)


def _context(chunks: list[dict]) -> str:
    """Куски → пронумерованный контекст с chunk_id и разделом (метки Дня 21)."""
    return "\n\n".join(
        f"[Источник {i + 1}] (chunk_id={i + 1}, раздел: {c.get('section', '?')})\n{c['text']}"
        for i, c in enumerate(chunks))


def ask_contract(question: str, chunks: list[dict]) -> dict:
    """Спросить модель по контракту, разобрать JSON, дотянуть форму до {answer,sources,quotes}."""
    user = f"ИСТОЧНИКИ:\n{_context(chunks)}\n\nВОПРОС: {question}"
    raw = _chat([{"role": "system", "content": CONTRACT_TEMPLATE},
                 {"role": "user", "content": user}])
    obj = _parse_json(raw)
    if not obj:
        return {"answer": raw or "(модель не дала ответ)", "sources": [], "quotes": [],
                "parse_ok": False, "raw": raw}
    return {
        "answer": str(obj.get("answer", "")).strip(),
        "sources": obj.get("sources") or [],
        "quotes": [q for q in (obj.get("quotes") or []) if isinstance(q, str) and q.strip()],
        "parse_ok": True,
        "raw": raw,
    }


# ---------- Узел 2: проверка цитат КОДОМ (substring → fuzzy) ----------
def _norm(s: str) -> str:
    """Нормализация для сверки: нижний регистр, единые кавычки/тире, схлопнутые пробелы."""
    s = s.lower()
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    s = s.replace("–", "-").replace("—", "-").replace("…", "...")
    s = re.sub(r"\s+", " ", s).strip(" .,\"'")
    return s


def verify_quotes(quotes: list[str], chunks: list[dict]) -> list[dict]:
    """Каждую цитату ищем в тексте кусков: сначала дословно (substring), потом с
    поблажкой на косметику (fuzzy). Возвращаем вердикт по каждой цитате."""
    norm_chunks = [(i + 1, _norm(c["text"])) for i, c in enumerate(chunks)]
    out = []
    for q in quotes:
        qn = _norm(q)
        found = next((cid for cid, t in norm_chunks if qn and qn in t), None)
        if found is not None:
            out.append({"quote": q, "matched": True, "method": "substring",
                        "chunk_id": found, "score": 100})
            continue
        best_id, best = None, 0
        for cid, t in norm_chunks:
            sc = fuzz.partial_ratio(qn, t)
            if sc > best:
                best, best_id = sc, cid
        out.append({"quote": q, "matched": best >= FUZZ_PASS,
                    "method": "fuzzy" if best >= FUZZ_PASS else "none",
                    "chunk_id": best_id, "score": round(best, 1)})
    return out


# ---------- Узел 4: faithfulness — LLM-судья ----------
JUDGE_SYS = (
    "Ты — придирчивый проверяющий. Тебе дают ОТВЕТ и ЦИТАТЫ-опоры.\n"
    "Реши, следует ли ответ ИЗ цитат (не из общих знаний). Верни ТОЛЬКО JSON:\n"
    '{"verdict": "supported|partial|unsupported", "reason": "<кратко по-русски>"}\n'
    "supported — всё в ответе подкреплено цитатами; partial — часть; "
    "unsupported — ответ не вытекает из цитат."
)


def faithfulness_judge(answer: str, quotes: list[str]) -> dict:
    """Проверка смысла: опирается ли ответ на цитаты. Код проверил БУКВЫ цитат,
    судья проверяет СВЯЗЬ ответ←цитата (перефраз/подгонку код не ловит)."""
    if not quotes:
        return {"verdict": "unsupported", "reason": "нет подтверждённых цитат"}
    payload = ("ОТВЕТ:\n" + answer + "\n\nЦИТАТЫ-ОПОРЫ:\n"
               + "\n".join(f"- {q}" for q in quotes))
    obj = _parse_json(_chat([{"role": "system", "content": JUDGE_SYS},
                             {"role": "user", "content": payload}]))
    if not obj or "verdict" not in obj:
        return {"verdict": "unknown", "reason": "судья не дал разбор"}
    return {"verdict": obj["verdict"], "reason": str(obj.get("reason", "")).strip()}


# ---------- Полный конвейер Дня 24 ----------
def answer(question: str, threshold: float = THRESHOLD, judge: bool = True) -> dict:
    """вопрос → поиск → реранк → ПОРОГ(вход) → контракт → проверка цитат(выход) → судья.

    Чистка на выходе: неподтверждённые цитаты выкидываем; если после чистки не осталось
    ни одной опоры — ответ не показываем (downgrade к «не могу подтвердить»)."""
    candidates = retrieve(question, k=CANDIDATES)
    graded = rerank_full(question, candidates, top_k=FINAL_K, threshold=threshold)
    kept = [c for c in graded if c.get("kept")]
    top_score = graded[0]["score"] if graded else 0.0

    # --- ВХОД: порог-отказ ---
    if not kept:
        return {"question": question, "abstained": True, "reason": "below_threshold",
                "top_score": top_score, "answer": "Не знаю — в источниках нет ответа. "
                "Уточните вопрос.", "graded": graded, "kept": [], "quotes": [],
                "checked": [], "faithfulness": None}

    # --- контракт ---
    c = ask_contract(question, kept)
    model_abstained = "в источниках нет" in c["answer"].lower() and not c["quotes"]

    # --- ВЫХОД: проверка цитат кодом ---
    checked = verify_quotes(c["quotes"], kept)
    verified = [x["quote"] for x in checked if x["matched"]]

    # чистка: если модель что-то ответила, но НИ ОДНА цитата не подтвердилась — не верим
    unverifiable = bool(c["quotes"]) and not verified
    if model_abstained:
        final_answer, status = c["answer"], "model_abstained"
    elif unverifiable:
        final_answer = "Не могу подтвердить ответ ссылками на источник."
        status = "unverifiable"
    else:
        final_answer, status = c["answer"], "answered"

    # --- судья (только если есть что судить) ---
    faith = None
    if judge and verified and status == "answered":
        faith = faithfulness_judge(c["answer"], verified)

    return {
        "question": question, "abstained": False, "status": status,
        "top_score": top_score, "answer": final_answer,
        "model_answer": c["answer"], "parse_ok": c["parse_ok"],
        "sources": c["sources"], "quotes": c["quotes"], "checked": checked,
        "verified_n": len(verified), "faithfulness": faith,
        "graded": graded, "kept": kept, "provider": PROVIDER, "model": MODEL,
    }

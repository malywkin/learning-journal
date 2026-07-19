"""
День 35 — RAG-ответ по одной рубрике дайджеста. Ядро Дня 24, наведённое на корпус.

Ничего с нуля: соединяю два кубика из разных недель.
  • ПОИСК по корпусу гайдлайнов — из Дня 31 (docs_tool.search_docs: bge-m3 + реранкер
    Дня 23). Он ищет куски и несёт source (какой файл-гайдлайн) для честной ссылки.
  • ПРОВЕРКА ответа — из Дня 24 (контракт {answer,sources,quotes} + сверка цитат кодом
    + порог-отказ + faithfulness-судья). Эти функции работают с ПЕРЕДАННЫМИ кусками,
    поэтому их можно кормить корпусом гайдлайнов, а не индексом книги.

Зачем так строго для дайджеста: тема медицинская, а из брифа Дня 35 — на слабой модели
дозировки/диагнозы ломаются, дисклеймеры у платформ исчезли (Stanford: 26%→<1%), родители
не отличают AI от врача. Поэтому «заземление на источник + отказ вместо выдумки» здесь
не украшение, а обязательное условие. Порог тот же (0.54), калиброван на Дне 24.

Провайдер §14: DeepSeek основной → OpenRouter запасной → локальный qwen. Ключи из .env.
"""
import json
import os
import re
import time

from openai import OpenAI
from rapidfuzz import fuzz

import config
from docs_tool import search_docs        # поиск по корпусу (День 31: bge-m3 + реранкер Дня 23)


# ---------- Провайдер модели (§14: основной → запасной) ----------
def _providers() -> list[dict]:
    out = []
    if os.getenv("DEEPSEEK_API_KEY"):
        out.append({"name": "deepseek", "base_url": config.DEEPSEEK_BASE_URL,
                    "key": os.environ["DEEPSEEK_API_KEY"], "model": config.DEEPSEEK_MODEL})
    if os.getenv("OPENROUTER_API_KEY"):
        out.append({"name": "openrouter", "base_url": config.OPENROUTER_BASE_URL,
                    "key": os.environ["OPENROUTER_API_KEY"], "model": config.OPENROUTER_MODEL})
    out.append({"name": "local", "base_url": config.LOCAL_BASE_URL,
                "key": "lm-studio", "model": config.LOCAL_MODEL})
    return out


_clients: dict[str, OpenAI] = {}


def _client(p: dict) -> OpenAI:
    if p["name"] not in _clients:
        _clients[p["name"]] = OpenAI(base_url=p["base_url"], api_key=p["key"], timeout=90)
    return _clients[p["name"]]


def _chat(messages, json_mode=True, max_tokens=700, tries=3) -> tuple[str, str]:
    """Один вызов модели с fallback по провайдерам. Возвращает (текст, имя_провайдера).
    json_object мягкий — держат оба облака (строгий json_schema не держит никто, День 24)."""
    kw = {"response_format": {"type": "json_object"}} if json_mode else {}
    last = "(нет провайдеров)"
    for p in _providers():
        extra = {"extra_body": {"reasoning": {"effort": "low"}}} if p["name"] == "openrouter" else {}
        msgs = messages
        if p["name"] == "local":                       # гашение thinking у MLX-Qwen (День 28)
            msgs = list(messages) + [{"role": "assistant", "content": "<think></think>"}]
        for _ in range(tries):
            try:
                r = _client(p).chat.completions.create(
                    model=p["model"], temperature=0, max_tokens=max_tokens, messages=msgs, **kw, **extra)
                content = (r.choices[0].message.content or "").strip()
                if content:
                    return content, p["name"]
                last = f"{p['name']}: (пусто)"
            except Exception as e:
                last = f"{p['name']}: {type(e).__name__}"
                break                                  # провайдер лёг — идём к следующему
        time.sleep(1)
    return f"(модель недоступна: {last})", "none"


def _parse_json(raw: str) -> dict | None:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


# ---------- Контракт с медицинскими ограничителями (ядро Дня 24 + бриф Дня 35) ----------
CONTRACT_TEMPLATE = (
    "Ты — помощник, который делает выжимку для родителя СТРОГО по официальным "
    "источникам ниже (гайдлайны NHS/CDC). Верни ТОЛЬКО JSON-объект такой формы:\n"
    '{"answer": "<2–4 фразы по-русски, спокойно и по делу>", '
    '"sources": [{"chunk_id": <номер источника>, "section": "<раздел>"}], '
    '"quotes": ["<ДОСЛОВНЫЙ фрагмент из источника, как в тексте>"]}\n'
    "Правила:\n"
    "1. Отвечай ТОЛЬКО по источникам, не добавляй знания из головы.\n"
    "2. НЕ называй дозировки лекарств и НЕ ставь диагноз по симптомам — если это "
    "нужно, посоветуй обратиться к врачу/акушерке.\n"
    "3. НЕ выдумывай числа (сроки, объёмы, температуру) — только те, что есть в источнике.\n"
    "4. НЕ используй понятия «скачок развития по неделям», «окна бодрствования», "
    "«регресс сна» — их нет в доказательной медицине.\n"
    "5. quotes — дословные куски ИЗ источников, подтверждающие ответ.\n"
    "6. Если в источниках нет ответа — answer «В источниках нет.», sources и quotes пустыми."
)


def _context(chunks: list[dict]) -> str:
    return "\n\n".join(
        f"[Источник {i + 1}] (chunk_id={i + 1}, файл: {c.get('source', '?')}, раздел: {c.get('section', '?')})\n{c['text']}"
        for i, c in enumerate(chunks))


def ask_contract(question: str, chunks: list[dict]) -> tuple[dict, str]:
    user = f"ИСТОЧНИКИ:\n{_context(chunks)}\n\nЗАПРОС: {question}"
    raw, provider = _chat([{"role": "system", "content": CONTRACT_TEMPLATE},
                           {"role": "user", "content": user}])
    obj = _parse_json(raw)
    if not obj:
        return ({"answer": raw or "(модель не дала ответ)", "sources": [], "quotes": [],
                 "parse_ok": False}, provider)
    return ({
        "answer": str(obj.get("answer", "")).strip(),
        "sources": obj.get("sources") or [],
        "quotes": [q for q in (obj.get("quotes") or []) if isinstance(q, str) and q.strip()],
        "parse_ok": True,
    }, provider)


# ---------- Проверка цитат КОДОМ (substring → fuzzy) — узел Дня 24 ----------
def _norm(s: str) -> str:
    s = s.lower()
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    s = s.replace("–", "-").replace("—", "-").replace("…", "...")
    s = re.sub(r"\s+", " ", s).strip(" .,\"'")
    return s


def verify_quotes(quotes: list[str], chunks: list[dict]) -> list[dict]:
    norm_chunks = [(i + 1, _norm(c["text"])) for i, c in enumerate(chunks)]
    out = []
    for q in quotes:
        qn = _norm(q)
        found = next((cid for cid, t in norm_chunks if qn and qn in t), None)
        if found is not None:
            out.append({"quote": q, "matched": True, "method": "substring", "chunk_id": found, "score": 100})
            continue
        best_id, best = None, 0
        for cid, t in norm_chunks:
            sc = fuzz.partial_ratio(qn, t)
            if sc > best:
                best, best_id = sc, cid
        out.append({"quote": q, "matched": best >= config.FUZZ_PASS,
                    "method": "fuzzy" if best >= config.FUZZ_PASS else "none",
                    "chunk_id": best_id, "score": round(best, 1)})
    return out


# ---------- faithfulness-судья — узел Дня 24 ----------
JUDGE_SYS = (
    "Ты — придирчивый проверяющий. Тебе дают ОТВЕТ и ЦИТАТЫ-опоры. Реши, следует ли "
    "ответ ИЗ цитат (не из общих знаний). Верни ТОЛЬКО JSON:\n"
    '{"verdict": "supported|partial|unsupported", "reason": "<кратко по-русски>"}'
)


def faithfulness_judge(answer: str, quotes: list[str]) -> dict:
    if not quotes:
        return {"verdict": "unsupported", "reason": "нет подтверждённых цитат"}
    payload = "ОТВЕТ:\n" + answer + "\n\nЦИТАТЫ-ОПОРЫ:\n" + "\n".join(f"- {q}" for q in quotes)
    obj = _parse_json(_chat([{"role": "system", "content": JUDGE_SYS},
                             {"role": "user", "content": payload}])[0])
    if not obj or "verdict" not in obj:
        return {"verdict": "unknown", "reason": "судья не дал разбор"}
    return {"verdict": obj["verdict"], "reason": str(obj.get("reason", "")).strip()}


# ---------- Полный конвейер одной рубрики (вход→порог→контракт→выход→судья) ----------
def grounded_answer(query: str, judge: bool = True) -> dict:
    """Запрос рубрики → поиск по корпусу → ПОРОГ → контракт → проверка цитат → судья.
    Возвращает готовый блок рубрики со ссылками и пометкой доверия (или честный отказ)."""
    hits = search_docs(query, k=config.FINAL_K)          # День 31: поиск + реранкер Дня 23
    top = hits[0]["score"] if hits else 0.0

    # --- ВХОД: порог-отказ (День 24). Слабая релевантность → молчим, не выдумываем ---
    if not hits or top < config.THRESHOLD:
        return {"query": query, "abstained": True, "status": "below_threshold",
                "top_score": round(top, 3), "answer": "", "sources": [], "quotes": [],
                "kept": [], "checked": [], "faithfulness": None, "provider": None}

    c, provider = ask_contract(query, hits)
    model_abstained = "в источниках нет" in c["answer"].lower() and not c["quotes"]

    # --- ВЫХОД: проверка цитат кодом (День 24) ---
    checked = verify_quotes(c["quotes"], hits)
    verified = [x["quote"] for x in checked if x["matched"]]
    unverifiable = bool(c["quotes"]) and not verified

    if model_abstained:
        final, status = "", "model_abstained"
    elif unverifiable:
        final, status = c["answer"], "unverifiable"      # ответ есть, но опоры не подтвердились
    else:
        final, status = c["answer"], "answered"

    faith = faithfulness_judge(c["answer"], verified) if (judge and verified and status == "answered") else None

    return {
        "query": query, "abstained": status == "model_abstained", "status": status,
        "top_score": round(top, 3), "answer": final,
        "sources": c["sources"], "quotes": c["quotes"], "checked": checked,
        "verified_n": len(verified), "faithfulness": faith,
        "kept": hits, "provider": provider,
    }


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "признаки начала родов, когда ехать в роддом"
    r = grounded_answer(q)
    print(f"порог top_score={r['top_score']} status={r.get('status')} провайдер={r.get('provider')}")
    print("ОТВЕТ:", r["answer"] or "(отказ)")
    for ch in r["checked"]:
        print(f"  цитата [{ch['method']} {ch['score']}]: {ch['quote'][:70]}…")

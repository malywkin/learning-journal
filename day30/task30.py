"""
День 30 — локальная LLM как приватный сервис.

Тонкий прокси перед LM Studio. Наружу на Wi-Fi торчит ТОЛЬКО этот прокси;
сам LM Studio остаётся на localhost и снаружи недоступен. Прокси добавляет то,
чего у голого демона нет: пароль на входе, ограничитель по токенам, обрезку
контекста, очередь и веб-чат.

Запуск:
    Tasks/day21/.venv/bin/python -m uvicorn task30:app --host 0.0.0.0 --port 8000
"""
import os
import json
import time
import asyncio
from collections import deque

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from openai import AsyncOpenAI

load_dotenv()

# --- конфиг из .env (см. .env / .env.example) ---
PROXY_API_KEY = os.getenv("PROXY_API_KEY", "change-me")  # реальный ключ — в .env (в git не идёт)
LMSTUDIO_URL = os.getenv("LMSTUDIO_URL", "http://localhost:1234/v1")
MODEL = os.getenv("MODEL", "qwen3.5-9b-mlx")
RATE_WINDOW_SEC = int(os.getenv("RATE_WINDOW_SEC", "60"))
RATE_TOKEN_BUDGET = int(os.getenv("RATE_TOKEN_BUDGET", "6000"))
MAX_CONTEXT_TOKENS = int(os.getenv("MAX_CONTEXT_TOKENS", "3500"))
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "400"))
CONCURRENCY = int(os.getenv("CONCURRENCY", "1"))

SYSTEM_PROMPT = "Ты дружелюбный помощник. Отвечай кратко и по делу, на русском."

# LM Studio совместим с OpenAI SDK — тот же клиент, что на Днях 27–29, только async.
client = AsyncOpenAI(base_url=LMSTUDIO_URL, api_key="lm-studio")

app = FastAPI(title="День 30 — приватный LLM-сервис")

# --- очередь: пускаем в MLX по одному (CONCURRENCY=1), остальные ждут семафор ---
sem = asyncio.Semaphore(CONCURRENCY)
stats = {"in_flight": 0, "waiting": 0}

# --- ограничитель по токенам: скользящее окно (ts, tokens) ---
usage_window: deque = deque()


def estimate_tokens(text: str) -> int:
    """Грубая оценка: ~4 символа на токен. Точного токенайзера у локального
    сервера нет, для лимита достаточно приближения (честно помечаем как оценку)."""
    return max(1, len(text) // 4)


def budget_used() -> int:
    """Сколько токенов потрачено за последнее окно (чистит устаревшее)."""
    now = time.monotonic()
    while usage_window and now - usage_window[0][0] > RATE_WINDOW_SEC:
        usage_window.popleft()
    return sum(tok for _, tok in usage_window)


def check_auth(authorization: str | None):
    """Ключ на входе: клиент шлёт Authorization: Bearer <ключ>."""
    expected = f"Bearer {PROXY_API_KEY}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Нужен верный ключ (Authorization: Bearer ...)")


@app.get("/health")
async def health():
    """Публичная проверка живости — без ключа (как /health у llama.cpp)."""
    return {"ok": True, "model": MODEL}


@app.get("/api/stats")
async def api_stats():
    """Живые метрики для веб-чата: очередь + расход бюджета."""
    return {
        "in_flight": stats["in_flight"],
        "waiting": stats["waiting"],
        "budget_used": budget_used(),
        "budget_total": RATE_TOKEN_BUDGET,
        "window_sec": RATE_WINDOW_SEC,
        "concurrency": CONCURRENCY,
    }


@app.post("/api/chat")
async def api_chat(request: Request, authorization: str | None = Header(default=None)):
    check_auth(authorization)

    body = await request.json()
    user_msg = (body.get("message") or "").strip()
    if not user_msg:
        raise HTTPException(status_code=400, detail="Пустое сообщение")

    # --- max context: не роняем длинный вход молча, а сами режем до окна ---
    orig_tokens = estimate_tokens(user_msg)
    truncated = False
    # оставляем место под system-промпт и ответ
    ctx_room = MAX_CONTEXT_TOKENS - estimate_tokens(SYSTEM_PROMPT) - MAX_OUTPUT_TOKENS
    if orig_tokens > ctx_room:
        keep_chars = ctx_room * 4
        user_msg = user_msg[:keep_chars]
        truncated = True
    sent_tokens = estimate_tokens(user_msg)

    # --- rate limit по токенам: пессимистичная цена = вход + потолок ответа ---
    cost = sent_tokens + MAX_OUTPUT_TOKENS
    used = budget_used()
    if used + cost > RATE_TOKEN_BUDGET:
        retry = RATE_WINDOW_SEC
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(retry)},
            content={
                "error": "Превышен лимит токенов на окно",
                "budget_used": used,
                "budget_total": RATE_TOKEN_BUDGET,
                "retry_after": retry,
            },
        )
    usage_window.append((time.monotonic(), cost))

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
        # префилл пустого <think></think> — гасит зависание думающей MLX-Qwen
        # (приём с Дней 28–29: request-флаги гашения на MLX мертвы).
        {"role": "assistant", "content": "<think></think>"},
    ]

    async def generate():
        t0 = time.monotonic()
        stats["waiting"] += 1
        async with sem:                      # ждём очередь (MLX жуёт по одному)
            stats["waiting"] -= 1
            stats["in_flight"] += 1
            queue_wait_ms = int((time.monotonic() - t0) * 1000)
            try:
                # первая строка потока — мета (обрезка, ожидание в очереди)
                meta = {
                    "truncated": truncated,
                    "orig_tokens": orig_tokens,
                    "sent_tokens": sent_tokens,
                    "queue_wait_ms": queue_wait_ms,
                }
                yield json.dumps(meta, ensure_ascii=False) + "\n"

                stream = await client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    stream=True,
                    temperature=0.3,             # как на Дне 29
                    max_tokens=MAX_OUTPUT_TOKENS,  # в облаке 2026 — max_completion_tokens
                    extra_body={"min_p": 0.05},   # адаптивный порог, как на Дне 29
                )
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
            except Exception as e:
                yield f"\n\n[ошибка сервера: {e}]"
            finally:
                stats["in_flight"] -= 1

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")


@app.get("/")
async def index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "index.html"))

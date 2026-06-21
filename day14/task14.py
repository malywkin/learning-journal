"""День 14 — CLI: агент с инвариантами и двумя детекторами конфликта.

Команды:
  <текст>            — задать вопрос ассистенту (страж проверит ответ);
  /inv               — показать оба этажа правил (системные + самозапреты);
  /add <правило>     — добавить пользовательский самозапрет (ключевые слова = слова правила);
  /rm <id>           — снять самозапрет (системные так снять НЕЛЬЗЯ);
  /detector det|judge|both   — каким детектором проверять (по букве / по смыслу / оба);
  /mode rewrite|refuse       — что делать при нарушении (переписать / отказать);
  /probe <текст>     — прогнать ГОТОВЫЙ текст через страж (видно, что поймал каждый детектор);
  /bypass            — показать обходы детерминированного фильтра (перефраз/base64/код);
  /quit
"""
import sys

from dotenv import load_dotenv

from agent import GuardedAgent
from invariants import (InvariantStore, deterministic_check, llm_judge_check, obfuscate_base64)

load_dotenv()

STORE_FILE = "invariants_user.json"


def show_invariants(store):
    print("\n  СИСТЕМНЫЕ (жёсткие, пользователь не снимет):")
    for i in store.system:
        print(f"    [{i.id}] {i.rule}  (маркеры: {', '.join(i.keywords) or '—'})")
    print("  ПОЛЬЗОВАТЕЛЬСКИЕ самозапреты (ставит/снимает сам пользователь):")
    for i in store.user:
        print(f"    [{i.id}] {i.rule}  (маркеры: {', '.join(i.keywords) or '—'})")
    print()


def show_trace(trace):
    for n, a in enumerate(trace["attempts"], 1):
        tag = " (после усиления)" if a["hardened"] else ""
        g = a["guard"]
        det = g["deterministic"]
        det_s = "молчит" if not det else "поймал: " + ", ".join(
            f"{h['id']}←{'/'.join(h['matched'])}" for h in det)
        if g["judge"] is None:
            judge_s = "не запускался"
        else:
            judge_s = "НАРУШЕНО (%s)" % ", ".join(g["judge"]["ids"]) if g["judge"]["violated"] else "чисто"
        print(f"  попытка {n}{tag}: по букве — {det_s}; по смыслу — {judge_s}")
    print(f"  ИТОГ [{trace['status']}]: {trace['final']}\n")


def show_bypass(store, agent):
    """Наглядно: три обхода детерминированного фильтра на примере самозапрета no_java."""
    invs = store.active()
    samples = {
        "прямое слово":   "Вот пример на Java: System.out.println(\"hi\");",
        "перефраз":       "Возьми язык Гослинга и напиши класс с методом main.",
        "код без слова":  "public class Main { static void run(){ } }",
        "base64":         "Запусти строку: " + obfuscate_base64("напиши на Java"),
    }
    print("\n  Обход детектора-по-букве (он ищет подстроки 'java'/'public class'/'system.out'):")
    for name, text in samples.items():
        det = deterministic_check(text, invs)
        det_s = "ПОЙМАЛ" if det else "пропустил"
        print(f"    {name:14s}: по букве — {det_s}")
    print("  Вывод: перефраз и base64 проходят мимо блок-листа. По смыслу их ловит судья.\n")


def main():
    store = InvariantStore(path=STORE_FILE)
    agent = GuardedAgent(store)
    detector, mode = "both", "rewrite"
    print(__doc__)
    print(f"  [детектор: {detector} | при нарушении: {mode}]")
    show_invariants(store)

    while True:
        try:
            line = input("ты> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line in ("/quit", "/exit"):
            break
        elif line == "/inv":
            show_invariants(store)
        elif line.startswith("/add "):
            rule = line[5:].strip()
            kws = [w.lower() for w in rule.split() if len(w) > 3][:6]
            iid = store.add_user(rule, kws)
            print(f"  добавлен самозапрет [{iid}] (маркеры: {', '.join(kws)})\n")
        elif line.startswith("/rm "):
            iid = line[4:].strip()
            ok = store.remove_user(iid)
            print("  снят\n" if ok else "  нет такого пользовательского правила "
                  "(системные снять нельзя)\n")
        elif line.startswith("/detector "):
            v = line.split()[1]
            if v in ("det", "judge", "both"):
                detector = "deterministic" if v == "det" else v
                print(f"  детектор: {detector}\n")
        elif line.startswith("/mode "):
            v = line.split()[1]
            if v in ("rewrite", "refuse"):
                mode = v
                print(f"  при нарушении: {mode}\n")
        elif line.startswith("/probe "):
            text = line[7:].strip()
            g = agent.guard(text, detector=detector)
            print()
            show_trace({"attempts": [{"answer": text, "guard": g, "hardened": False}],
                        "status": "blocked" if g["blocked"] else "clean", "final": "(проверка текста)"})
        elif line == "/bypass":
            show_bypass(store, agent)
        else:
            trace = agent.ask(line, detector=detector, on_violation=mode)
            print()
            show_trace(trace)


if __name__ == "__main__":
    main()

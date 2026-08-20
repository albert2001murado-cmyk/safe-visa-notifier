from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

URL = "https://travel.state.gov/content/travel/en/us-visas/visa-information-resources/global-visa-wait-times.html"
STATE_PATH = Path("action_state.json")

SUPPORTED = {
    "Almaty": "Kazakhstan",
    "Astana": "Kazakhstan",
    "Warsaw": "Poland",
    "Krakow": "Poland",
    "Yerevan": "Armenia",
}

VISA_INDEX = {
    "B1B2": 2,
    "FMJ": 3,
    "PETITION": 4,
    "CREW": 5,
}

VISA_LABEL = {
    "B1B2": "Туризм / бизнес B1/B2",
    "FMJ": "Учёба / обмен F, M, J",
    "PETITION": "Рабочие H, L, O, P, Q",
    "CREW": "Экипаж / транзит C, D, C1/D",
}

MONTH_NAMES = (
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
)


def clean(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def parse_months(value: str) -> float | None:
    text = clean(value)
    if not text or text.upper() in {"NA", "N/A"}:
        return None
    if re.search(r"<\s*0[.,]?5", text, flags=re.I):
        return 0.49
    match = re.search(r"(\d+(?:[.,]\d+)?)", text)
    return float(match.group(1).replace(",", ".")) if match else None


def format_months(months: float | None, raw: str) -> str:
    if months is None:
        return raw or "неизвестно"
    if months < 0.5:
        return "меньше 0.5 месяца"
    return f"{months:g} мес."


def approximate_date(months: float | None) -> str:
    if months is None:
        return "неизвестно"
    whole_months = max(0, int(round(months)))
    today = date.today()
    total = today.year * 12 + (today.month - 1) + whole_months
    year, month_index = divmod(total, 12)
    return f"{MONTH_NAMES[month_index]} {year} года"


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "да"}


def get_float_env(name: str, default: float, minimum: float | None = None, maximum: float | None = None) -> float:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = float(raw.replace(",", "."))
    except ValueError:
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def load_html() -> str:
    # Официальная страница иногда отдаёт 403 на обычные HTTP-запросы.
    # Playwright открывает её как обычный браузер, без входа в аккаунт и без обхода личного кабинета.
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            )
        )
        page.goto(URL, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(5_000)
        html = page.content()
        browser.close()
        return html


def parse_table(html: str, cities: list[str], visa_type: str) -> dict[str, dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, dict[str, Any]] = {}
    index = VISA_INDEX[visa_type]

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = [clean(c.get_text(" ")) for c in row.find_all(["td", "th"])]
            if len(cells) <= index:
                continue
            city = cells[0]
            if city not in cities:
                continue
            raw = cells[index]
            result[city] = {"raw": raw, "months": parse_months(raw)}

    if not result:
        raise RuntimeError(
            "Официальная таблица не найдена или сайт временно не отдал данные. "
            "Попробуйте вручную запустить workflow позже."
        )
    return result


def send_message(token: str, chat_id: str, text: str) -> None:
    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}
    ).encode()
    request = urllib.request.Request(endpoint, data=payload, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8", errors="replace")
        if response.status != 200:
            raise RuntimeError(f"Telegram API: {response.status}: {body}")


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def make_status_line(city: str, visa_type: str, raw: str, months: float | None, target: float, horizon: float) -> str:
    if months is None:
        horizon_text = "Горизонт: определить невозможно"
    elif months <= horizon:
        horizon_text = f"✅ Входит в горизонт {horizon:g} мес."
    else:
        horizon_text = f"⏳ Дальше горизонта {horizon:g} мес."

    return (
        f"📍 {SUPPORTED[city]}, {city}\n"
        f"🎫 {VISA_LABEL[visa_type]}\n"
        f"Сейчас: {format_months(months, raw)}\n"
        f"Ориентировочно: {approximate_date(months)}\n"
        f"{horizon_text}\n"
        f"Срочный порог: ≤ {target:g} мес."
    )


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    cities_raw = os.environ.get("VISA_CITIES", "Almaty,Astana,Warsaw,Krakow,Yerevan")
    visa_type = os.environ.get("VISA_TYPE", "B1B2").strip().upper()
    target = get_float_env("TARGET_MONTHS", 2, minimum=0.1, maximum=36)
    horizon = get_float_env("SEARCH_HORIZON_MONTHS", 36, minimum=1, maximum=36)
    send_status = env_bool("SEND_STATUS", False)

    if not token or not chat_id:
        raise RuntimeError("Не заданы TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID.")
    if visa_type not in VISA_INDEX:
        raise RuntimeError(f"Неизвестный VISA_TYPE: {visa_type}. Допустимо: {', '.join(VISA_INDEX)}")

    cities = [c.strip() for c in cities_raw.split(",") if c.strip()]
    unknown = [c for c in cities if c not in SUPPORTED]
    if unknown:
        raise RuntimeError(f"Неизвестные города: {', '.join(unknown)}")

    try:
        html = load_html()
        current = parse_table(html, cities, visa_type)
    except Exception as exc:
        message = (
            "⚠️ Проверка временно не получила официальную таблицу\n\n"
            f"Причина: {exc}\n\n"
            "Это не ошибка токена и не ошибка Telegram. Такое бывает, когда официальный сайт "
            "Госдепартамента временно не отдаёт таблицу GitHub-серверу или меняет структуру страницы.\n\n"
            "Бот ничего не бронирует и не обходит личный кабинет. Просто попробуйте запустить workflow позже "
            "или дождитесь следующей автоматической проверки. Компьютер для этого держать включённым не нужно."
            f"\n\nИсточник: {URL}"
        )
        if send_status:
            send_message(token, chat_id, message)
        print(message)
        return 0

    previous = load_state()
    new_state = dict(previous)
    alerts: list[str] = []
    status_lines: list[str] = []

    for city in cities:
        item = current.get(city)
        if not item:
            status_lines.append(f"📍 {city}\nДанные временно не найдены")
            continue

        months = item["months"]
        raw = item["raw"]
        key = f"{visa_type}:{city}"
        old = previous.get(key, {}).get("months")

        new_state[key] = {
            "city": city,
            "country": SUPPORTED[city],
            "visa_type": visa_type,
            "raw": raw,
            "months": months,
            "target_months": target,
            "search_horizon_months": horizon,
        }

        status_lines.append(make_status_line(city, visa_type, raw, months, target, horizon))

        if months is None:
            continue

        within_horizon = months <= horizon
        improved = old is not None and months < old
        threshold_crossed = months <= target and (old is None or old > target)

        if within_horizon and (improved or threshold_crossed):
            reason = "официальное ожидание уменьшилось" if improved else "показатель достиг выбранного порога"
            alerts.append(
                f"🔔 {reason}\n" + make_status_line(city, visa_type, raw, months, target, horizon)
            )

    STATE_PATH.write_text(json.dumps(new_state, ensure_ascii=False, indent=2), encoding="utf-8")

    safety_text = (
        "\n\nПроверьте календарь вручную в официальной системе записи. "
        "Это уведомление основано на публичном ориентировочном сроке ожидания "
        "и не подтверждает конкретный свободный день."
        f"\n\nИсточник: {URL}"
    )

    if alerts:
        send_message(token, chat_id, "\n\n".join(alerts) + safety_text)
        print("Notification sent")
    elif send_status:
        send_message(token, chat_id, "✅ Ручная проверка выполнена\n\n" + "\n\n".join(status_lines) + safety_text)
        print("Status sent")
    else:
        print("No meaningful changes")
        print("\n\n".join(status_lines))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import load_settings
from app.db import Database, Subscription
from app.visa_wait_times import LOCATIONS, VISA_TYPES, WAIT_TIMES_URL, fetch_wait_times, get_wait_time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
router = Router()
db: Optional[Database] = None
bot: Optional[Bot] = None
pending: dict[int, dict[str, str]] = {}


def kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=data) for text, data in row] for row in rows
    ])


def main_menu() -> InlineKeyboardMarkup:
    return kb([
        [("➕ Добавить отслеживание", "menu:add")],
        [("📊 Проверить все сейчас", "menu:check"), ("📋 Мои отслеживания", "menu:list")],
        [("ℹ️ Как это работает", "menu:info")],
    ])


def format_wait(months: Optional[float], raw: str) -> str:
    if months is None:
        return raw
    return "меньше 0.5 месяца" if months < 0.5 else f"{months:g} мес."


def safe_note() -> str:
    return (
        "\n\n⚠️ Это не подтверждение конкретного свободного дня. "
        "Бот отслеживает только официально опубликованное ориентировочное ожидание. "
        "Конкретный слот проверяется и выбирается вами вручную в официальной системе записи."
    )


@router.message(Command("start"))
async def start(message: Message) -> None:
    await message.answer(
        "👋 Визовый помощник США\n\n"
        "Отслеживает публичные данные по Казахстану, Польше и Армении. "
        "Не входит в аккаунт, не хранит пароль, не обходит CAPTCHA и не бронирует автоматически.\n\n"
        "Выберите действие:", reply_markup=main_menu()
    )


@router.callback_query(F.data == "menu:add")
async def add_begin(call: CallbackQuery) -> None:
    rows = [[(country, f"country:{country}")] for country in LOCATIONS]
    rows.append([("⬅️ Назад", "menu:home")])
    await call.message.edit_text("Выберите страну:", reply_markup=kb(rows))
    await call.answer()


@router.callback_query(F.data.startswith("country:"))
async def choose_country(call: CallbackQuery) -> None:
    country = call.data.split(":", 1)[1]
    pending[call.from_user.id] = {"country": country}
    rows = [[(city, f"city:{city}")] for city in LOCATIONS[country]]
    rows.append([("⬅️ Назад", "menu:add")])
    await call.message.edit_text(f"Страна: {country}\nВыберите город:", reply_markup=kb(rows))
    await call.answer()


@router.callback_query(F.data.startswith("city:"))
async def choose_city(call: CallbackQuery) -> None:
    city = call.data.split(":", 1)[1]
    pending.setdefault(call.from_user.id, {})["city"] = city
    rows = [[(label, f"visa:{code}")] for code, label in VISA_TYPES.items()]
    rows.append([("⬅️ Назад", "menu:add")])
    await call.message.edit_text(f"Город: {city}\nВыберите тип визы:", reply_markup=kb(rows))
    await call.answer()


@router.callback_query(F.data.startswith("visa:"))
async def choose_visa(call: CallbackQuery) -> None:
    visa = call.data.split(":", 1)[1]
    data = pending.setdefault(call.from_user.id, {})
    data["visa"] = visa
    rows = [[(f"≤ {value} мес.", f"target:{value}") for value in (0.5, 1, 2)],
            [("≤ 3 мес.", "target:3"), ("≤ 6 мес.", "target:6")],
            [("⬅️ Назад", "menu:add")]]
    await call.message.edit_text(
        f"{data.get('city')} — {VISA_TYPES[visa]}\n"
        "При каком ожидании прислать уведомление?",
        reply_markup=kb(rows),
    )
    await call.answer()


@router.callback_query(F.data.startswith("target:"))
async def save_subscription(call: CallbackQuery) -> None:
    target = float(call.data.split(":", 1)[1])
    data = pending.get(call.from_user.id, {})
    city, visa = data.get("city"), data.get("visa")
    if not city or not visa:
        await call.answer("Начните выбор заново", show_alert=True)
        return
    assert db is not None
    await db.add(call.from_user.id, city, visa, target)
    await call.message.edit_text(
        f"✅ Отслеживание добавлено\n\n📍 {city}\n🎫 {VISA_TYPES[visa]}\n"
        f"🔔 Порог: ≤ {target:g} мес.{safe_note()}", reply_markup=main_menu()
    )
    pending.pop(call.from_user.id, None)
    await call.answer()


async def status_lines(user_id: int) -> str:
    assert db is not None
    subs = await db.list_for_user(user_id)
    if not subs:
        return "У вас пока нет отслеживаний."
    data = await fetch_wait_times()
    lines = ["📊 Текущие официальные показатели:\n"]
    for i, sub in enumerate(subs, 1):
        try:
            wait = get_wait_time(data, sub.city, sub.visa_type)
            value = format_wait(wait.months, wait.raw_value)
        except Exception:
            value = "данные временно недоступны"
        lines.append(f"{i}. {sub.city} — {VISA_TYPES[sub.visa_type]}\n   Сейчас: {value}; уведомление: ≤ {sub.target_months:g} мес.")
    return "\n\n".join(lines) + safe_note()


@router.callback_query(F.data == "menu:check")
async def check_now(call: CallbackQuery) -> None:
    try:
        text = await status_lines(call.from_user.id)
    except Exception as exc:
        logger.exception("check failed")
        text = f"Не удалось получить официальные данные: {exc}"
    await call.message.edit_text(text, reply_markup=main_menu(), disable_web_page_preview=True)
    await call.answer()


async def render_subscriptions(call: CallbackQuery) -> None:
    assert db is not None
    subs = await db.list_for_user(call.from_user.id)
    if not subs:
        await call.message.edit_text("У вас пока нет отслеживаний.", reply_markup=main_menu())
    else:
        rows = [[(f"🗑 {s.city} — {s.visa_type}", f"del:{s.city}:{s.visa_type}")] for s in subs]
        rows.append([("⬅️ Назад", "menu:home")])
        await call.message.edit_text("Ваши отслеживания. Нажмите на пункт, чтобы удалить:", reply_markup=kb(rows))


@router.callback_query(F.data == "menu:list")
async def list_subs(call: CallbackQuery) -> None:
    await render_subscriptions(call)
    await call.answer()


@router.callback_query(F.data.startswith("del:"))
async def delete_sub(call: CallbackQuery) -> None:
    _, city, visa = call.data.split(":", 2)
    assert db is not None
    await db.remove(call.from_user.id, city, visa)
    await render_subscriptions(call)
    await call.answer("Удалено")


@router.callback_query(F.data == "menu:info")
async def info(call: CallbackQuery) -> None:
    await call.message.edit_text(
        "ℹ️ Бот читает публичную таблицу Global Visa Wait Times Госдепартамента США. "
        "Она показывает ориентировочный срок до следующей записи, а не конкретный календарный слот.\n\n"
        "Когда показатель уменьшается или достигает вашего порога, бот присылает сигнал. "
        "После этого вы самостоятельно входите в официальный кабинет и проверяете календарь.\n\n"
        f"Источник: {WAIT_TIMES_URL}{safe_note()}",
        reply_markup=main_menu(), disable_web_page_preview=True,
    )
    await call.answer()


@router.callback_query(F.data == "menu:home")
async def home(call: CallbackQuery) -> None:
    await call.message.edit_text("Главное меню:", reply_markup=main_menu())
    await call.answer()


@router.message(F.text)
async def fallback(message: Message) -> None:
    await message.answer("Используйте кнопки меню или команду /start.", reply_markup=main_menu())


async def scheduled_check() -> None:
    if bot is None or db is None:
        return
    try:
        data = await fetch_wait_times()
        subs = await db.all_enabled()
    except Exception:
        logger.exception("scheduled fetch failed")
        return

    for sub in subs:
        try:
            wait = get_wait_time(data, sub.city, sub.visa_type)
            months = wait.months
            if months is None:
                await db.update_seen(sub, None)
                continue
            improved = sub.last_seen_months is not None and months < sub.last_seen_months
            reached = months <= sub.target_months
            duplicate = sub.last_alert_months is not None and months == sub.last_alert_months
            should_alert = (improved or reached) and not duplicate
            if should_alert:
                reason = "показатель достиг вашего порога" if reached else "официальное ожидание уменьшилось"
                await bot.send_message(
                    sub.telegram_id,
                    f"🔔 {reason}!\n\n📍 {wait.country}, {wait.city}\n🎫 {wait.label}\n"
                    f"Сейчас: {format_wait(months, wait.raw_value)}\nВаш порог: ≤ {sub.target_months:g} мес.\n\n"
                    "Зайдите в официальный визовый кабинет и вручную проверьте календарь."
                    f"{safe_note()}\n\nИсточник: {WAIT_TIMES_URL}",
                    disable_web_page_preview=True,
                )
            await db.update_seen(sub, months, alerted=should_alert)
        except Exception:
            logger.exception("subscription check failed: %s", sub)


async def main() -> None:
    global db, bot
    settings = load_settings()
    db = Database(settings.db_path)
    await db.init()
    bot = Bot(settings.bot_token)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    scheduler = AsyncIOScheduler()
    scheduler.add_job(scheduled_check, "interval", minutes=settings.check_interval_minutes, max_instances=1)
    scheduler.start()
    await scheduled_check()
    try:
        await dispatcher.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

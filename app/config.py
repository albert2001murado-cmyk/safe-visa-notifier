from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    bot_token: str
    db_path: str = "visa_bot.sqlite3"
    check_interval_minutes: int = 360


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN не задан. Создайте .env по примеру .env.example")

    interval_raw = os.getenv("CHECK_INTERVAL_MINUTES", "360").strip()
    try:
        interval = max(60, int(interval_raw))
    except ValueError:
        interval = 360

    return Settings(
        bot_token=token,
        db_path=os.getenv("DB_PATH", "visa_bot.sqlite3"),
        check_interval_minutes=interval,
    )

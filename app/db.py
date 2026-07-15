from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import aiosqlite


@dataclass
class Subscription:
    telegram_id: int
    city: str
    visa_type: str
    target_months: float
    enabled: bool
    last_seen_months: Optional[float]
    last_alert_months: Optional[float]


class Database:
    def __init__(self, path: str):
        self.path = path

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    telegram_id INTEGER NOT NULL,
                    city TEXT NOT NULL,
                    visa_type TEXT NOT NULL,
                    target_months REAL NOT NULL DEFAULT 1.0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_seen_months REAL,
                    last_alert_months REAL,
                    PRIMARY KEY (telegram_id, city, visa_type)
                )
            """)
            await db.commit()

    async def add(self, telegram_id: int, city: str, visa_type: str, target: float = 1.0) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO subscriptions (telegram_id, city, visa_type, target_months, enabled)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(telegram_id, city, visa_type)
                DO UPDATE SET enabled = 1
            """, (telegram_id, city, visa_type, target))
            await db.commit()

    async def remove(self, telegram_id: int, city: str, visa_type: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "DELETE FROM subscriptions WHERE telegram_id=? AND city=? AND visa_type=?",
                (telegram_id, city, visa_type),
            )
            await db.commit()

    async def set_target(self, telegram_id: int, city: str, visa_type: str, target: float) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                UPDATE subscriptions SET target_months=?
                WHERE telegram_id=? AND city=? AND visa_type=?
            """, (target, telegram_id, city, visa_type))
            await db.commit()

    async def list_for_user(self, telegram_id: int) -> list[Subscription]:
        return await self._query("SELECT * FROM subscriptions WHERE telegram_id=? ORDER BY city, visa_type", (telegram_id,))

    async def all_enabled(self) -> list[Subscription]:
        return await self._query("SELECT * FROM subscriptions WHERE enabled=1", ())

    async def update_seen(self, sub: Subscription, months: Optional[float], alerted: bool = False) -> None:
        async with aiosqlite.connect(self.path) as db:
            if alerted:
                await db.execute("""
                    UPDATE subscriptions SET last_seen_months=?, last_alert_months=?
                    WHERE telegram_id=? AND city=? AND visa_type=?
                """, (months, months, sub.telegram_id, sub.city, sub.visa_type))
            else:
                await db.execute("""
                    UPDATE subscriptions SET last_seen_months=?
                    WHERE telegram_id=? AND city=? AND visa_type=?
                """, (months, sub.telegram_id, sub.city, sub.visa_type))
            await db.commit()

    async def _query(self, sql: str, params: tuple) -> list[Subscription]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(sql, params)
            rows = await cur.fetchall()
            return [Subscription(
                telegram_id=row["telegram_id"], city=row["city"], visa_type=row["visa_type"],
                target_months=float(row["target_months"]), enabled=bool(row["enabled"]),
                last_seen_months=None if row["last_seen_months"] is None else float(row["last_seen_months"]),
                last_alert_months=None if row["last_alert_months"] is None else float(row["last_alert_months"]),
            ) for row in rows]

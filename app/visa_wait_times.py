from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional

import aiohttp
from bs4 import BeautifulSoup

WAIT_TIMES_URL = "https://travel.state.gov/content/travel/en/us-visas/visa-information-resources/global-visa-wait-times.html"

LOCATIONS = {
    "Kazakhstan": ["Almaty", "Astana"],
    "Poland": ["Warsaw", "Krakow"],
    "Armenia": ["Yerevan"],
}
SUPPORTED_CITIES = {city for cities in LOCATIONS.values() for city in cities}
CITY_COUNTRY = {city: country for country, cities in LOCATIONS.items() for city in cities}

VISA_TYPES = {
    "B1B2": "Туризм / бизнес B1/B2",
    "FMJ": "Учёба / обмен F, M, J",
    "PETITION": "Рабочие H, L, O, P, Q",
    "CREW": "Экипаж / транзит C, D, C1/D",
}


@dataclass(frozen=True)
class WaitTime:
    city: str
    country: str
    visa_type: str
    label: str
    raw_value: str
    months: Optional[float]
    source_url: str = WAIT_TIMES_URL


def parse_months(value: str) -> Optional[float]:
    text = " ".join(value.replace("\xa0", " ").split())
    if not text or text.upper() in {"NA", "N/A"}:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    return float(match.group(1)) if match else None


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def _make_city(city: str, values: dict[str, str]) -> dict[str, WaitTime]:
    return {
        visa_type: WaitTime(
            city=city,
            country=CITY_COUNTRY[city],
            visa_type=visa_type,
            label=VISA_TYPES[visa_type],
            raw_value=raw,
            months=parse_months(raw),
        )
        for visa_type, raw in values.items()
    }


def _parse_table_rows(html: str) -> Dict[str, Dict[str, WaitTime]]:
    soup = BeautifulSoup(html, "lxml")
    result: Dict[str, Dict[str, WaitTime]] = {}
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [_clean(cell.get_text(" ")) for cell in tr.find_all(["td", "th"])]
            if len(cells) < 6 or cells[0] not in SUPPORTED_CITIES:
                continue
            city = cells[0]
            result[city] = _make_city(city, {
                "B1B2": cells[2],
                "FMJ": cells[3],
                "PETITION": cells[4],
                "CREW": cells[5],
            })
    return result


def _parse_text_fallback(html: str) -> Dict[str, Dict[str, WaitTime]]:
    text = BeautifulSoup(html, "lxml").get_text("\n")
    result: Dict[str, Dict[str, WaitTime]] = {}
    token_re = r"NA|N/A|<\s*0\.5\s*Month|\d+(?:\.\d+)?\s*Months?"
    for city in SUPPORTED_CITIES:
        for line in text.splitlines():
            line = _clean(line)
            if not line.startswith(city + " "):
                continue
            values = re.findall(token_re, line[len(city):], flags=re.I)
            if len(values) >= 5:
                result[city] = _make_city(city, {
                    "B1B2": values[1],
                    "FMJ": values[2],
                    "PETITION": values[3],
                    "CREW": values[4],
                })
                break
    return result


async def fetch_wait_times() -> Dict[str, Dict[str, WaitTime]]:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; SafeVisaNotifier/2.0; public-data-only)",
        "Accept": "text/html,application/xhtml+xml",
    }
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        async with session.get(WAIT_TIMES_URL) as response:
            response.raise_for_status()
            html = await response.text()
    parsed = _parse_table_rows(html) or _parse_text_fallback(html)
    if not parsed:
        raise RuntimeError("Не удалось распознать официальную таблицу ожиданий.")
    return parsed


def get_wait_time(data: Dict[str, Dict[str, WaitTime]], city: str, visa_type: str) -> WaitTime:
    try:
        return data[city][visa_type]
    except KeyError as exc:
        raise KeyError(f"Нет данных для {city}, {visa_type}") from exc

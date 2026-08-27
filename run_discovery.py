"""
Production discovery-скрипт для автоматического запуска через GitHub Actions.

Делает всё за один проход:
1. Генерирует полную матрицу запросов (оба сегмента)
2. Прогоняет каждый через SerpAPI
3. Сохраняет находки в Supabase с дедупом по URL

Настройки (SERPAPI_KEY, DATABASE_URL) берутся из переменных окружения —
в GitHub Actions они подставляются автоматически из GitHub Secrets,
нигде не хранятся в самом коде.
"""

import os
import time
from itertools import product

import psycopg2
from serpapi import GoogleSearch

SERPAPI_KEY = os.environ["SERPAPI_KEY"]
DATABASE_URL = os.environ["DATABASE_URL"]

# --- Матрица запросов (ниша: ставки на спорт, англоязычный рынок) ---

base_topics = [
    "sports betting",
    "betting tips",
    "sports predictions",
    "tipster",
    "handicapper",
    "arbitrage betting",
    "sure betting",
    "live betting",
]

publisher_arbitrage_modifiers = {
    "telegram_channels": [
        'site:t.me "{topic}"',
        '"{topic}" telegram channel',
        '"{topic}" join channel',
    ],
    "webmasters_arbitrage": [
        '"{topic}" affiliate program',
        '"iGaming affiliate" "{topic}"',
        '"{topic}" arbitrage forum',
    ],
    "youtube_bloggers": [
        'site:youtube.com "{topic}" channel',
    ],
}

cold_outreach_modifiers = {
    "review_sites": [
        '"best {topic}" review',
        '"{topic}" ranking site',
    ],
    "niche_blogs": [
        '"{topic}" blog contact',
    ],
    "bonus_promo": [
        '"betting bonus codes"',
        '"sports betting promo codes"',
        '"no deposit bonus" sportsbook',
    ],
    "facebook_pages": [
        'site:facebook.com "{topic}"',
    ],
}


def generate_queries():
    rows = []
    for group, templates in publisher_arbitrage_modifiers.items():
        for template, topic in product(templates, base_topics):
            rows.append((template.format(topic=topic), "publisher_arbitrage"))
    for group, templates in cold_outreach_modifiers.items():
        for template in templates:
            if "{topic}" in template:
                for topic in base_topics:
                    rows.append((template.format(topic=topic), "cold_outreach_site"))
            else:
                rows.append((template, "cold_outreach_site"))
    return rows


def classify_source_type(url: str) -> str:
    if "t.me" in url:
        return "telegram_channel"
    if "facebook.com" in url:
        return "facebook_page"
    return "website"


def run_query(query_text: str, num_results: int = 10):
    params = {
        "engine": "google",
        "q": query_text,
        "num": num_results,
        "api_key": SERPAPI_KEY,
        "hl": "en",
    }
    search = GoogleSearch(params)
    results = search.get_dict()
    return results.get("organic_results", [])


def main():
    queries = generate_queries()
    print(f"Всего запросов в матрице: {len(queries)}")

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    total_saved = 0

    for i, (query_text, segment) in enumerate(queries, 1):
        print(f"[{i}/{len(queries)}] ({segment}) {query_text}")
        try:
            results = run_query(query_text)
        except Exception as e:
            print(f"  ошибка запроса: {e}")
            continue

        for r in results:
            url = r.get("link")
            if not url:
                continue
            title = r.get("title", "")
            description = r.get("snippet", "")
            source_type = classify_source_type(url)

            cur.execute(
                """
                INSERT INTO sources (url, source_type, title, description, found_via_query, segment)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (url) DO NOTHING
                """,
                (url, source_type, title, description, query_text, segment),
            )
            total_saved += cur.rowcount

        conn.commit()
        time.sleep(1.5)  # уважаем rate limit SerpAPI

    cur.close()
    conn.close()
    print(f"\nГотово! Новых записей добавлено в базу: {total_saved}")


if __name__ == "__main__":
    main()

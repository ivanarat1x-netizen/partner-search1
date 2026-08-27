"""
Production contact-scraper для автоматического запуска через GitHub Actions.

Проходит по сайтам сегмента cold_outreach_site (тип website), которые ещё
не имеют сохранённого email, заходит на главную и типовые страницы контактов,
извлекает email и сохраняет в таблицу contacts.

Настройки (DATABASE_URL) берутся из переменных окружения — в GitHub Actions
подставляются автоматически из GitHub Secrets.
"""

import os
import re
import time
from urllib.parse import urljoin, urlparse

import psycopg2
import requests
from bs4 import BeautifulSoup

DATABASE_URL = os.environ["DATABASE_URL"]

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
CONTACT_PATHS = ["/contact", "/contacts", "/about", "/about-us"]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PartnerSearchBot/1.0)"}
REQUEST_TIMEOUT = 10
MAX_SITES_PER_RUN = 150  # ограничение, чтобы один прогон не растягивался на часы


def extract_emails_from_html(html: str) -> set:
    soup = BeautifulSoup(html, "html.parser")
    emails = set()

    for a in soup.find_all("a", href=True):
        if a["href"].startswith("mailto:"):
            emails.add(a["href"].replace("mailto:", "").split("?")[0].strip())

    emails.update(EMAIL_RE.findall(soup.get_text()))

    return {
        e for e in emails
        if not e.lower().endswith((".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif"))
        and len(e) < 100
    }


def fetch(url: str):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            return resp.text
    except requests.RequestException:
        return None
    return None


def find_contacts_for_site(base_url: str) -> set:
    emails = set()

    html = fetch(base_url)
    if html:
        emails.update(extract_emails_from_html(html))

    if emails:
        return emails  # нашли на главной — дальше не идём, экономим время

    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"

    for path in CONTACT_PATHS:
        html = fetch(urljoin(root, path))
        if html:
            emails.update(extract_emails_from_html(html))
        if emails:
            break
        time.sleep(0.3)

    return emails


def main():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Берём сайты cold_outreach_site, у которых ещё нет ни одного сохранённого email
    cur.execute(
        """
        SELECT s.id, s.url
        FROM sources s
        WHERE s.segment = 'cold_outreach_site'
          AND s.source_type = 'website'
          AND NOT EXISTS (
              SELECT 1 FROM contacts c
              WHERE c.source_id = s.id AND c.contact_type = 'email'
          )
        ORDER BY s.found_at DESC
        LIMIT %s
        """,
        (MAX_SITES_PER_RUN,),
    )
    rows = cur.fetchall()
    print(f"Сайтов к обработке в этом прогоне: {len(rows)}")

    found_total = 0

    for source_id, url in rows:
        emails = find_contacts_for_site(url)
        if emails:
            for email in emails:
                cur.execute(
                    """
                    INSERT INTO contacts (source_id, contact_type, contact_value)
                    VALUES (%s, 'email', %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (source_id, email),
                )
            found_total += len(emails)
            print(f"  {url} -> {emails}")
        else:
            print(f"  {url} -> контактов не найдено")

        conn.commit()
        time.sleep(0.5)

    cur.close()
    conn.close()
    print(f"\nГотово! Email-адресов сохранено: {found_total}")


if __name__ == "__main__":
    main()

name: Daily Contact Scraper

on:
  schedule:
    # Запуск каждый день в 07:00 UTC (10:00 по МСК) — через час после поиска источников
    - cron: "0 7 * * *"
  workflow_dispatch:
    # Кнопка ручного запуска для тестов

jobs:
  run-contacts:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run contact scraper
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
        run: python run_contacts.py

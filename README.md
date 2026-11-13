# Topic Digest Pipeline

Еженедельный дайджест по теме: RSS → фильтр по дате и ключевым словам → оценка Gemini → Markdown в `digests/YYYY-WW-<profile>.md` (для NotebookLM, Obsidian и т.п.). Спецификация: [system_specification.md](system_specification.md).

Рядом с дайджестом создаётся `digests/YYYY-WW-<profile>-links.txt` — ссылки на отобранные статьи по одной в строке (для arXiv — на PDF). Его содержимое вставляется целиком в NotebookLM: Add source → Website.

## Локальный запуск

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # Linux/macOS: .venv/bin/pip
.venv/Scripts/python src/main.py --list
.venv/Scripts/python src/main.py --profile ai-sdlc-architecture --dry-run   # без LLM: только список кандидатов
```

Полный запуск требует ключ Google AI Studio в переменной окружения `GEMINI_API_KEY`:

```bash
.venv/Scripts/python src/main.py --profile ai-sdlc-architecture
```

`--profile all` прогоняет все профили подряд.

## GitHub Actions

1. Запушить репозиторий на GitHub.
2. Settings → Secrets and variables → Actions → секрет `GEMINI_API_KEY`.
3. Workflow запускается по воскресеньям в 23:00 UTC либо вручную (Actions → Run workflow, с выбором профиля).

Необязательные repository variables: `DIGEST_PROFILE` (профиль для запуска по расписанию, например `all`) и `GEMINI_MODEL`.

## Новая тема

Добавить блок в [config/profiles.yaml](config/profiles.yaml) — код менять не нужно:

```yaml
profiles:
  history:
    description: "О чём дайджест"
    rss_sources:
      - name: "Название ленты"
        url: "https://example.com/feed"
        keyword_filter: false   # необязательно: пропускать все статьи источника мимо фильтра по ключевым словам
    keywords: ["слово", "фраза"]   # без учёта регистра, целыми словами (допускается «s» на конце); пустой список = без фильтра
    signal_threshold: 8            # минимальная оценка 1-10
    system_prompt: |
      Роль эксперта и критерии: что считать сигналом, а что шумом.
```

Общие параметры (модель, окно в днях, лимит статей, язык дайджеста, размер дайджеста `max_items` и доля одного источника `max_source_share`) — в секции `settings` того же файла.

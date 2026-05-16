# 🎯 Job Analyzer MVP

RAG-система для умного подбора вакансий под ваше резюме.
**Стек:** Python 3.12 · FastAPI · GigaChat · ChromaDB · hh.ru (парсинг) · Streamlit

---

## Архитектура пайплайна

```
Резюме (PDF/DOCX)
      │
      ▼ GigaChat LLM — извлечение профиля
  [навыки, позиция, summary]
      │
      ├──→ Поисковые запросы ──→ hh.ru API ──→ Вакансии
      │                                             │
      │                                    GigaChat Embeddings
      │                                             │
      │                                         ChromaDB
      │                                             │
      └──→ Семантический поиск (Top-30) ───────────┘
                                          │
                                 GigaChat LLM scoring
                                          │
                                 Финальный ранг (Top-N)
                                          │
                                 Streamlit Dashboard
```

---

## Быстрый старт

### 1. Клонировать и настроить

```bash
git clone <repo>
cd job_analyzer
```

### 2. Получить GigaChat API key

1. Зайти на https://developers.sber.ru/gigachat
2. Создать проект → получить API key
3. Сохранить в файл:
   ```bash
   mkdir -p ~/secrets
   echo -n "ВАШ_API_KEY" > ~/secrets/gigachat_api_key.txt
   ```

### 3. Запуск

```bash
docker compose up --build
```

- **UI:** http://localhost:8501
- **API docs:** http://localhost:8000/docs

### 4. Использование

1. **Резюме** — загрузить PDF или DOCX
2. **Предпочтения** — город, формат работы, зарплата, ключевые слова
3. **Анализ** — нажать «Запустить», ждать 2-5 минут
4. **Результаты** — ранжированные вакансии, фильтры, экспорт CSV

---

## Структура проекта

```
job_analyzer/
├── app/
│   ├── core/
│   │   ├── config.py          # pydantic-settings
│   │   └── pipeline.py        # Главный пайплайн
│   ├── models/schemas.py      # Pydantic-модели
│   ├── services/
│   │   ├── resume_parser.py   # PDF/DOCX → профиль (GigaChat)
│   │   ├── hh_fetcher.py      # hh.ru API
│   │   ├── vector_store.py    # ChromaDB + embeddings
│   │   ├── scorer.py          # LLM-ранжирование
│   │   └── state_manager.py   # JSON-стейт
│   └── main.py                # FastAPI
├── streamlit_app/
│   ├── main.py                # Точка входа
│   ├── sidebar.py
│   ├── page_resume.py
│   ├── page_preferences.py
│   ├── page_analyze.py
│   └── page_results.py        # Дашборд с графиками
├── scheduler/
│   └── daily_job.py           # APScheduler — ежедневный запуск
├── tests/test_core.py
├── docker-compose.yml
├── Dockerfile.api
├── Dockerfile.streamlit
├── requirements.txt
└── .env.example
```

---

## Переменные окружения

| Переменная | Обязательная | По умолчанию | Описание |
|---|---|---|---|
| `GIGACHAT_API_KEY` | ✅* | — | Base64 ключ GigaChat (или через secrets) |
| `GIGACHAT_API_KEY_FILE` | ✅* | — | Путь к файлу с ключом (Docker secrets) |
| `GIGACHAT_SCOPE` | — | `GIGACHAT_API_PERS` | Для физлиц / юрлиц |
| `GIGACHAT_MODEL` | — | `GigaChat-Pro` | Модель GigaChat |
| `DAILY_REPORT_HOUR` | — | `9` | Час ежедневного запуска (UTC) |
| `DAILY_REPORT_MINUTE` | — | `0` | Минута запуска |
| `CHROMA_DB_PATH` | — | `/app/data/chroma_db` | Путь к ChromaDB |
| `RESUMES_PATH` | — | `/app/data/resumes` | Путь к резюме и стейту |

*\* Достаточно одного из `GIGACHAT_API_KEY` или `GIGACHAT_API_KEY_FILE`*

---

## Команды

```bash
# Запуск
docker compose up --build

# Логи
docker compose logs -f api
docker compose logs -f scheduler

# Тесты (локально)
pip install -r requirements.txt
pytest tests/ -v

# Очистить базу вакансий
curl -X DELETE http://localhost:8000/data/clear
```

## Ограничения MVP / Roadmap

**Сейчас:** одно резюме, JSON-стейт, парсинг hh.ru, последовательная LLM-оценка.

**Следующий шаг:**
- [ ] PostgreSQL вместо JSON-стейта
- [ ] Параллельная async LLM-оценка
- [ ] SuperJob / LinkedIn как дополнительные источники
- [ ] Telegram-бот для уведомлений

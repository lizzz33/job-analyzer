# Job Analyzer MVP

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
      ├──→ Поисковые запросы ──→ hh.ru (HTML) ──→ Вакансии
      │                                           │
      │                                  GigaChat Embeddings
      │                                           │
      │                                       ChromaDB
      │                                           │
      └──→ Семантический поиск (Top-30) ─────────┘
                                      │
                             GigaChat LLM scoring
                             (последовательный — API однопоточный)
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

### 3. SSL-сертификат (production)

GigaChat API (`ngw.devices.sberbank.ru:9443`) использует сертификат Минцифры.
Для production нужен CA-сертификат:

```bash
# Конвертировать .p7b → .pem
openssl pkcs7 -inform DER -in russiantrustedca.p7b -print_certs -out gigachat_ca.pem
cp gigachat_ca.pem ~/secrets/gigachat_ca.pem
```

Для dev без сертификата — не устанавливайте `GIGACHAT_SSL_REQUIRED` (SSL будет отключен с warning).

### 4. Запуск

```bash
docker compose up --build
```

- **UI:** http://localhost:8501
- **API docs:** http://localhost:8000/docs

### 5. Использование

1. **Резюме** — загрузить PDF или DOCX
2. **Предпочтения** — город, формат работы, зарплата, ключевые слова
3. **Анализ** — нажать «Запустить»
4. **Результаты** — ранжированные вакансии, фильтры, экспорт CSV

---

## Структура проекта

```
job_analyzer/
├── app/
│   ├── core/
│   │   ├── config.py          # pydantic-settings
│   │   ├── deps.py            # DI-фабрики (@lru_cache singletons)
│   │   ├── gigachat_auth.py   # Token provider + SSL setup
│   │   ├── llm.py             # GigaChat LLM factory (shared)
│   │   └── pipeline.py        # Главный пайплайн
│   ├── models/schemas.py      # Pydantic-модели
│   ├── services/
│   │   ├── resume_parser.py   # PDF/DOCX → профиль (GigaChat)
│   │   ├── hh_fetcher.py      # hh.ru HTML-парсинг
│   │   ├── vector_store.py    # ChromaDB + embeddings
│   │   ├── scorer.py          # LLM-ранжирование
│   │   └── state_manager.py   # JSON-стейт (отдельные файлы + filelock)
│   └── main.py                # FastAPI
├── streamlit_app/
│   ├── main.py                # Точка входа
│   ├── config.py              # API URL
│   ├── sidebar.py
│   ├── page_resume.py
│   ├── page_preferences.py
│   ├── page_analyze.py
│   └── page_results.py        # Дашборд + пагинация + графики
├── scheduler/
│   └── daily_job.py           # APScheduler — ежедневный запуск
├── tests/                     # 111 тестов
├── docker-compose.yml
├── Dockerfile.api
├── Dockerfile.streamlit
├── requirements-streamlit.txt
└── pyproject.toml
```

---

## Переменные окружения

| Переменная | Обязательная | По умолчанию | Описание |
|---|---|---|---|
| `GIGACHAT_API_KEY` | ✅* | — | Base64 ключ GigaChat API |
| `GIGACHAT_API_KEY_FILE` | ✅* | — | Путь к файлу с ключом |
| `GIGACHAT_SCOPE` | — | `GIGACHAT_API_PERS` | Для физлиц / юрлиц |
| `GIGACHAT_MODEL` | — | `GigaChat-Pro` | Модель GigaChat |
| `GIGACHAT_CA_CERT_PATH` | — | — | Путь к CA-сертификату (PEM) |
| `GIGACHAT_SSL_REQUIRED` | — | — | `1` = ошибка без сертификата |
| `API_KEY` | — | — | API-key для аутентификации эндпоинтов |
| `CORS_ORIGINS` | — | `http://localhost:8501` | Разрешённые CORS origins (через запятую) |
| `API_BASE_URL` | — | `http://api:8000` | URL API-сервиса |
| `SCHEDULER_ENABLED` | — | `false` | Встроенный scheduler в API-контейнере |
| `DAILY_REPORT_HOUR` | — | `9` | Час ежедневного запуска (UTC) |
| `DAILY_REPORT_MINUTE` | — | `0` | Минута запуска |
| `CHROMA_DB_PATH` | — | `/app/data/chroma_db` | Путь к ChromaDB |
| `RESUMES_PATH` | — | `/app/data/resumes` | Путь к резюме и стейту |

---

## Команды

```bash
# Запуск
docker compose up --build

# Логи
docker compose logs -f api
docker compose logs -f scheduler

# Тесты (локально)
pip install -e ".[dev]"
pytest tests/ -v

# Очистить базу вакансий (если API_KEY задан — передать в заголовке)
curl -X DELETE http://localhost:8000/data/clear -H "X-API-Key: YOUR_KEY"
```

## Ограничения MVP / Roadmap

**Сейчас:** одно резюме, JSON-стейт (отдельные файлы + filelock), DI через `@lru_cache`, парсинг hh.ru, последовательная LLM-оценка (GigaChat API однопоточный), пагинация в UI.

**Следующий шаг:**
- [ ] PostgreSQL вместо JSON-стейта
- [ ] SuperJob / LinkedIn как дополнительные источники
- [ ] Telegram-бот для уведомлений

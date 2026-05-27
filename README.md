# Job Analyzer MVP

RAG-система для умного подбора вакансий под ваше резюме.
**Стек:** Python 3.12 · FastAPI · GigaChat-2 · ChromaDB · deepvk/USER-bge-m3 (embeddings) · hh.ru (парсинг) · Streamlit

---

## Архитектура пайплайна

```
Резюме (PDF/DOCX/TXT)
      │
      ▼ GigaChat LLM — извлечение профиля
  [навыки, позиция, опыт, summary]
      │
      ├──→ Поисковые запросы (роль + навыки) ──→ hh.ru (параллельно) ──→ Вакансии
      │                                                    │
      │                                          deepvk/USER-bge-m3
      │                                          (локальные embeddings)
      │                                                    │
      │                                               ChromaDB
      │                                                    │
      ├──→ Семантический поиск (Top-30, logistic calibration) ─────┘
      │         │
      │    Фильтр по грейду (seniority)
      │         │
      └──→ LLM-скоринг (GigaChat-2, последовательный)
               │
          Фильтр по релевантности (≥ 40%)
               │
          Корректировка по фидбеку (± like/dislike)
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

### 2. Получить API-ключи

**GigaChat:**

1. Зайти на https://developers.sber.ru/gigachat
2. Создать проект → получить API key
3. Сохранить в файл:
   ```bash
   mkdir -p ~/secrets
   echo -n "ВАШ_API_KEY" > ~/secrets/gigachat_api_key.txt
   ```

**HuggingFace** (для модели embeddings `deepvk/USER-bge-m3`):

```bash
echo -n "ВАШ_HF_TOKEN" > ~/secrets/hf_token.txt
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

1. **Резюме** — загрузить PDF, DOCX или TXT
2. **Предпочтения** — город, формат работы, зарплата, ключевые слова
3. **Анализ** — нажать «Запустить»
4. **Результаты** — ранжированные вакансии, фидбек (like/dislike), фильтры, экспорт CSV

---

## Структура проекта

```
job_analyzer/
├── app/
│   ├── core/
│   │   ├── config.py            # pydantic-settings
│   │   ├── deps.py              # DI-фабрики (@lru_cache singletons)
│   │   ├── gigachat_auth.py     # Token provider + SSL setup
│   │   ├── llm.py               # GigaChat LLM factory (shared)
│   │   └── pipeline.py          # Главный пайплайн
│   ├── models/schemas.py        # Pydantic-модели
│   ├── services/
│   │   ├── resume_parser.py     # PDF/DOCX/TXT → профиль (GigaChat)
│   │   ├── hh_fetcher.py        # hh.ru HTML-парсинг
│   │   ├── vector_store.py      # ChromaDB + локальные embeddings
│   │   ├── scorer.py            # LLM-ранжирование (GigaChat-2)
│   │   ├── seniority.py         # Определение грейда (junior–lead)
│   │   ├── score_cache.py       # Кэш LLM-оценок по content-hash
│   │   ├── feedback_store.py    # Хранение like/dislike по компаниям
│   │   └── state_manager.py     # JSON-стейт (отдельные файлы + filelock)
│   └── main.py                  # FastAPI
├── streamlit_app/
│   ├── main.py                  # Точка входа
│   ├── config.py                # API URL
│   ├── sidebar.py
│   ├── page_resume.py
│   ├── page_preferences.py
│   ├── page_analyze.py
│   └── page_results.py          # Дашборд + фидбек + пагинация + графики
├── scheduler/
│   └── daily_job.py             # APScheduler — ежедневный запуск
├── tests/                       # 13 файлов тестов
├── docker-compose.yml           # 3 сервиса: api, streamlit, scheduler
├── Dockerfile.api
├── Dockerfile.streamlit
└── pyproject.toml
```

---

## API-эндпоинты

| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/resume/upload` | Загрузить резюме (PDF/DOCX/TXT) |
| `GET` | `/resume/profile` | Получить профиль из резюме |
| `DELETE` | `/resume/profile` | Удалить профиль и файл резюме |
| `POST` | `/preferences` | Сохранить предпочтения |
| `GET` | `/preferences` | Получить текущие предпочтения |
| `POST` | `/analysis/run` | Запустить анализ (background) |
| `GET` | `/analysis/status` | Статус выполнения анализа |
| `GET` | `/analysis/report` | Получить последний отчёт |
| `GET` | `/vacancies/search-by-skills` | Поиск вакансий по навыкам (semantic) |
| `GET` | `/stats` | Статистика (вакансий в БД, наличие резюме/настроек) |
| `DELETE` | `/data/clear` | Очистить базу вакансий |
| `POST` | `/feedback` | Оставить фидбек (like/dislike) |
| `DELETE` | `/feedback/{id}` | Удалить фидбек |
| `GET` | `/feedback` | Список всех фидбеков |
| `GET` | `/health` | Health check |

---

## Переменные окружения

| Переменная | Обязательная | По умолчанию | Описание |
|---|---|---|---|
| `GIGACHAT_API_KEY` | ✅* | — | Base64 ключ GigaChat API |
| `GIGACHAT_API_KEY_FILE` | ✅* | — | Путь к файлу с ключом |
| `GIGACHAT_SCOPE` | — | `GIGACHAT_API_PERS` | Для физлиц / юрлиц |
| `GIGACHAT_MODEL` | — | `GigaChat-2` | Модель GigaChat |
| `GIGACHAT_CA_CERT_PATH` | — | — | Путь к CA-сертификату (PEM) |
| `GIGACHAT_SSL_REQUIRED` | — | — | `1` = ошибка без сертификата |
| `HF_TOKEN` / `HF_TOKEN_FILE` | ✅ | — | HuggingFace токен для embeddings |
| `API_KEY` | — | — | API-key для аутентификации эндпоинтов |
| `CORS_ORIGINS` | — | `http://localhost:8501` | Разрешённые CORS origins (через запятую) |
| `API_BASE_URL` | — | `http://api:8000` | URL API-сервиса |
| `SCHEDULER_ENABLED` | — | `false` | Встроенный scheduler в API-контейнере |
| `DAILY_REPORT_HOUR` | — | `9` | Час ежедневного запуска (UTC) |
| `DAILY_REPORT_MINUTE` | — | `0` | Минута запуска |
| `CHROMA_DB_PATH` | — | `/app/data/chroma_db` | Путь к ChromaDB |
| `RESUMES_PATH` | — | `/app/data/resumes` | Путь к резюме и стейту |

\* — достаточно одного из `GIGACHAT_API_KEY` или `GIGACHAT_API_KEY_FILE`

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

---

## Ключевые механизмы

**Скоринг** — двухуровневый с итоговым score = 0.4 × semantic + 0.6 × llm:

1. **Семантическая близость** — cosine-расстояние между embedding'ом профиля и вакансии (deepvk/USER-bge-m3). Сырые расстояния преобразуются в абсолютный score через логистическую калибровку (сигмоида, параметры подобраны по pairwise-распределению всех вакансий в БД). Не зависит от состава батча.

2. **LLM-оценка (GigaChat-2)** — промпт-рекрутер получает профиль кандидата, пожелания и текст вакансии (до 1500 символов). LLM возвращает JSON `{score, reason}`. Правила внутри промпта: за каждый недостающий обязательный навык −0.3, несовпадение уровня −0.2, города −0.3, ЗП −0.3; приоритетная компания +0.1. Оценки кэшируются по content-hash (vacancy text + position) — повторные запуски не вызывают LLM.

3. **Фильтрация** — вакансии с итоговым score < 0.4 отбрасываются. Disliked вакансии исключаются полностью. Оставшиеся корректируются по фидбеку на уровне компаний: liked +5%, disliked −10%.

**Грейд** — определение уровня кандидата по опыту (junior/middle/senior/lead) и фильтрация вакансий с несовместимым грейдом.

**Фидбек** — like/dislike по компаниям корректирует итоговый скоринг: liked +5%, disliked −10%.

**Кэширование** — LLM-оценки кэшируются по content-hash (vacancy + position), повторные запуски не вызывают API. Embeddings кэшируются на диск (`embedding_cache.json`) — при повторном добавлении вакансии embedding берётся из кэша без повторного вычисления.

**Инкрементальный парсинг** — при неизменных параметрах поиска hh.ru запрашиваются только новые вакансии.

---

## Ограничения MVP / Roadmap

**Сейчас:** одно резюме, JSON-стейт (отдельные файлы + filelock), DI через `@lru_cache`, парсинг hh.ru, локальные embeddings (deepvk/USER-bge-m3), последовательная LLM-оценка, фидбек по компаниям, кэш оценок.

**Следующий шаг:**
- [ ] PostgreSQL вместо JSON-стейта
- [ ] SuperJob / LinkedIn как дополнительные источники
- [ ] Telegram-бот для уведомлений
- [ ] Авторизация пользователей (множественные резюме)
- [ ] Отслеживание вакансий во времени — уведомления о новых за день/неделю
- [ ] Сравнение вакансий side-by-side
- [ ] История анализов — трекинг как менялся рынок и скоринг
- [ ] Tailored cover letter — генерация сопроводительного письма под вакансию
- [ ] Подготовка к собеседованию — вопросы по вакансии на основе профиля
- [ ] Валидация резюме — рекомендации по улучшению (недостающие навыки, формулировки)
- [ ] CI/CD pipeline — автотесты + деплой через GitHub Actions
- [ ] Observability — логирование, метрики, алерты при падении пайплайна

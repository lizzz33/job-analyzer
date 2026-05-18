"""Страница результатов — основной дашборд"""

from datetime import datetime
import html

import httpx
import pandas as pd
import plotly.express as px
import streamlit as st

from streamlit_app.config import API

PAGE_SIZE = 10


def _load_report() -> tuple[list[dict], str | None]:
    """Load report from API. Returns (vacancies, error_message)."""
    try:
        r = httpx.get(f"{API}/analysis/report", timeout=10)
        if r.status_code == 200:
            return r.json().get("vacancies", []), None
        return [], f"Ошибка API: {r.status_code}"
    except httpx.ConnectError:
        return [], "API недоступен — проверьте, запущен ли сервер"
    except httpx.TimeoutException:
        return [], "API не ответил за 10с — попробуйте позже"
    except Exception as e:
        return [], f"Ошибка: {e}"


def _score_class(score: float) -> str:
    if score >= 0.75:
        return "score-high"
    elif score >= 0.5:
        return "score-mid"
    return "score-low"


def _salary_str(v: dict) -> str:
    vac = v.get("vacancy", {})
    lo = vac.get("salary_from")
    hi = vac.get("salary_to")
    cur = vac.get("currency", "RUR")
    if lo or hi:
        lo_s = f"{lo:,}" if lo else "?"
        hi_s = f"{hi:,}" if hi else "?"
        return f"{lo_s}–{hi_s} {cur}"
    return "не указана"


def _render_vacancy_card(i: int, sv: dict) -> None:
    v = sv["vacancy"]
    score_pct = int(sv["score"] * 100)
    s_class = _score_class(sv["score"])
    sem_pct = int(sv.get("semantic_score", 0) * 100)
    llm_pct = int(sv.get("llm_score", 0) * 100)
    salary = _salary_str(sv)
    pub_date = v.get("published_at", "")[:10] if v.get("published_at") else ""

    safe_url = html.escape(v.get("url", "#"))
    safe_title = html.escape(v.get("title", ""))
    safe_company = html.escape(v.get("company", ""))
    safe_city = html.escape(v.get("city", ""))
    safe_reason = html.escape(sv.get("match_reason", "")[:200])

    st.markdown(
        f"""
<div class="vacancy-card">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;">
    <div style="flex:1;">
      <div style="font-size:17px;font-weight:600;margin-bottom:2px;">
        {i}. <a href="{safe_url}" target="_blank"
              style="color:#c7d2fe;text-decoration:none;">{safe_title}</a>
      </div>
      <div style="color:#6b7280;font-size:14px;margin-bottom:10px;">
        🏢 {safe_company} &nbsp;·&nbsp;
        🏙️ {safe_city} &nbsp;·&nbsp;
        💰 {salary} &nbsp;·&nbsp;
        📅 {pub_date}
      </div>
    </div>
    <div style="text-align:right;min-width:80px;">
      <span class="score-badge {s_class}">{score_pct}%</span>
    </div>
  </div>
  <div style="color:#9ca3af;font-size:13px;margin-bottom:10px;line-height:1.5;">
    {safe_reason}
  </div>
  <div style="display:flex;gap:12px;font-size:12px;color:#6b7280;">
    <span>🔍 Семантика: {sem_pct}%</span>
    <span>🤖 LLM: {llm_pct}%</span>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def render():
    st.title("📊 Результаты подбора")

    vacancies, error = _load_report()

    if error:
        st.error(f"**Не удалось загрузить результаты:** {error}")
        if st.button("🔄 Повторить", type="primary"):
            st.rerun()
        return

    if not vacancies:
        st.info("Результатов пока нет. Запустите анализ на странице **🔍 Анализ**.")
        if st.button("→ Перейти к анализу", type="primary"):
            st.session_state["page"] = "analyze"
            st.rerun()
        return

    # ── Метрики ───────────────────────────────────────────────────────────────
    scores = [v["score"] for v in vacancies]
    avg_score = sum(scores) / len(scores) if scores else 0
    top_score = max(scores) if scores else 0
    high_match = sum(1 for s in scores if s >= 0.75)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(
            f"""
<div class="metric-card">
  <div class="val">{len(vacancies)}</div>
  <div class="label">Вакансий в подборке</div>
</div>""",
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f"""
<div class="metric-card">
  <div class="val">{int(top_score * 100)}%</div>
  <div class="label">Лучший матч</div>
</div>""",
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f"""
<div class="metric-card">
  <div class="val">{int(avg_score * 100)}%</div>
  <div class="label">Средний матч</div>
</div>""",
            unsafe_allow_html=True,
        )
    with col4:
        st.markdown(
            f"""
<div class="metric-card">
  <div class="val">{high_match}</div>
  <div class="label">Высокий матч (75%+)</div>
</div>""",
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Фильтры ───────────────────────────────────────────────────────────────
    with st.expander("🔧 Фильтры и сортировка"):
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            min_score = st.slider("Мин. релевантность", 0, 100, 0) / 100
        with col_f2:
            companies = list({v["vacancy"]["company"] for v in vacancies})
            sel_companies = st.multiselect("Компании", companies, default=companies)
        with col_f3:
            sort_by = st.selectbox("Сортировка", ["По релевантности", "По дате", "По зарплате"])

    filtered = [
        v for v in vacancies if v["score"] >= min_score and v["vacancy"]["company"] in sel_companies
    ]

    if sort_by == "По дате":
        filtered.sort(key=lambda x: x["vacancy"].get("published_at", ""), reverse=True)
    elif sort_by == "По зарплате":
        filtered.sort(key=lambda x: x["vacancy"].get("salary_from") or 0, reverse=True)
    else:
        filtered.sort(key=lambda x: x["score"], reverse=True)

    # ── Charts ────────────────────────────────────────────────────────────────
    if len(vacancies) > 2:
        col_ch1, col_ch2 = st.columns(2)

        with col_ch1:
            st.markdown("#### Распределение релевантности")
            df_scores = pd.DataFrame({"score": [int(v["score"] * 100) for v in vacancies]})
            fig = px.histogram(
                df_scores,
                x="score",
                nbins=10,
                color_discrete_sequence=["#818cf8"],
                labels={"score": "Релевантность (%)"},
            )
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(26,29,39,1)",
                font_color="#9ca3af",
                margin={"l": 0, "r": 0, "t": 20, "b": 0},
                height=220,
                showlegend=False,
            )
            fig.update_xaxes(gridcolor="#2d3148", range=[0, 100])
            fig.update_yaxes(gridcolor="#2d3148")
            st.plotly_chart(fig, use_container_width=True)

        with col_ch2:
            st.markdown("#### Топ компаний")
            company_counts = {}
            for v in vacancies:
                c = v["vacancy"]["company"]
                company_counts[c] = company_counts.get(c, 0) + 1
            top_companies = sorted(company_counts.items(), key=lambda x: x[1], reverse=True)[:8]
            df_comp = pd.DataFrame(top_companies, columns=["company", "count"])
            fig2 = px.bar(
                df_comp,
                x="count",
                y="company",
                orientation="h",
                color_discrete_sequence=["#6366f1"],
                labels={"count": "Вакансий", "company": ""},
            )
            fig2.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(26,29,39,1)",
                font_color="#9ca3af",
                margin={"l": 0, "r": 0, "t": 20, "b": 0},
                height=220,
                showlegend=False,
                yaxis={"autorange": "reversed"},
            )
            fig2.update_xaxes(gridcolor="#2d3148")
            fig2.update_yaxes(gridcolor="#2d3148")
            st.plotly_chart(fig2, use_container_width=True)

    st.markdown("---")

    # ── Пагинация ─────────────────────────────────────────────────────────────
    total = len(filtered)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    if "results_page" not in st.session_state:
        st.session_state["results_page"] = 1
    page = min(st.session_state["results_page"], total_pages)

    start = (page - 1) * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)
    page_items = filtered[start:end]

    st.markdown(f"### Вакансии ({total}) — страница {page} из {total_pages}")

    col_prev, _, col_next = st.columns([1, 3, 1])
    with col_prev:
        if page > 1 and st.button("← Назад"):
            st.session_state["results_page"] = page - 1
            st.rerun()
    with col_next:
        if page < total_pages and st.button("Вперёд →"):
            st.session_state["results_page"] = page + 1
            st.rerun()

    # ── Карточки вакансий ─────────────────────────────────────────────────────
    for i, sv in enumerate(page_items, start=start + 1):
        _render_vacancy_card(i, sv)

    # ── Нижняя пагинация ──────────────────────────────────────────────────────
    if total_pages > 1:
        col_prev2, _, col_next2 = st.columns([1, 3, 1])
        with col_prev2:
            if page > 1 and st.button("← Назад", key="prev_bottom"):
                st.session_state["results_page"] = page - 1
                st.rerun()
        with col_next2:
            if page < total_pages and st.button("Вперёд →", key="next_bottom"):
                st.session_state["results_page"] = page + 1
                st.rerun()

    # ── Экспорт CSV ──────────────────────────────────────────────────────────
    st.markdown("---")
    if st.button("📥 Экспортировать в CSV"):
        rows = []
        for sv in filtered:
            v = sv["vacancy"]
            rows.append(
                {
                    "Должность": v.get("title"),
                    "Компания": v.get("company"),
                    "Город": v.get("city"),
                    "Зарплата": _salary_str(sv),
                    "Релевантность": f"{int(sv['score'] * 100)}%",
                    "Причина": sv.get("match_reason"),
                    "Ссылка": v.get("url"),
                    "Дата": v.get("published_at", "")[:10],
                }
            )
        df_export = pd.DataFrame(rows)
        csv = df_export.to_csv(index=False, encoding="utf-8-sig")
        st.download_button(
            "⬇️ Скачать CSV",
            data=csv.encode("utf-8-sig"),
            file_name=f"vacancies_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )

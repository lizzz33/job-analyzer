"""Страница результатов — основной дашборд"""

from datetime import datetime
import os

import httpx
import pandas as pd
import plotly.express as px
import streamlit as st

API = os.getenv("API_BASE_URL", "http://localhost:8000")


def _load_report() -> list[dict]:
    try:
        r = httpx.get(f"{API}/analysis/report", timeout=5)
        if r.status_code == 200:
            return r.json().get("vacancies", [])
    except Exception:
        pass
    return []


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


def render():
    st.title("📊 Результаты подбора")

    vacancies = _load_report()

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
    st.markdown(f"### Вакансии ({len(filtered)} из {len(vacancies)})")

    # ── Карточки вакансий ─────────────────────────────────────────────────────
    for i, sv in enumerate(filtered, 1):
        v = sv["vacancy"]
        score_pct = int(sv["score"] * 100)
        s_class = _score_class(sv["score"])
        sem_pct = int(sv.get("semantic_score", 0) * 100)
        llm_pct = int(sv.get("llm_score", 0) * 100)
        salary = _salary_str(sv)
        pub_date = v.get("published_at", "")[:10] if v.get("published_at") else ""

        st.markdown(
            f"""
<div class="vacancy-card">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;">
    <div style="flex:1;">
      <div style="font-size:17px;font-weight:600;margin-bottom:2px;">
        {i}. <a href="{v.get("url", "#")}" target="_blank"
              style="color:#c7d2fe;text-decoration:none;">{v.get("title", "")}</a>
      </div>
      <div style="color:#6b7280;font-size:14px;margin-bottom:10px;">
        🏢 {v.get("company", "")} &nbsp;·&nbsp;
        🏙️ {v.get("city", "")} &nbsp;·&nbsp;
        💰 {salary} &nbsp;·&nbsp;
        📅 {pub_date}
      </div>
    </div>
    <div style="text-align:right;min-width:80px;">
      <span class="score-badge {s_class}">{score_pct}%</span>
    </div>
  </div>
  <div style="color:#9ca3af;font-size:13px;margin-bottom:10px;line-height:1.5;">
    {sv.get("match_reason", "")[:200]}
  </div>
  <div style="display:flex;gap:12px;font-size:12px;color:#6b7280;">
    <span>🔍 Семантика: {sem_pct}%</span>
    <span>🤖 LLM: {llm_pct}%</span>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )

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

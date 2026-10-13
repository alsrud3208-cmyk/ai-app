"""수업 성찰 한 마디 + 월간 정리 메시지 (Streamlit)
실행: streamlit run app.py
저장: 로컬 SQLite (reflections.db)
요약: GEMINI_API_KEY가 있으면 Gemini, 없으면 통계 기반 요약
메일: SMTP 설정이 있으면 발송 (선택)
"""
import os
import sqlite3
import smtplib
from collections import Counter
from datetime import datetime, date
from email.mime.text import MIMEText

import pandas as pd
import streamlit as st

DB = "reflections.db"
TAGS = ["적극적으로 참여하기", "발표하기", "경청하기", "집중하기", "기타 다른 노력들을 할 거예요"]
MOODS = {"😀: 최고예요": 4, "🙂: 좋아요": 3, "😐: 아쉬웠어요": 2, "😕: 힘들었어요": 1}


def conn():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS reflections(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT, class_name TEXT, unit TEXT, text TEXT,
        mood INTEGER, tags TEXT, next_change TEXT)""")
    return c


def secret(key, default=""):
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)


def load(month: str | None = None) -> pd.DataFrame:
    with conn() as c:
        df = pd.read_sql("SELECT * FROM reflections ORDER BY ts DESC", c)
    if month and not df.empty:
        df = df[df["ts"].str.startswith(month)]
    return df


def stats_summary(df: pd.DataFrame, month: str) -> str:
    tags = Counter(t for s in df["tags"] for t in s.split(",") if t)
    top = ", ".join(f"{k}({v})" for k, v in tags.most_common(3)) or "없음"
    by_class = df["class_name"].value_counts().to_dict()
    mood = df["mood"].mean()
    quotes = df["text"].head(3).tolist()
    nxt = [x for x in df["next_change"] if x][:2]
    lines = [
        f"## {month} 수업 성찰 정리",
        f"- 기록 횟수: {len(df)}회",
        f"- 학급별: {by_class}",
        f"- 평균 만족도: {mood:.2f} / 4",
        f"- 다음 수업 때 개선할 점 TOP3: {top}",
        "", "### 인상 깊은 한 마디",
        *[f"- {q}" for q in quotes],
        "", "### 오늘 수업에서 잘한 점",
        *([f"- {x}" for x in nxt] or ["- (기록된 '잘한 점' 없음)"]),
    ]
    return "\n".join(lines)


def gemini_summary(df: pd.DataFrame, month: str) -> str:
    key = secret("GEMINI_API_KEY")
    if not key:
        return stats_summary(df, month)
    import google.generativeai as genai
    genai.configure(api_key=key)
    model = genai.GenerativeModel(secret("GEMINI_MODEL", "gemini-2.0-flash"))
    rows = "\n".join(
        f"[{r.ts[:10]}] {r.class_name} {r.unit} | {r.text} | 개선할 점:{r.tags} | 잘한 점:{r.next_change}"
        for r in df.itertuples())
    prompt = f"""당신은 고등학교 국어 교사의 수업 성찰을 정리하는 조력자입니다.
아래는 {month}의 성찰 기록입니다. 규칙: 원문에 없는 내용을 지어내지 말 것,
교사의 어투를 존중할 것, 근거 기록 날짜를 병기할 것.
출력(마크다운): 1) 이번 달 한눈에 보기 2) 잘된 점 3) 아쉬운 점
4) 반복된 개선할 점 키워드 5) 다음 달 실천 제안 1~2개(개선할 점 근거) 6) 인상 깊은 한 마디 3개(원문 인용)

{rows}"""
    try:
        return model.generate_content(prompt).text
    except Exception as e:
        return stats_summary(df, month) + f"\n\n(Gemini 오류로 통계 요약 대체: {e})"


def send_mail(subject: str, body: str) -> str:
    host, user, pw, to = (secret(k) for k in
                          ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "MAIL_TO"))
    if not (host and user and pw and to):
        return "SMTP 설정이 없어 발송하지 않았습니다."
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    with smtplib.SMTP_SSL(host, 465) as s:
        s.login(user, pw)
        s.send_message(msg)
    return f"{to} 로 발송했습니다."


# ---------------- UI ----------------
st.set_page_config(page_title="수업 성찰 한 마디", page_icon="📝", layout="centered")

pw = secret("APP_PASSWORD")
if pw:
    if st.sidebar.text_input("비밀번호", type="password") != pw:
        st.info("사이드바에 비밀번호를 입력하세요.")
        st.stop()

st.title("📝 수업 성찰 한 마디")
tab1, tab2, tab3 = st.tabs(["✍️ 기록하기", "📚 기록 보기", "📬 월간 정리"])

with tab1:
    st.caption("⚠️ 학생 실명·식별 정보는 쓰지 마세요.")
    with st.form("f", clear_on_submit=True):
        c1, c2 = st.columns(2)
        cls = c1.text_input("학년반", st.session_state.get("last_cls", ""), placeholder="2-3")
        unit = c2.text_input("단원/학습지 번호", st.session_state.get("last_unit", ""))
        text = st.text_area("한 마디 성찰 (140자)", max_chars=140, height=100)
        mood = st.radio("수업 만족도", list(MOODS), horizontal=True, index=1)
        tags = st.multiselect("다음 수업 때 개선할 점", TAGS)
        nxt = st.text_input("오늘 수업에서 잘한 점 (선택)")
        ok = st.form_submit_button("저장", use_container_width=True)
    if ok:
        if not text.strip():
            st.error("성찰 내용을 입력해 주세요.")
        else:
            st.session_state.update(last_cls=cls, last_unit=unit)
            with conn() as c:
                c.execute("INSERT INTO reflections(ts,class_name,unit,text,mood,tags,next_change) VALUES(?,?,?,?,?,?,?)",
                          (datetime.now().strftime("%Y-%m-%d %H:%M"), cls, unit,
                           text.strip(), MOODS[mood], ",".join(tags), nxt.strip()))
            n = len(load(date.today().strftime("%Y-%m")))
            st.success(f"저장했습니다. 이번 달 {n}번째 기록이에요 🎉")

with tab2:
    df = load()
    if df.empty:
        st.info("아직 기록이 없습니다.")
    else:
        st.dataframe(df.drop(columns=["id"]), use_container_width=True, hide_index=True)
        st.download_button("CSV 내려받기", df.to_csv(index=False).encode("utf-8-sig"),
                           "reflections.csv", "text/csv")
        with st.expander("기록 삭제"):
            rid = st.selectbox("삭제할 ID", df["id"])
            if st.button("삭제"):
                with conn() as c:
                    c.execute("DELETE FROM reflections WHERE id=?", (int(rid),))
                st.rerun()

with tab3:
    month = st.text_input("월 (YYYY-MM)", date.today().strftime("%Y-%m"))
    mdf = load(month)
    if mdf.empty:
        st.info("해당 월 기록이 없습니다.")
    else:
        st.line_chart(mdf.assign(d=mdf["ts"].str[:10]).groupby("d")["mood"].mean())
        if st.button("정리 메시지 만들기", type="primary"):
            st.session_state["summary"] = gemini_summary(mdf, month)
        if "summary" in st.session_state:
            st.markdown(st.session_state["summary"])
            if st.button("📧 메일로 보내기"):
                st.info(send_mail(f"[{month}] 수업 성찰 월간 정리", st.session_state["summary"]))

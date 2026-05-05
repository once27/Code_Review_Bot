"""
AI Code Review Bot — Streamlit Admin Dashboard

Run: streamlit run dashboard.py
"""

import datetime
import os
import sys

import streamlit as st
import pandas as pd

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from app.auth.github_oauth import (
    get_authorization_url,
    exchange_code_for_token,
    get_github_user,
)
from app.db.session import get_session, init_db
from app.db.crud import get_feedback_stats, get_health_score
from app.models.review import Review, ReviewComment, Feedback, DashboardUser
from app.rag.tasks import run_index_repository

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="AI Code Review Bot — Admin",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS — dark premium theme
# ---------------------------------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* Global */
.stApp {
    font-family: 'Inter', sans-serif;
}

/* Sidebar styling */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0f0f1a 0%, #1a1a2e 100%);
    border-right: 1px solid rgba(99, 102, 241, 0.15);
}
section[data-testid="stSidebar"] .stMarkdown h3 {
    color: #e2e8f0 !important;
}
section[data-testid="stSidebar"] .stMarkdown p,
section[data-testid="stSidebar"] .stMarkdown span {
    color: #94a3b8 !important;
}

/* Metric cards */
div[data-testid="stMetric"] {
    background: linear-gradient(135deg, rgba(99, 102, 241, 0.08) 0%, rgba(139, 92, 246, 0.05) 100%);
    border: 1px solid rgba(99, 102, 241, 0.15);
    border-radius: 12px;
    padding: 16px 20px;
    backdrop-filter: blur(10px);
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}
div[data-testid="stMetric"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 25px rgba(99, 102, 241, 0.15);
}
div[data-testid="stMetric"] label {
    color: #94a3b8 !important;
    font-weight: 500 !important;
    font-size: 0.85rem !important;
    letter-spacing: 0.02em;
}
div[data-testid="stMetric"] [data-testid="stMetricValue"] {
    color: #e2e8f0 !important;
    font-weight: 700 !important;
    font-size: 1.8rem !important;
}

/* Buttons */
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%) !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    padding: 8px 24px !important;
    transition: all 0.3s ease !important;
    box-shadow: 0 4px 15px rgba(99, 102, 241, 0.3) !important;
}
.stButton > button[kind="primary"]:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 20px rgba(99, 102, 241, 0.45) !important;
}
.stButton > button[kind="secondary"],
.stButton > button:not([kind]) {
    border: 1px solid rgba(99, 102, 241, 0.3) !important;
    border-radius: 8px !important;
    font-weight: 500 !important;
    transition: all 0.2s ease !important;
}

/* Dataframes */
div[data-testid="stDataFrame"] {
    border: 1px solid rgba(99, 102, 241, 0.12) !important;
    border-radius: 10px !important;
    overflow: hidden;
}

/* Section headers */
.section-header {
    font-size: 1.1rem;
    font-weight: 600;
    color: #c4b5fd;
    margin: 24px 0 12px 0;
    padding-bottom: 6px;
    border-bottom: 2px solid rgba(99, 102, 241, 0.2);
    letter-spacing: 0.03em;
}

/* Glass card */
.glass-card {
    background: linear-gradient(135deg, rgba(99, 102, 241, 0.06) 0%, rgba(139, 92, 246, 0.04) 100%);
    border: 1px solid rgba(99, 102, 241, 0.12);
    border-radius: 14px;
    padding: 24px;
    margin: 12px 0;
    backdrop-filter: blur(12px);
}

/* Health bar */
.health-bar-container {
    background: rgba(30, 30, 50, 0.6);
    border-radius: 8px;
    height: 10px;
    overflow: hidden;
    margin: 6px 0;
}
.health-bar-fill {
    height: 100%;
    border-radius: 8px;
    transition: width 0.6s ease;
}

/* Login card */
.login-card {
    background: linear-gradient(135deg, rgba(15, 15, 26, 0.95) 0%, rgba(26, 26, 46, 0.95) 100%);
    border: 1px solid rgba(99, 102, 241, 0.2);
    border-radius: 20px;
    padding: 60px 40px;
    text-align: center;
    backdrop-filter: blur(20px);
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
    max-width: 480px;
    margin: 80px auto;
}
.login-card h1 {
    font-size: 2.4rem;
    background: linear-gradient(135deg, #6366f1, #a78bfa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 8px;
}
.login-card p {
    color: #64748b;
    font-size: 1rem;
    margin-bottom: 32px;
}
.github-btn {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
    color: white !important;
    padding: 14px 36px;
    border: none;
    border-radius: 10px;
    font-size: 1rem;
    font-weight: 600;
    cursor: pointer;
    text-decoration: none !important;
    transition: all 0.3s ease;
    box-shadow: 0 8px 25px rgba(99, 102, 241, 0.35);
}
.github-btn:hover {
    transform: translateY(-2px);
    box-shadow: 0 12px 35px rgba(99, 102, 241, 0.5);
}
.github-btn svg { fill: white; width: 20px; height: 20px; }

/* Status badge */
.badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.04em;
}
.badge-admin { background: rgba(99, 102, 241, 0.2); color: #a5b4fc; }
.badge-viewer { background: rgba(52, 211, 153, 0.15); color: #6ee7b7; }

/* Divider */
.styled-divider {
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(99, 102, 241, 0.25), transparent);
    margin: 28px 0;
    border: none;
}

/* Sidebar user card */
.sidebar-user {
    text-align: center;
    padding: 16px 0 8px 0;
}
.sidebar-user img {
    border-radius: 50%;
    border: 2px solid rgba(99, 102, 241, 0.4);
    margin-bottom: 10px;
}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Init DB on first load
# ---------------------------------------------------------------------------
init_db()

# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user" not in st.session_state:
    st.session_state.user = None
if "role" not in st.session_state:
    st.session_state.role = None


# ---------------------------------------------------------------------------
# Helper: get or create dashboard user
# ---------------------------------------------------------------------------
def _lookup_user(github_login: str, github_id: int, avatar_url: str):
    """Check if user is allowed. Returns role or None."""
    session = get_session()
    user = session.query(DashboardUser).filter_by(github_username=github_login).first()
    if not user:
        session.close()
        return None

    # Update last login + avatar
    user.last_login = datetime.datetime.utcnow()
    user.github_id = github_id
    user.avatar_url = avatar_url
    session.commit()
    role = user.role
    session.close()
    return role


def _add_user(github_username: str, role: str = "viewer"):
    """Add a new dashboard user."""
    session = get_session()
    existing = session.query(DashboardUser).filter_by(github_username=github_username).first()
    if existing:
        session.close()
        return False
    user = DashboardUser(github_username=github_username, role=role)
    session.add(user)
    session.commit()
    session.close()
    return True


def _list_users():
    """Get all dashboard users."""
    session = get_session()
    users = session.query(DashboardUser).all()
    data = [
        {
            "Username": u.github_username,
            "Role": u.role,
            "Last Login": str(u.last_login)[:19] if u.last_login else "Never",
        }
        for u in users
    ]
    session.close()
    return data


def _delete_user(username: str):
    """Remove a dashboard user."""
    session = get_session()
    user = session.query(DashboardUser).filter_by(github_username=username).first()
    if user:
        session.delete(user)
        session.commit()
    session.close()


def _update_user_role(username: str, new_role: str):
    """Change a user's role."""
    session = get_session()
    user = session.query(DashboardUser).filter_by(github_username=username).first()
    if user:
        user.role = new_role
        session.commit()
    session.close()


def _get_health_color(score: float) -> str:
    """Return gradient color for health score."""
    if score >= 0.8:
        return "linear-gradient(90deg, #22c55e, #4ade80)"
    elif score >= 0.5:
        return "linear-gradient(90deg, #f59e0b, #fbbf24)"
    else:
        return "linear-gradient(90deg, #ef4444, #f87171)"


# ---------------------------------------------------------------------------
# OAuth flow
# ---------------------------------------------------------------------------
def _handle_oauth_callback():
    """Process GitHub OAuth callback if code is in query params."""
    params = st.query_params
    code = params.get("code")
    if not code:
        return False

    token = exchange_code_for_token(code)
    if not token:
        st.error("❌ GitHub OAuth token exchange failed.")
        return False

    gh_user = get_github_user(token)
    if not gh_user:
        st.error("❌ Could not fetch GitHub profile.")
        return False

    role = _lookup_user(gh_user["login"], gh_user["id"], gh_user["avatar_url"])
    if not role:
        st.error(
            f"❌ User **{gh_user['login']}** is not authorized. "
            "Ask an admin to add you."
        )
        return False

    # Success
    st.session_state.authenticated = True
    st.session_state.user = gh_user
    st.session_state.role = role

    # Clear query params
    st.query_params.clear()
    return True


# ---------------------------------------------------------------------------
# Login page
# ---------------------------------------------------------------------------
GITHUB_SVG = '<svg viewBox="0 0 16 16" width="20" height="20"><path fill="white" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>'

def show_login():
    redirect_uri = os.getenv("STREAMLIT_REDIRECT_URI", "http://localhost:8501")
    auth_url = get_authorization_url(redirect_uri)

    st.markdown(f"""
    <div class="login-card">
        <div style="font-size: 3.5rem; margin-bottom: 16px;">🤖</div>
        <h1>Code Review Bot</h1>
        <p>Admin Dashboard — Sign in with GitHub to continue</p>
        <a href="{auth_url}" class="github-btn" target="_self">
            {GITHUB_SVG}
            Continue with GitHub
        </a>
        <div style="margin-top: 40px; color: #475569; font-size: 0.8rem;">
            Only authorized team members can access this dashboard.
        </div>
    </div>
    """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Page: Overview
# ---------------------------------------------------------------------------
def page_overview():
    st.markdown("## 🏠 Overview")

    session = get_session()
    repos = session.query(Review.repo_owner, Review.repo_name).distinct().all()
    total_reviews = session.query(Review).count()
    total_comments = session.query(ReviewComment).count()
    total_feedbacks = session.query(Feedback).count()
    session.close()

    # Metric cards
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Repos Tracked", len(repos))
    c2.metric("Total Reviews", total_reviews)
    c3.metric("Total Comments", total_comments)
    c4.metric("Feedbacks", total_feedbacks)

    st.markdown('<div class="styled-divider"></div>', unsafe_allow_html=True)

    # Health scores
    if repos:
        st.markdown('<div class="section-header">📈 Repository Health (30 days)</div>', unsafe_allow_html=True)
        for owner, name in repos:
            health = get_health_score(owner, name)
            score = health.get("score", 0)
            total_fb = health.get("total_feedback", 0)
            color = _get_health_color(score)

            st.markdown(f"""
            <div class="glass-card">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <span style="font-size: 1.1rem; font-weight: 600; color: #e2e8f0;">
                            📦 {owner}/{name}
                        </span>
                        <span style="color: #64748b; margin-left: 12px; font-size: 0.85rem;">
                            {total_fb} feedbacks
                        </span>
                    </div>
                    <span style="font-size: 1.4rem; font-weight: 700; color: #a5b4fc;">{score:.0%}</span>
                </div>
                <div class="health-bar-container" style="margin-top: 12px;">
                    <div class="health-bar-fill" style="width: {score*100}%; background: {color};"></div>
                </div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No reviews yet. The bot hasn't reviewed any PRs.")


# ---------------------------------------------------------------------------
# Page: Feedback Stats
# ---------------------------------------------------------------------------
def page_feedback_stats():
    st.markdown("## 📊 Feedback Analytics")

    session = get_session()
    repos = session.query(Review.repo_owner, Review.repo_name).distinct().all()
    session.close()

    if not repos:
        st.info("No reviews yet.")
        return

    selected_repo = st.selectbox("Select repository", [f"{o}/{n}" for o, n in repos])

    if selected_repo:
        owner, name = selected_repo.split("/", 1)
        stats = get_feedback_stats(owner, name)

        overall = stats.get("overall", {})
        accepted = overall.get("accepted", 0)
        dismissed = overall.get("dismissed", 0)
        rate = overall.get("acceptance_rate", 0)

        st.markdown('<div class="styled-divider"></div>', unsafe_allow_html=True)

        c1, c2, c3 = st.columns(3)
        c1.metric("✅ Accepted", accepted)
        c2.metric("❌ Dismissed", dismissed)
        c3.metric("📈 Acceptance Rate", f"{rate:.0%}")

        st.markdown('<div class="styled-divider"></div>', unsafe_allow_html=True)

        per_agent = stats.get("per_agent", {})
        if per_agent:
            st.markdown('<div class="section-header">🤖 Per-Agent Breakdown</div>', unsafe_allow_html=True)

            df = pd.DataFrame([
                {
                    "Agent": agent.title(),
                    "Accepted": data["accepted"],
                    "Dismissed": data["dismissed"],
                    "Acceptance Rate": f"{data['acceptance_rate']:.0%}",
                }
                for agent, data in per_agent.items()
            ])
            st.dataframe(df, use_container_width=True, hide_index=True)

            st.markdown('<div class="section-header">📊 Comparison Chart</div>', unsafe_allow_html=True)
            chart_df = pd.DataFrame([
                {"Agent": a.title(), "Accepted": d["accepted"], "Dismissed": d["dismissed"]}
                for a, d in per_agent.items()
            ])
            st.bar_chart(chart_df.set_index("Agent"))
        else:
            st.info("No feedback data for this repo yet.")


# ---------------------------------------------------------------------------
# Page: RAG Indexing (admin only)
# ---------------------------------------------------------------------------
def page_rag_indexing():
    st.markdown("## 🔍 RAG Indexing")

    if st.session_state.role != "admin":
        st.warning("⚠️ Admin access required for indexing operations.")
        return

    st.markdown('<div class="section-header">🚀 Trigger Repository Indexing</div>', unsafe_allow_html=True)

    with st.container():
        col1, col2, col3 = st.columns(3)
        owner = col1.text_input("Repo Owner", value="once27")
        repo = col2.text_input("Repo Name", value="test-review-bot")
        branch = col3.text_input("Branch", value="main")

        if st.button("🚀 Start Indexing", type="primary"):
            with st.spinner("Queuing indexing task..."):
                try:
                    task = run_index_repository.delay(owner, repo, branch or None)
                    st.success(f"✅ Task queued! ID: `{task.id}`")
                except Exception as e:
                    st.error(f"❌ Failed: {e}")

    st.markdown('<div class="styled-divider"></div>', unsafe_allow_html=True)

    st.markdown('<div class="section-header">📋 Check Task Status</div>', unsafe_allow_html=True)
    task_id = st.text_input("Task ID")
    if task_id and st.button("Check Status"):
        from celery.result import AsyncResult
        from app.worker import celery_app
        result = AsyncResult(task_id, app=celery_app)
        status = result.status
        icon = "✅" if status == "SUCCESS" else "⏳" if status == "PENDING" else "❌"
        st.markdown(f"**{icon} Status:** `{status}`")
        if status == "SUCCESS" and result.result:
            st.json(result.result)


# ---------------------------------------------------------------------------
# Page: User Management (admin only)
# ---------------------------------------------------------------------------
def page_users():
    st.markdown("## 👥 User Management")

    if st.session_state.role != "admin":
        st.warning("⚠️ Admin access required.")
        return

    st.markdown('<div class="section-header">➕ Add New User</div>', unsafe_allow_html=True)
    col1, col2, col3 = st.columns([3, 2, 1])
    new_username = col1.text_input("GitHub Username")
    new_role = col2.selectbox("Role", ["viewer", "admin"])
    col3.markdown("<br>", unsafe_allow_html=True)
    if col3.button("Add User", type="primary"):
        if new_username:
            ok = _add_user(new_username, new_role)
            if ok:
                st.success(f"✅ Added **{new_username}** as `{new_role}`")
                st.rerun()
            else:
                st.warning(f"User **{new_username}** already exists.")

    st.markdown('<div class="styled-divider"></div>', unsafe_allow_html=True)

    st.markdown('<div class="section-header">📋 Current Users</div>', unsafe_allow_html=True)
    users = _list_users()
    if users:
        st.dataframe(pd.DataFrame(users), use_container_width=True, hide_index=True)

        st.markdown('<div class="section-header">🗑️ Remove User</div>', unsafe_allow_html=True)
        del_user = st.selectbox(
            "Select user to remove",
            [u["Username"] for u in users],
            label_visibility="collapsed",
        )
        if st.button("🗑️ Remove User"):
            if del_user == st.session_state.user["login"]:
                st.error("Cannot remove yourself!")
            else:
                _delete_user(del_user)
                st.success(f"Removed **{del_user}**")
                st.rerun()
    else:
        st.info("No users configured yet.")


# ---------------------------------------------------------------------------
# Sidebar + routing
# ---------------------------------------------------------------------------
def show_dashboard():
    user = st.session_state.user
    role = st.session_state.role

    with st.sidebar:
        # User profile
        st.markdown('<div class="sidebar-user">', unsafe_allow_html=True)
        if user.get("avatar_url"):
            st.image(user["avatar_url"], width=80)
        st.markdown(f"**{user['login']}**")
        badge_class = "badge-admin" if role == "admin" else "badge-viewer"
        st.markdown(
            f'<span class="badge {badge_class}">{role.upper()}</span>',
            unsafe_allow_html=True,
        )
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="styled-divider"></div>', unsafe_allow_html=True)

        pages = ["🏠 Overview", "📊 Feedback Analytics"]
        if role == "admin":
            pages += ["🔍 RAG Indexing", "👥 Users"]

        page = st.radio("Navigation", pages, label_visibility="collapsed")

        st.markdown('<div class="styled-divider"></div>', unsafe_allow_html=True)
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.authenticated = False
            st.session_state.user = None
            st.session_state.role = None
            st.rerun()

        # Footer
        st.markdown(
            '<div style="position: fixed; bottom: 16px; color: #475569; font-size: 0.7rem;">'
            '🤖 AI Code Review Bot v1.0</div>',
            unsafe_allow_html=True,
        )

    # Route
    if page == "🏠 Overview":
        page_overview()
    elif page == "📊 Feedback Analytics":
        page_feedback_stats()
    elif page == "🔍 RAG Indexing":
        page_rag_indexing()
    elif page == "👥 Users":
        page_users()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if not st.session_state.authenticated:
        _handle_oauth_callback()

    if st.session_state.authenticated:
        show_dashboard()
    else:
        show_login()


if __name__ == "__main__":
    main()

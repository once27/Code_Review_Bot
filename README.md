# 🤖 AI Code Review Bot

A self-hosted, codebase-aware GitHub bot that analyzes pull requests using a **multi-agent LLM pipeline** and posts structured, severity-classified review comments back via the GitHub API.

---

## ✨ Key Features

| Feature | Description |
|---|---|
| **Multi-Agent Pipeline** | Specialized agents for Security, Performance, Logic, and Style review |
| **RAG Codebase Awareness** | Reviews diffs in context of your entire repository via ChromaDB |
| **Team Rules** | Custom review rules defined in `.codereview.yml` per repo |
| **Review Memory** | Learns from accepted/dismissed suggestions, suppresses false positives |
| **Severity Classification** | `critical` / `warning` / `suggestion` labels with auto-block on critical |
| **Self-Hosted** | Own your data — no SaaS subscription required |

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| API Server | FastAPI |
| Agent Orchestration | LangChain |
| Background Jobs | Celery + Redis |
| Vector Store | ChromaDB |
| Database | PostgreSQL |
| Admin Panel | Django + DRF |
| Containerization | Docker + Compose |
| LLM | OpenAI / HuggingFace |

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- PostgreSQL 15+
- Redis 7+

### Setup

```bash
# 1. Clone the repository
git clone <repo-url>
cd Code_Review_Bot

# 2. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate    # Linux/Mac

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
# Edit .env with your actual keys and secrets

# 5. Run the development server
uvicorn app.main:app --reload
```

### Verify

```bash
curl http://localhost:8000/ping
# → {"status": "ok"}
```

---

## 📁 Project Structure

```
Code_Review_Bot/
├── app/
│   ├── main.py              # FastAPI application entry point
│   ├── agents/              # Multi-agent review pipeline
│   ├── rag/                 # RAG indexing & retrieval (ChromaDB)
│   ├── github/              # Webhook handling & GitHub API client
│   ├── tasks/               # Celery background tasks
│   ├── config/              # .codereview.yml parser & app settings
│   └── models/              # SQLAlchemy ORM models & DB session
├── tests/                   # Test suite
├── .env.example             # Environment variable template
├── requirements.txt         # Python dependencies
└── README.md
```

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/ping` | Health check |
| `POST` | `/webhook/github` | Receives GitHub PR events |
| `POST` | `/repos/register` | Register a new repository |
| `POST` | `/repos/{id}/index` | Trigger codebase re-indexing |
| `GET` | `/health/{repo_id}` | Review Health Score |
| `GET` | `/stats/{repo_id}` | Per-agent accuracy stats |
| `POST` | `/feedback` | Submit accept/dismiss on a comment |
| `GET` | `/reviews/{pr_id}` | Get all comments for a PR |

---

## 🏗️ Architecture

> Architecture diagram coming soon.

---

## 📜 License

Private — All rights reserved.

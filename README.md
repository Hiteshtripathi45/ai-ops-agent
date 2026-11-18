# AI Operations Agent

Note: This app is hosted on Render's free tier. If it has been idle, the first request may take ~50 seconds to spin up.

A safety-focused, human-in-the-loop LLM agent built with FastAPI, SQLAlchemy, and OpenAI/Gemini. It resolves customer refund requests end-to-end by querying a database, detecting duplicate payments, and issuing refunds—with strict idempotency and human approval gates for large amounts.

## Live Demo
- **Swagger UI:** [https://your-app.onrender.com/docs](https://your-app.onrender.com/docs)
- **Health Check:** [https://your-app.onrender.com/health](https://your-app.onrender.com/health)
*(Note: Hosted on Render's free tier. The first request may take ~50 seconds to spin up.)*

## Why this project exists
Most LLM agent demos just let the model run wild. This project focuses on **agent safety and reliability**:
- **Human-in-the-loop:** Refunds over a certain threshold pause the agent and wait for human approval via an API endpoint.
- **Idempotency:** Write tools (like `issue_refund`) track their own execution state so a model looping can't double-refund a customer.
- **Security:** Internal flags (like `_approved`) are stripped from LLM-generated tool arguments to prevent prompt injection.
- **Resilience:** Durable state allows the agent to pause mid-conversation, survive a server restart, and resume exactly where it left off.

## Architecture
- **Framework:** FastAPI, SQLAlchemy (SQLite)
- **LLM:** OpenAI (`gpt-4o-mini`) / Gemini (`gemini-3.6-flash`) via OpenAI-compatible SDK
- **Deployment:** Docker, Render

## How to run locally
1. Clone the repo: `git clone ...`
2. Create virtual env: `python -m venv venv`
3. Activate: `source venv/bin/activate`
4. Install: `pip install -r requirements.txt`
5. Create `.env` with:
   ```env
   GEMINI_API_KEY=your_key_here
   APP_API_KEY=your_secret_here

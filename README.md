# Farvision Automation

Automates preparation of Farvision ERP import sheets: reads a bank statement Google Sheet, classifies each transaction against a Master sheet, and writes the correctly-formatted rows into the existing Deposit/Withdrawal or Receipt/Payment Google Sheets.

See [docs/business-rules.md](docs/business-rules.md) for the confirmed business logic derived from live sheet inspection.

## Tech Stack

- **Frontend:** Next.js (TypeScript, Tailwind CSS, App Router)
- **Backend:** FastAPI (Python), gspread (Google Sheets API), pandas
- **Database:** Supabase (Postgres) — duplicate-detection ledger + audit log
- **Deployment:** Vercel (both frontend and backend)

## Live Deployment

| Component | URL |
|---|---|
| Frontend | https://frontend-iota-two-22.vercel.app |
| Backend | https://farvision-backend.vercel.app |

Key endpoints: `GET /api/v1/health`, `GET /api/v1/sheets/status`, `POST /api/v1/automation/run?dry_run=true|false`, `GET /api/v1/runs`, `GET /api/v1/logs`, `GET /api/v1/stats`.

## Local Development

**Backend:**
```bash
cd backend
python -m venv .venv
.venv/Scripts/activate  # or source .venv/bin/activate on Linux/Mac
pip install -r requirements.txt
cp .env.example .env  # fill in real values
uvicorn app.main:app --reload
```

**Frontend:**
```bash
cd frontend
npm install
cp .env.example .env.local  # fill in real values
npm run dev
```

## Deployment Notes

- Both the frontend and backend are deployed as separate Vercel projects (`frontend`, `farvision-backend`), rooted at their respective subdirectories.
- The backend runs on Vercel's Python serverless runtime (`backend/api/index.py` + `backend/vercel.json`). **Important:** Vercel's Python builder reads dependencies exclusively from `backend/pyproject.toml`, not `requirements.txt` — keep both in sync when adding a new import.
- Google service account credentials are provided via the `GOOGLE_CREDENTIALS_JSON_BASE64` env var (base64-encoded service account JSON) rather than a file, since Vercel's filesystem doesn't have the git-ignored `credentials/service-account.json` available at runtime.

### ⚠️ Known limitation: Vercel Hobby's 10-second function timeout

The free Hobby plan hard-caps serverless function execution at 10 seconds. The automation engine's duplicate-detection was optimized to a single batched Supabase query (rather than one round-trip per transaction) specifically to stay under this limit at the current small data volume. As real bank statement volume grows, this may eventually become a real constraint. If it does, the fix is either:

1. Move the backend to **Railway** or **Render** — no code changes needed, it's a standard ASGI app, or
2. Upgrade to **Vercel Pro**, which allows raising the function timeout up to 300s+.

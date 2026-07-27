# Farvision Automation

Automates preparation of Farvision ERP import sheets for the Accounts team: upload the day's bank statement, transactions are classified against a Master sheet, and the correctly-formatted rows are written into the existing Deposit/Withdrawal or Receipt/Payment Google Sheets — ready for import into Farvision.

See [docs/business-rules.md](docs/business-rules.md) for the confirmed business logic derived from live sheet inspection.

## Tech Stack

- **Frontend:** Next.js (TypeScript, Tailwind CSS, App Router)
- **Backend:** FastAPI (Python), gspread (Google Sheets API), pandas
- **Database:** Supabase (Postgres) — duplicate-detection ledger + audit log
- **Deployment:** Vercel — single project serving both frontend and backend

## Live Deployment

**https://farvision-app.vercel.app**

Frontend and backend are served from the same domain (one Vercel project). Key API endpoints: `GET /api/v1/health`, `GET /api/v1/sheets/status`, `POST /api/v1/automation/run-upload?dry_run=true|false` (upload a statement file), `POST /api/v1/automation/run?dry_run=true|false` (process the configured Google Sheet tab directly), `GET /api/v1/runs`, `GET /api/v1/logs`, `GET /api/v1/stats`.

## Daily Workflow

1. Accounts team opens the dashboard and uploads the day's bank statement (`.xlsx` or `.csv`, same columns as the existing sheet format: `SL#, TXN DATE, DESCRIPTION, REFERENCE, DEBITS, CREDITS, BUSINESS UNIT, HEAD, ...`).
2. Each transaction is classified — `HEAD` is trusted if already filled in on the file, otherwise derived from a Master-sheet lookup by payee name; internal transfers route to Deposit/Withdrawal, everything else to Receipt/Payment.
3. Preview with dry-run first, then run for real to write into the existing Google Sheets.
4. Anything unmatched is flagged for manual review rather than guessed at.
5. Accounts uploads the completed sheets to Farvision as before.

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

- Single Vercel project (`farvision-app`), Root Directory = repo root. A root-level `vercel.json` mixes an `@vercel/next` build (`frontend/`) with an `@vercel/python` build (`backend/api/index.py`), routing `/api/*` to the backend and everything else to the Next.js app — same domain, so no CORS config needed.
- The backend runs on Vercel's Python serverless runtime. **Important:** Vercel's Python builder reads dependencies exclusively from `backend/pyproject.toml`, not `requirements.txt` — keep both in sync when adding a new import.
- Google service account credentials are provided via the `GOOGLE_CREDENTIALS_JSON_BASE64` env var (base64-encoded service account JSON) rather than a file, since Vercel's filesystem doesn't have the git-ignored `credentials/service-account.json` available at runtime.
- Git integration is connected — pushes to `master` auto-deploy.

### ⚠️ Known limitation: Vercel Hobby's 10-second function timeout

The free Hobby plan hard-caps serverless function execution at 10 seconds. The automation engine's duplicate-detection was optimized to a single batched Supabase query (rather than one round-trip per transaction) specifically to stay under this limit at the current small data volume. As real bank statement volume grows, this may eventually become a real constraint. If it does, the fix is either:

1. Move the backend to **Railway** or **Render** — no code changes needed, it's a standard ASGI app, or
2. Upgrade to **Vercel Pro**, which allows raising the function timeout up to 300s+.

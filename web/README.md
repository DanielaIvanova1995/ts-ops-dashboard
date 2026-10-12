# TradeHub web (new app front-end)

A **Next.js (React)** front-end — the fast, live order-processing board. It talks to the FastAPI
backend in `../api`. The live Streamlit app is separate and untouched.

## Run locally
```bash
cd web
npm install
cp .env.local.example .env.local   # point NEXT_PUBLIC_API_URL at the API (default localhost:8000)
npm run dev                         # http://localhost:3000
```
(Have the API running too: from the repo root, `uvicorn api.main:app --port 8000`.)

## Deploy (Vercel — the right host for a React app)
1. Create a free **Vercel** account and **Import** this GitHub repo.
2. Set the project's **Root Directory** to `web`.
3. Add an **Environment Variable**: `NEXT_PUBLIC_API_URL` = the API's URL (the Render API service).
4. Deploy. Vercel gives you a URL; later we can point a custom domain at it.
5. Back on the **API** (Render), set `WEB_ORIGINS` to this Vercel URL so CORS allows it.

## Status (Phase 1)
- ✅ Read-only board: live NEW ORDERS from Monday, fast, with status pills.
- ⏭ Next: inline Supplier/Stage edits (instant), routing + PO, process all/selected, splits.

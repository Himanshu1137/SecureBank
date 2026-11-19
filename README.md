# SecureBank Pro — Full-stack banking app with AI assistant

- `backend/`  Django 5 project (your original apps + new `api/` REST layer, token auth, atomic money movement, AI assistant)
- `frontend/` React + HTML + CSS + JavaScript client (no build step; open via Django at `/app/`)
- `docs/STEPS.md` step-by-step process map, run instructions, architecture

Quick start: see `docs/STEPS.md`. Demo login: `demo@securebank.in` / `Demo@1234` (after `python manage.py seed_demo`; it also prints the demo card, ATM PIN and mPIN).
Admin: `admin@securebank.in` / `Admin@1234`.
Features: KYC document upload + admin review/approval (all transactions stay locked until approval), debit card application with admin approval (ATM service starts only after approval), real SMS OTP (register, login, high-value transfer), bill pay & recharge, loans/EMI, cheque book, PDF statement, admin dashboard, mobile OTP + Aadhaar KYC signup, debit card + ATM banking, UPI id/IFSC transfers, fixed deposits, WhatsApp banking, Claude-powered AI assistant.

Tests: `cd backend && python manage.py test api` (94 test cases).  Survey analysis for the thesis: `analysis/` (see its README).

# SecureBank — step-by-step build guide

| Step | Banking process | Backend (Django) | Frontend (React) |
|------|-----------------|------------------|------------------|
| 1 | Account opening (KYC-lite: name, DOB 18+, address, PIN) + Login | `POST /api/register/`, `POST /api/login/` (signed token) | `Auth` (2-step form) |
| 2 | Dashboard: balance, totals, trend, recent activity | `GET /api/me/`, `GET /api/transactions/` | `Dashboard` |
| 3 | Deposit | `POST /api/deposit/` (min ₹10, atomic + row lock) | `Money kind=deposit` |
| 4 | Withdraw | `POST /api/withdraw/` (min ₹10, per-type limit, balance check) | `Money kind=withdraw` |
| 5 | Transfer to another account | `POST /api/transfer/` (both ledgers updated atomically) | `Money kind=transfer` |
| 6 | Statement: filter, search, CSV | `GET /api/transactions/?type=&q=`, `GET /api/statement/` | `History` |
| 7 | Interest | Celery monthly task `transactions/tasks.py` only (the customer-callable demo endpoint was removed: it allowed unlimited free interest) | - |
| 8 | AI assistant (account-aware, private) | `POST /api/assistant/` → `api/assistant.py` | `Assistant` chat widget |
| 9 | Profile & security | `GET /api/me/` | `Profile` |
| 10 | Mobile OTP (+91) | `POST /api/otp/send/`, `/api/otp/verify/` (hashed OTP, 5 min expiry, 5 attempts, 30 s resend gap) | `Auth` step 2 |
| 11 | Aadhaar KYC | `kyc.py`: 12-digit + Verhoeff checksum, consent, only last 4 digits + salted hash stored | `Auth` step 3 |
| 12 | Debit card issue (Luhn, expiry, CVV hash) + ATM PIN + block/limits | `/api/card/`, `/api/card/set-pin/`, `/api/card/action/` (mPIN protected) | `CardPage` |
| 13 | ATM banking: balance, cash (₹100 notes, ₹10k/txn, daily limit), mini statement, PIN change, 3-wrong-PIN lock | `POST /api/atm/` | `ATM` simulator |
| 14 | UPI id (`mobile@securebank`), IFSC, transfer by A/c no / mobile / UPI id | `resolve_target()` in `views.py` | Transfer page |
| 15 | Fixed deposit (6.00–7.25 %, quarterly compounding, early-closure penalty) | `/api/fd/`, `/api/fd/open/`, `/api/fd/close/` | `FDPage` |
| 16 | WhatsApp banking: BALANCE, STATEMENT, SEND x TO y + mPIN confirm, BLOCK CARD, free-text AI | `/api/whatsapp/webhook/` (Meta Cloud API, signature verified), `/api/whatsapp/simulate/` | `WhatsApp` simulator |
| 18 | Real SMS OTP: registration, 2-step login, transfers above ₹10,000 (hashed, 5 min expiry, 5 attempts, 5/hour limit) | `api/otp.py`, `api/sms.py` (MSG91 / Fast2SMS / Twilio) | OTP screens |
| 19 | Beneficiaries (save / pick / remove payees) | `/api/beneficiaries/…` | Transfer page chips |
| 20 | Bill payments + mobile/DTH recharge (6 categories, 25+ billers) | `/api/billers/`, `/api/pay/`, `/api/payments/` | `Payments` |
| 21 | Loans: Personal/Home/Education/Vehicle, EMI, 50%-of-income rule, officer approval, disbursal, EMI payment | `/api/loans/…`, `/api/admin/loans/decide/` | `Loans` |
| 22 | Cheque book request + dispatch | `/api/cheque/…`, `/api/admin/cheques/…` | `Services` |
| 23 | PDF + CSV statement (dependency-free PDF writer) | `GET /api/statement.pdf` | History / Services |
| 24 | Admin dashboard: KPIs, loan approvals, cheque dispatch, freeze/unfreeze customers | `/api/admin/…` (staff only) | `Admin` (login as admin) |
| 25 | KYC document upload at signup (Aadhaar required; PAN, photo optional) - JPG/PNG/PDF, max 2 MB, content-type verified by file signature, stored in a private folder (`backend/private_media/`) | `POST /api/documents/upload/`, `GET /api/documents/` | `Auth` step 3, Profile |
| 26 | KYC approval workflow: new accounts start as PENDING - **every** money action is blocked (deposit, withdraw, transfer in/out, bills, FD, loans, cheque, interest, ATM) until staff approve; staff must open the Aadhaar document before approving (`KYC_REQUIRE_REVIEW`); rejected users re-upload | `/api/admin/kyc/…`, `/api/admin/documents/<id>/` (staff only) | Admin > KYC approvals |
| 28 | Debit card application: after KYC approval the customer applies (Classic: Rs. 20,000/day ATM limit, Platinum: Rs. 50,000/day) with the mPIN; staff approve or reject (single or approve-all); the card is created and ATM service starts only on approval, CVV shown once | `POST /api/card/apply/`, `/api/admin/cards/…`, `issue_card()` called from `kycdocs.decide_card()` | Card & ATM, Admin > Card approvals |
| 29 | Admin: accounts-opened counters (total, today, KYC pending/verified/rejected, cards issued) and full customer detail (profile, address, KYC, documents, account, card, FDs, loans, cheques, last 25 transactions) | `GET /api/admin/summary/`, `GET /api/admin/customers/<id>/` | Admin > Overview / Customers |
| 27 | Bulk approvals: Approve all reviewed KYC / Approve all loans / Dispatch all cheque books (two-click confirmation) | `/api/admin/kyc/approve-all/`, `/api/admin/loans/approve-all/`, `/api/admin/cheques/dispatch-all/` | Admin |
| 17 | AI assistant (Claude) with account context, Hindi/Hinglish/English, safe fallback | `api/assistant.py` (`ANTHROPIC_API_KEY`) | Floating chat |

## Run locally
```bash
cd backend
python -m venv venv && venv\Scripts\activate        # Windows  (Linux/Mac: source venv/bin/activate)
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo                           # account types + demo@securebank.in / Demo@1234
python manage.py runserver
```
- React app: http://127.0.0.1:8000/app/
- Original Django-template UI: http://127.0.0.1:8000/
- Admin: `python manage.py createsuperuser` → http://127.0.0.1:8000/admin/

## Going live with real services
- **AI assistant:** set `ANTHROPIC_API_KEY` in `backend/.env` (model via `ANTHROPIC_MODEL`). The model only sees the logged-in customer's balance/recent transactions and can never move money or see PIN/OTP/Aadhaar. No key or any error → rule-based fallback.
- **Real SMS OTP (already implemented):** put `SMS_PROVIDER` + that provider's keys in `backend/.env`.
  - `msg91`: `MSG91_AUTHKEY`, `MSG91_TEMPLATE_ID` (OTP template with the `##OTP##` variable, DLT-approved in India).
  - `fast2sms`: `FAST2SMS_KEY` (OTP route). `twilio`: `TWILIO_SID`, `TWILIO_TOKEN`, `TWILIO_FROM`.
  - Once a provider is set, the OTP is **never** returned in API responses. With no provider and `DEBUG=False`, OTP endpoints return 503 instead of faking it.
  - Set `LOGIN_OTP=False` only if you want password-only login.
- **WhatsApp:** create a Meta WhatsApp Business app → webhook URL `https://<your-domain>/api/whatsapp/webhook/`, verify token = `WHATSAPP_VERIFY_TOKEN`, set `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_APP_SECRET`. (Use ngrok for local testing.)
- **Aadhaar:** this project validates format + checksum only. Genuine UIDAI e-KYC (OTP/offline XML) needs a licensed KUA/AUA or a provider such as Digio/Setu/Sandbox.co.in — hook it in `register()` and set `kyc_status`.
- Demo seed data: customer `demo@securebank.in` / `Demo@1234` (mobile 9876543210, mPIN 2468, ATM PIN 2580; card number printed by `seed_demo`), bank admin `admin@securebank.in` / `Admin@1234`. Change/remove these before any real deployment.

## Demo without a backend
`frontend/build-demo.py` bundles the React app + an in-browser mock bank (`mode: 'mock'` in `js/api.js`) into one `demo.html`.

## Architecture
```
frontend (React UMD + htm)  --fetch JSON + Bearer token-->  Django API (api/)  -->  accounts / transactions models (SQLite)
                                                                   └── Celery + Redis (optional): monthly interest
```
Switch the frontend between real API and mock with `window.SB_CONFIG.mode` in `frontend/index.html`.

## Production checklist (this is a portfolio simulation)
Set `SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS`; use PostgreSQL; add login rate-limiting + OTP/2FA; HTTPS only; audit log; idempotency keys for transfers.

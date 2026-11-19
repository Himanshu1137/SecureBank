# Security changes in this version

Applied on top of the original `securebank-pro` zip. **Not executed in the build sandbox (no Django installed):** Python and JS were syntax-checked only.
Run `cd backend && python manage.py test api` before using it (original 94 tests + 6 new ones, TC-100..105; TC-35 was rewritten).

## Fixed
| # | Problem | Fix |
|---|---------|-----|
| 1 | Accounts with no KYC profile (old `/accounts/register/`) could use every money API and the old deposit/withdraw pages | `require_kyc` now fails closed; recipient must be VERIFIED; old registration redirects to `/app/`; old deposit/withdraw need VERIFIED KYC |
| 2 | `POST /api/interest/` let any user credit unlimited interest | Endpoint, frontend button and mock removed (Celery task remains) |
| 3 | Default `SECRET_KEY` could sign forged staff tokens; `0.0.0.0` in default hosts | With `DEBUG=False` the app refuses to start unless `SECRET_KEY` is 32+ chars and not a "change-me" value; secure cookies when not DEBUG; `0.0.0.0` removed |
| 4 | WhatsApp webhook accepted unsigned requests when `WHATSAPP_APP_SECRET` was empty | Rejected with 403 outside DEBUG |
| 5 | No login throttling | 10 failures / 15 min per email+IP, 50 per IP |
| 6 | Throttle counters were per-process | Optional `REDIS_CACHE_URL` shared cache (set it in production) |
| 7 | OTP 6th guess could still succeed | Attempts checked before comparing |
| 8 | Transfer notes from other users reached the AI prompt unfiltered; no assistant rate limit | Notes sanitised and marked untrusted; 20 questions/min per customer |
| 9 | `seed_demo` created known admin/demo passwords anywhere | Blocked when `DEBUG=False` unless `--force` |

## Still open (not changed)
- `DEBUG` still defaults to True for easy local start: set `DEBUG=False` + `SECRET_KEY` in production.
- Staff 2FA, role separation, audit log, "approve all loans" bulk disbursal.
- Full card number is returned by `/api/card/`; CVV is stored in `reveal_cvv` until first view (PCI DSS forbids storing CVV); KYC files are unencrypted on disk.
- Aadhaar hash is `sha256(SECRET_KEY + number)` (brute-forceable if DB and key leak); check Aadhaar storage rules with a lawyer/compliance officer.
- Tokens are 7-day, non-revocable, kept in `localStorage`.
- Old Django deposit/withdraw views have no row locking; `select_for_update` is a no-op on SQLite (use PostgreSQL).
- No SMS-pumping protection on `/api/otp/send/` (add CAPTCHA / per-IP limits); registration reveals whether an email/phone exists.
- Transfer OTP is not bound to amount/recipient; no daily transfer limit.
- React CDN scripts have no SRI hashes.

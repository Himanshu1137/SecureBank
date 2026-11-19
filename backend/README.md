# SecureBank — Professional Digital Banking + AI Assistant

SecureBank is a Django-based banking demo with a colourful professional frontend and a privacy-first, account-aware AI assistant.

## Features
- Custom email-based authentication
- Bank account creation and account types
- Deposit and withdrawal flows with validation
- Transaction history with filters
- CSV statement download
- Profile and security center
- Responsive professional banking UI
- SecureBank AI Assistant for balance, account, transaction, deposit, withdrawal and security questions
- Celery + Redis-ready interest calculation task
- SQLite database for local development

## Recommended Python
Use **Python 3.11** for the smoothest local setup.

## Run in VS Code (Windows)
```powershell
py -3.11 -m venv venv
venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Open: http://127.0.0.1:8000/

### Optional admin account
```powershell
python manage.py createsuperuser
```
Then open: http://127.0.0.1:8000/admin/

## Redis / Celery
The website itself does not require a running Celery worker for normal browsing, login, deposits, withdrawals or the AI Assistant. Interest automation is Celery/Redis-ready.

Start Redis, then in separate terminals:
```powershell
celery -A banking_system worker -l info
celery -A banking_system beat -l info
```

## Project structure
- `accounts/` — users, bank accounts and profiles
- `transactions/` — deposits, withdrawals, reports and scheduled interest task
- `ai_assistant/` — account-aware assistant API
- `core/` — landing page and shared UI
- `templates/` — professional frontend
- `static/` — CSS and assistant JavaScript
- `banking_system/` — Django configuration and Celery setup

> This is a college/portfolio banking simulation, not a production banking system.

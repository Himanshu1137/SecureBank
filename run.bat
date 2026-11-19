@echo off
setlocal
cd /d "%~dp0backend"

if not exist venv\Scripts\activate.bat (
    echo [SecureBank] Creating Python Virtual Environment...
    py -3 -m venv venv
)

echo [SecureBank] Activating virtual environment...
call venv\Scripts\activate.bat

echo [SecureBank] Installing dependencies...
pip install -r requirements.txt

echo [SecureBank] Running database migrations...
python manage.py migrate

echo [SecureBank] Seeding demo data...
python manage.py seed_demo

echo.
echo ========================================================
echo  SecureBank Pro is running!
echo  Open Web App:   http://127.0.0.1:8000/app/
echo  Django Admin:   http://127.0.0.1:8000/admin/
echo.
echo  Demo Customer:  demo@securebank.in / Demo@1234
echo  Bank Admin:     admin@securebank.in / Admin@1234
echo ========================================================
echo.

start http://127.0.0.1:8000/app/
python manage.py runserver

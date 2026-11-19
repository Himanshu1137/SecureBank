@echo off
setlocal
cd /d "%~dp0"
if not exist venv\Scripts\activate.bat (
  echo Creating virtual environment...
  py -3 -m venv venv
)
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
echo.
echo Open http://127.0.0.1:8000/app/ in your browser
python manage.py runserver

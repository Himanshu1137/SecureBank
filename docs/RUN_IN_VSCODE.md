# Run SecureBank in VS Code (Windows)

1. Install **Python 3.11 or 3.12** from python.org (tick "Add python.exe to PATH") and **VS Code**.
2. In VS Code install the extension **Python** (Microsoft).
3. Unzip `securebank-pro.zip` -> VS Code: **File > Open Folder** -> choose the `securebank-pro` folder.
4. Open the terminal: **Terminal > New Terminal** (PowerShell) and go to the backend:
   ```
   cd backend
   ```
5. Create + activate a virtual environment:
   ```
   py -3 -m venv venv
   venv\Scripts\Activate.ps1
   ```
   If PowerShell blocks it: `Set-ExecutionPolicy -Scope Process Bypass` and activate again. (You should now see `(venv)` in the prompt.)
6. In VS Code press **Ctrl+Shift+P > Python: Select Interpreter** and pick the one inside `backend\venv`.
7. Install packages: `pip install -r requirements.txt`
8. Create the database and demo data:
   ```
   python manage.py migrate
   python manage.py seed_demo
   ```
9. Start the server: `python manage.py runserver`   (or press **F5** and choose "SecureBank: Django runserver")
10. Open **http://127.0.0.1:8000/app/** in the browser (internet needed once for React from CDN).

Logins
- Customer: `demo@securebank.in` / `Demo@1234` -> OTP is shown on the screen (dev mode)
- Bank admin: `admin@securebank.in` / `Admin@1234` (no OTP)
- Demo mPIN `2468`, ATM PIN `2580`, card number is printed by `seed_demo`
- Old Django-template UI: http://127.0.0.1:8000/  | Django admin: /admin/

Stop the server with **Ctrl+C**. Next time only steps 4 (cd backend), 5 (activate) and 9 are needed.

Optional settings: copy `backend/.env.example` to `backend/.env` and fill SMS / WhatsApp / AI keys, then restart the server.
Redis/Celery are NOT needed to run the project (only for the monthly interest background job).

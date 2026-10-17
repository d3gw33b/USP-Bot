@echo off
rem Starts the USP bot in the background, so closing this window doesn't stop it.
rem If an older copy is still running, it is stopped first, so this always loads the newest code.
rem Stop it with: py -3 usp_live.py --stop   (run in this folder). Its log is bot.log.
cd /d "%~dp0"
if not exist bot.env (
  echo Make bot.env first: copy bot.env.example, rename the copy to bot.env, and fill in the values.
  pause
  exit /b 1
)
where pyw >nul 2>nul
if %errorlevel%==0 (set PYW=pyw -3) else (set PYW=pythonw)
py -3 usp_live.py --stop >nul 2>nul
timeout /t 3 /nobreak >nul
start "" %PYW% usp_live.py

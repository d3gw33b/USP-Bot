@echo off
rem Starts the USP bot in the background, so closing this window doesn't stop it.
rem Stop it with: py -3 usp_live.py --stop   (run in this folder). Its log is bot.log.
cd /d "%~dp0"
if not exist bot.env (
  echo Make bot.env first: copy bot.env.example, rename the copy to bot.env, and fill in the values.
  pause
  exit /b 1
)
where pyw >nul 2>nul
if %errorlevel%==0 (start "" pyw -3 usp_live.py) else (start "" pythonw usp_live.py)

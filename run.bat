@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Chon python: uu tien py -3.11, roi python trong PATH (can 3.11 tro len)
set "PY="
py -3.11 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=py -3.11"
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)" >nul 2>&1
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo Khong tim thay Python 3.11 tro len.
  echo Hay cai Python 3.11 64-bit tu https://www.python.org/downloads/ va tick "Add python.exe to PATH".
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Dang tao moi truong ao .venv ...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo Khong tao duoc moi truong ao.
    pause
    exit /b 1
  )
)

rem Goi qua python.exe (khong qua pip.exe / facesort.exe) de tranh bi Application Control chan
if not exist ".venv\.facesort_installed" (
  echo Dang cai dat cac goi can thiet, lan dau co the mat vai phut ...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1
  ".venv\Scripts\python.exe" -m pip install -e ".[ml]"
  if errorlevel 1 (
    echo Cai dat that bai. Kiem tra ket noi mang roi chay lai run.bat.
    pause
    exit /b 1
  )
  echo ok> ".venv\.facesort_installed"
)

".venv\Scripts\python.exe" -m facesort ui
if errorlevel 1 pause

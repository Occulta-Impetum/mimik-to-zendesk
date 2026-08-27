@echo off
setlocal
cd /d "%~dp0"

if "%~1"=="" (
    echo Mimik HTML Converter
    echo ====================
    echo.
    echo Drag one or more Mimik HTML exports onto this BAT file.
    echo.
    pause
    exit /b 1
)

where py >nul 2>&1
if %errorlevel%==0 (
    py "%~dp0mimik_converter.py" %*
    exit /b %errorlevel%
)

where python >nul 2>&1
if %errorlevel%==0 (
    python "%~dp0mimik_converter.py" %*
    exit /b %errorlevel%
)

echo ERROR: Python was not found.
echo Install Python 3 and make sure "py" or "python" is available.
echo.
pause
exit /b 1

@echo off

set "LOGFILE=%USERPROFILE%\Desktop\install_log.txt"

echo Installation started at %date% %time% > "%LOGFILE%"
echo. >> "%LOGFILE%"

echo Installing Python packages from requirements.txt...
echo Installing Python packages from requirements.txt... >> "%LOGFILE%"
echo.
echo. >> "%LOGFILE%"

pip install -r requirements.txt >> "%LOGFILE%" 2>&1

echo. >> "%LOGFILE%"
echo Pip install completed >> "%LOGFILE%"
echo. >> "%LOGFILE%"

echo Pip installation completed.
echo.

set "SCRIPT_DIR=%~dp0"
set "DESKTOP=%USERPROFILE%\Desktop"
set "SHORTCUT=%DESKTOP%\KG Chat.lnk"

REM Build absolute paths - remove trailing backslash from SCRIPT_DIR
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "TARGET=%SCRIPT_DIR%\launchers\launcher.pyw"
set "ICON=%SCRIPT_DIR%\src\icons\chat.ico"

echo Script Directory: %SCRIPT_DIR% >> "%LOGFILE%"
echo Desktop: %DESKTOP% >> "%LOGFILE%"
echo Shortcut Path: %SHORTCUT% >> "%LOGFILE%"
echo Target: %TARGET% >> "%LOGFILE%"
echo Icon: %ICON% >> "%LOGFILE%"
echo. >> "%LOGFILE%"

echo Checking for existing shortcut...
echo Checking for existing shortcut... >> "%LOGFILE%"
echo Target: %TARGET%
echo Icon: %ICON%
echo.

if exist "%SHORTCUT%" (
    echo Desktop shortcut already exists.
    echo Desktop shortcut already exists. >> "%LOGFILE%"
) else (
    echo Creating desktop shortcut...
    echo Creating desktop shortcut... >> "%LOGFILE%"
    
    powershell -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT%'); $s.TargetPath = '%TARGET%'; $s.IconLocation = '%ICON%'; $s.WorkingDirectory = '%SCRIPT_DIR%'; $s.Save()" >> "%LOGFILE%" 2>&1
    
    if exist "%SHORTCUT%" (
        echo Desktop shortcut created successfully!
        echo Desktop shortcut created successfully! >> "%LOGFILE%"
    ) else (
        echo Failed to create desktop shortcut.
        echo Failed to create desktop shortcut. >> "%LOGFILE%"
    )
)

echo. >> "%LOGFILE%"
echo Installation ended at %date% %time% >> "%LOGFILE%"

echo.
echo Log file saved to: %LOGFILE%
echo.
echo Done. Press any key to close...
pause
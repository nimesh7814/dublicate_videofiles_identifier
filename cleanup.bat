@echo off
title System Cleanup
color 0A
echo.
echo ============================================
echo         SYSTEM CLEANUP UTILITY
echo ============================================
echo.
echo This will:
echo   [1] Empty the Recycle Bin
echo   [2] Clear Windows File Explorer search history
echo   [3] Clear Recent Files (Quick Access)
echo   [4] Clear Recent Files list in registry
echo.
set /p confirm=Are you sure? (Y/N): 
if /i not "%confirm%"=="Y" (
    echo Cancelled.
    pause
    exit /b
)

echo.
echo [1/4] Emptying Recycle Bin...
PowerShell.exe -NoProfile -Command "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"
echo       Done.

echo.
echo [2/4] Clearing File Explorer search history...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\WordWheelQuery" /f >nul 2>&1
echo       Done.

echo.
echo [3/4] Clearing Recent Files (Quick Access)...
del /f /q "%APPDATA%\Microsoft\Windows\Recent\*.*" >nul 2>&1
del /f /q "%APPDATA%\Microsoft\Windows\Recent\AutomaticDestinations\*.*" >nul 2>&1
del /f /q "%APPDATA%\Microsoft\Windows\Recent\CustomDestinations\*.*" >nul 2>&1
echo       Done.

echo.
echo [4/4] Clearing Recent Files list in registry...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\RecentDocs" /f >nul 2>&1
echo       Done.

echo.
echo ============================================
echo   All done! Restarting Explorer...
echo ============================================
taskkill /f /im explorer.exe >nul 2>&1
start explorer.exe
echo.
echo Cleanup complete. Press any key to exit.
pause >nul

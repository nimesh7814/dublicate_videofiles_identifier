@echo off
setlocal enabledelayedexpansion

echo Flattening files in: %CD%
echo.

set "moved=0"
set "skipped=0"

for /r . %%F in (*) do (
    :: Skip files already in the current directory
    if /i not "%%~dpF" == "%CD%\" (
        set "dest=%CD%\%%~nxF"
        
        :: Handle filename conflicts by appending a counter
        if exist "!dest!" (
            set "counter=1"
            :loop
            set "dest=%CD%\%%~nF_!counter!%%~xF"
            if exist "!dest!" (
                set /a counter+=1
                goto loop
            )
            echo [RENAMED] %%~nxF -^> %%~nF_!counter!%%~xF
            set /a skipped+=1
        ) else (
            set /a moved+=1
        )
        
        move "%%F" "!dest!" >nul
    )
)

echo Done!
echo Files moved:   %moved%
echo Renamed (conflicts): %skipped%
echo.
pause

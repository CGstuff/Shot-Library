@echo off
setlocal EnableDelayedExpansion

REM Anchor to the script's own directory so dist/ and build/ always land
REM inside the repo, regardless of where build.bat was invoked from.
cd /d "%~dp0"

echo ============================================
echo Shot Library Build Script
echo ============================================
echo Building in: %CD%
echo.

REM Check if we're in the right directory
if not exist "build_spec.spec" (
    echo ERROR: build_spec.spec not found. Run from project root.
    exit /b 1
)

REM Clean old builds
echo Cleaning old builds...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"

REM ============================================
REM Version Detection from Git Tags
REM ============================================
echo.
echo Detecting version from git tags...

REM Get version from git
for /f "tokens=*" %%a in ('git describe --tags --abbrev^=0 2^>nul') do set GIT_VERSION=%%a

if not defined GIT_VERSION (
    echo WARNING: No git tag found, using default version 1.0.0
    set GIT_VERSION=v1.0.0
)

echo Found git version: %GIT_VERSION%

REM Remove 'v' prefix if present
set CLEAN_VERSION=%GIT_VERSION%
if "%CLEAN_VERSION:~0,1%"=="v" set CLEAN_VERSION=%CLEAN_VERSION:~1%
if "%CLEAN_VERSION:~0,1%"=="V" set CLEAN_VERSION=%CLEAN_VERSION:~1%

echo Clean version: %CLEAN_VERSION%

REM Parse version into components
for /f "tokens=1-3 delims=." %%a in ("%CLEAN_VERSION%") do (
    set MAJOR=%%a
    set MINOR=%%b
    set PATCH=%%c
)

REM Handle missing patch version
if not defined PATCH set PATCH=0

echo Version components: %MAJOR%.%MINOR%.%PATCH%

REM ============================================
REM Write version.txt for desktop app
REM ============================================
echo.
echo Writing version.txt for desktop app...
echo %CLEAN_VERSION%> shot_library\version.txt

REM ============================================
REM Inject version into Blender addon
REM ============================================
echo.
echo Injecting version into Blender addon...

REM Backup original __init__.py
copy /y "SL_blender_plugin\__init__.py" "SL_blender_plugin\__init__.py.bak" >nul

REM Use PowerShell to inject version
powershell -Command "(Get-Content 'SL_blender_plugin\__init__.py') -replace '\"version\": \(\d+, \d+, \d+\)', '\"version\": (%MAJOR%, %MINOR%, %PATCH%)' | Set-Content 'SL_blender_plugin\__init__.py'"

echo Addon version set to: (%MAJOR%, %MINOR%, %PATCH%)

REM ============================================
REM Run PyInstaller
REM ============================================
REM Pin to Python 3.10 via the `py` launcher to avoid picking up Anaconda's
REM Python 3.9 (which has PyQt5/PyQt6 ABI conflicts in this environment).
REM --distpath / --workpath pinned to the repo so output is never silently
REM redirected by stale env vars or unexpected CWD.
echo.
echo Running PyInstaller (Python 3.10)...
py -3.10 -m PyInstaller build_spec.spec --noconfirm --distpath "%~dp0dist" --workpath "%~dp0build"

if %ERRORLEVEL% neq 0 (
    echo.
    echo ERROR: PyInstaller failed!
    goto :restore
)

REM ============================================
REM Post-build setup
REM ============================================
echo.
echo Setting up output directory...

REM Create storage folder (optional - for portable mode)
if not exist "dist\ShotLibrary\storage" mkdir "dist\ShotLibrary\storage"

REM Copy any additional files if needed
REM copy /y "README.md" "dist\ShotLibrary\" >nul 2>&1

echo.
echo ============================================
echo Build Complete!
echo ============================================
echo.
echo Output: dist\ShotLibrary\ShotLibrary.exe
echo Version: %CLEAN_VERSION%
echo.

:restore
REM ============================================
REM Restore original addon __init__.py
REM ============================================
echo Restoring addon __init__.py to development version...
if exist "SL_blender_plugin\__init__.py.bak" (
    move /y "SL_blender_plugin\__init__.py.bak" "SL_blender_plugin\__init__.py" >nul
)

REM Clean up version.txt (optional - can leave for dev testing)
REM if exist "shot_library\version.txt" del "shot_library\version.txt"

endlocal

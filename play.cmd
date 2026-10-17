@echo off
rem Run the built game in a window, for playing rather than measuring.
rem   play.cmd [NAME=VALUE ...]     extra switches, e.g. play.cmd AUDIO_RATE=1
rem The log goes to scratch\play.out and scratch\play.err (both gitignored).
rem Double-click the target's exe in build\ to run without these log files.
rem Settings (resolution, antialiasing, vsync, controllers) are in
rem gt5p_settings.toml here, written on first start; a NAME=VALUE given
rem here wins over it, and deleting the file restores the defaults.
setlocal
cd /d "%~dp0"
set EXE=gt5p
if /I "%GT5P_TARGET%"=="BCUS98114" set EXE=gt5
if not defined GT5P_TARGET if exist input\target for /f "usebackq delims=" %%T in ("input\target") do if not defined GT5P_TARGET set GT5P_TARGET=%%T
if /I "%GT5P_TARGET%"=="BCUS98114" set EXE=gt5
if not exist build\%EXE%.exe (
    echo build\%EXE%.exe is missing. Build it first:
    echo     scripts\build.cmd -DGT5P_TARGET=BCUS98158
    pause
    exit /b 1
)
if not defined PS3_VERBOSE set PS3_VERBOSE=0
set PS3_HEADLESS=
:vars
if "%~1"=="" goto run
rem cmd splits NAME=VALUE into two arguments at the equals sign
set "%~1=%~2"
shift
shift
goto vars
:run
if not exist scratch mkdir scratch
echo Gran Turismo 5 Prologue - a controller works if one is plugged in (any kind, with SDL2.dll in build; Xbox ones without).
echo Keyboard: arrows = d-pad   Z = Cross   X = Circle   A = Square   S = Triangle
echo           Q / W = L1 / R1   1 / 2 = L2 / R2   Enter = Start   Tab = Select
echo The agreement: hold Down to its end, Right to "Accept", then Z.
echo Close the game window to stop.
build\%EXE%.exe > scratch\play.out 2> scratch\play.err
echo Exited with code %errorlevel%. Log: scratch\play.out, scratch\play.err
if not "%errorlevel%"=="0" pause

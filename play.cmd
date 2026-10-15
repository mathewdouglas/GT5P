@echo off
rem Run the built game in a window, for playing rather than measuring.
rem   play.cmd [NAME=VALUE ...]     extra switches, e.g. play.cmd AUDIO_RATE=1
rem The log goes to scratch\play.out and scratch\play.err (both gitignored).
rem Double-clicking build\gt5p.exe works too; this adds the log files.
rem Settings (resolution, antialiasing, vsync, controllers) are in
rem gt5p_settings.toml here, written on first start; a NAME=VALUE given
rem here wins over it, and deleting the file restores the defaults.
setlocal
cd /d "%~dp0"
if not exist build\gt5p.exe (
    echo build\gt5p.exe is missing. Build it first:
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
build\gt5p.exe > scratch\play.out 2> scratch\play.err
echo Exited with code %errorlevel%. Log: scratch\play.out, scratch\play.err
if not "%errorlevel%"=="0" pause

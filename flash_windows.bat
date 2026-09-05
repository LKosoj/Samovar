@echo off
setlocal EnableExtensions
chcp 65001 >nul

set "BOARD=devkit"
set "LITTLEFS=no"
set "PIO_ENV=Samovar"

:parse_args
if "%~1"=="" goto :args_ready
if /I "%~1"=="--help" goto :help
if /I "%~1"=="-h" goto :help
if /I "%~1"=="--board" (
  if "%~2"=="" goto :bad_args
  set "BOARD=%~2"
  shift
  shift
  goto :parse_args
)
if /I "%~1"=="--littlefs" (
  if "%~2"=="" goto :bad_args
  set "LITTLEFS=%~2"
  shift
  shift
  goto :parse_args
)
goto :bad_args

:args_ready
if /I "%PROCESSOR_ARCHITECTURE%"=="AMD64" goto :architecture_ready
if /I "%PROCESSOR_ARCHITEW6432%"=="AMD64" goto :architecture_ready
echo Ошибка: батник поддерживает только 64-разрядную Windows 10 или 11 на процессорах Intel/AMD.
exit /b 1

:architecture_ready
if /I "%BOARD%"=="devkit" (
  set "PIO_ENV=Samovar"
) else if /I "%BOARD%"=="s3" (
  set "PIO_ENV=Samovar_s3"
) else (
  echo Ошибка: неизвестная плата "%BOARD%".
  goto :bad_args
)

if /I not "%LITTLEFS%"=="yes" if /I not "%LITTLEFS%"=="no" (
  echo Ошибка: для --littlefs укажите yes или no.
  goto :bad_args
)

pushd "%~dp0" || (
  echo Ошибка: не удалось открыть папку проекта.
  goto :failed_without_project
)

echo Плата: %BOARD%
echo Окружение PlatformIO: %PIO_ENV%
echo Загружать LittleFS: %LITTLEFS%
echo.

call :find_pio
if not defined PIO_EXE (
  echo PlatformIO не найден. Начинается автоматическая установка.
  call :ensure_python || goto :failed
  call :install_platformio || goto :failed
  call :find_pio
  if not defined PIO_EXE (
    echo Ошибка: PlatformIO установлен, но исполняемый файл не найден.
    goto :failed
  )
) else (
  echo PlatformIO найден: "%PIO_EXE%"
)

echo.
echo [1/4] Компиляция прошивки...
"%PIO_EXE%" run -e "%PIO_ENV%"
if errorlevel 1 goto :failed

echo.
echo [2/4] Загрузка прошивки в плату...
"%PIO_EXE%" run -e "%PIO_ENV%" -t upload
if errorlevel 1 goto :failed

if /I "%LITTLEFS%"=="yes" (
  echo.
  echo [3/4] Загрузка файлов LittleFS...
  "%PIO_EXE%" run -e "%PIO_ENV%" -t uploadfs
  if errorlevel 1 goto :failed
) else (
  echo.
  echo [3/4] Загрузка LittleFS пропущена.
)

echo.
echo [4/4] Открытие монитора порта. Для выхода нажмите Ctrl+C.
"%PIO_EXE%" run -e "%PIO_ENV%" -t monitor
set "RESULT=%ERRORLEVEL%"
popd
exit /b %RESULT%

:find_pio
set "PIO_EXE="
if defined PLATFORMIO_CORE_DIR if exist "%PLATFORMIO_CORE_DIR%\penv\Scripts\pio.exe" set "PIO_EXE=%PLATFORMIO_CORE_DIR%\penv\Scripts\pio.exe"
if not defined PIO_EXE if exist "C:\.platformio\penv\Scripts\pio.exe" set "PIO_EXE=C:\.platformio\penv\Scripts\pio.exe"
if not defined PIO_EXE if exist "%USERPROFILE%\.platformio\penv\Scripts\pio.exe" set "PIO_EXE=%USERPROFILE%\.platformio\penv\Scripts\pio.exe"
if not defined PIO_EXE if exist "%USERPROFILE%\.platformio\penv\Scripts\platformio.exe" set "PIO_EXE=%USERPROFILE%\.platformio\penv\Scripts\platformio.exe"
if not defined PIO_EXE for /f "delims=" %%P in ('where pio.exe 2^>nul') do if not defined PIO_EXE set "PIO_EXE=%%P"
if not defined PIO_EXE for /f "delims=" %%P in ('where platformio.exe 2^>nul') do if not defined PIO_EXE set "PIO_EXE=%%P"
if defined PIO_EXE "%PIO_EXE%" --version >nul 2>&1
if errorlevel 1 set "PIO_EXE="
exit /b 0

:ensure_python
call :find_python
if defined PYTHON_EXE (
  echo Python найден: "%PYTHON_EXE%" %PYTHON_ARGS%
  exit /b 0
)

where winget.exe >nul 2>&1
if not errorlevel 1 (
  echo Python не найден. Установка Python через winget...
  winget install --id Python.Python.3.13 -e --scope user --silent --accept-package-agreements --accept-source-agreements
  if errorlevel 1 (
    echo Ошибка: winget не смог установить Python.
    exit /b 1
  )
) else (
  echo Python и winget не найдены. Скачивание Python с python.org...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.13.15/python-3.13.15-amd64.exe' -OutFile (Join-Path $env:TEMP 'samovar-python-3.13.15-amd64.exe')"
  if errorlevel 1 (
    echo Ошибка: не удалось скачать Python.
    exit /b 1
  )
  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$hash=(Get-FileHash (Join-Path $env:TEMP 'samovar-python-3.13.15-amd64.exe') -Algorithm SHA256).Hash; if ($hash -ne 'EDEC09C4853AEAE9AC36EFB8C9F95B6B8E2FEE65EEE56D9767A8B7C69C574403') { exit 1 }"
  if errorlevel 1 (
    echo Ошибка: контрольная сумма установщика Python не совпала.
    exit /b 1
  )
  start /wait "" "%TEMP%\samovar-python-3.13.15-amd64.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_test=0 Include_launcher=1 InstallLauncherAllUsers=0
  if errorlevel 1 (
    echo Ошибка: установщик Python завершился с ошибкой.
    exit /b 1
  )
)

call :find_python
if not defined PYTHON_EXE (
  echo Ошибка: Python установлен, но исполняемый файл не найден.
  exit /b 1
)
exit /b 0

:find_python
set "PYTHON_EXE="
set "PYTHON_ARGS="
py.exe -3 -c "import sys; raise SystemExit(sys.version_info < (3, 7))" >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_EXE=py.exe"
  set "PYTHON_ARGS=-3"
  exit /b 0
)
if exist "%LocalAppData%\Programs\Python\Python313\python.exe" (
  set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python313\python.exe"
  exit /b 0
)
for /f "delims=" %%P in ('where python.exe 2^>nul ^| findstr /I /V /C:"\Microsoft\WindowsApps\"') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
if defined PYTHON_EXE "%PYTHON_EXE%" -c "import sys; raise SystemExit(sys.version_info < (3, 7))" >nul 2>&1
if errorlevel 1 set "PYTHON_EXE="
exit /b 0

:install_platformio
echo Скачивание официального установщика PlatformIO...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/platformio/platformio-core-installer/master/get-platformio.py' -OutFile (Join-Path $env:TEMP 'samovar-get-platformio.py')"
if errorlevel 1 (
  echo Ошибка: не удалось скачать установщик PlatformIO.
  exit /b 1
)
"%PYTHON_EXE%" %PYTHON_ARGS% "%TEMP%\samovar-get-platformio.py"
if errorlevel 1 (
  echo Ошибка: PlatformIO не установился.
  exit /b 1
)
exit /b 0

:help
echo Использование:
echo   %~nx0 [--board devkit^|s3] [--littlefs yes^|no]
echo.
echo По умолчанию: --board devkit --littlefs no
exit /b 0

:bad_args
echo.
echo Использование:
echo   %~nx0 [--board devkit^|s3] [--littlefs yes^|no]
echo.
echo По умолчанию: --board devkit --littlefs no
exit /b 2

:failed
echo.
echo Операция остановлена из-за ошибки. Исправьте указанную выше причину и запустите батник снова.
popd
:failed_without_project
pause
exit /b 1

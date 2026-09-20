@echo off
rem Conciliacion de cobros - ejecutar con doble clic.
rem Toma el PDF y el Excel mas recientes de la carpeta datos\ y genera el
rem reporte en salida\, abriendolo al terminar.

cd /d "%~dp0"
chcp 65001 >nul

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo No se encontro el entorno de Python en .venv
    echo Ejecuta primero:  python -m venv .venv ^&^& .venv\Scripts\python -m pip install -e .
    echo.
    pause
    exit /b 1
)

echo.
echo ===========================================
echo   CONCILIACION DE COBROS - BDB LOGISTICA
echo ===========================================
echo.

.venv\Scripts\python.exe -m conciliador.cli conciliar %*
set CODIGO=%ERRORLEVEL%

echo.
if %CODIGO% NEQ 0 (
    echo Termino con errores. Revisa el mensaje de arriba.
) else (
    echo Listo. Abriendo el reporte...
    for /f "delims=" %%A in ('dir /b /o-d "salida\*.xlsx" 2^>nul') do (
        start "" "salida\%%A"
        goto :fin
    )
)

:fin
echo.
pause

@echo off
rem Builds dist\PDFLocal\PDFLocal.exe (no console window, tray icon to quit).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" python -m venv .venv
".venv\Scripts\python.exe" -m pip install -r requirements.txt -r requirements-build.txt || exit /b 1
".venv\Scripts\python.exe" -c "from launcher import make_icon_image; make_icon_image().save('build_icon.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])" || exit /b 1
".venv\Scripts\pyinstaller.exe" launcher.py --name PDFLocal --noconsole --onedir --noconfirm --clean ^
    --icon build_icon.ico --add-data "static;static" ^
    --collect-all pymupdf4llm --collect-all pymupdf_layout --collect-all pymupdf --collect-all pypdfium2 --collect-all pypdfium2_raw ^
    || exit /b 1
del build_icon.ico
rem build\ holds an intermediate PDFLocal.exe that cannot run on its own; remove it to avoid confusion.
rmdir /s /q build
echo.
echo Listo: dist\PDFLocal\PDFLocal.exe

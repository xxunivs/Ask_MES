@echo off

if not exist venv (
    echo [MES LLM API] Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo [MES LLM API] Installing packages...
pip install -r requirements.txt -q

echo.
echo [MES LLM API] Starting server on port 8001...
echo   Swagger UI : http://localhost:8001/docs
echo   Health     : http://localhost:8001/health
echo   Chat health: http://localhost:8001/chat/health
echo.
uvicorn main:app --host 0.0.0.0 --port 8001 --reload

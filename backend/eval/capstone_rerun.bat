@echo off
REM 캡스톤 발표 전 FULL 재벤치마크 (mes-llm-api 루트에서 실행)
cd /d %~dp0..
if not exist venv\Scripts\python.exe (
  echo venv 없음. README대로 가상환경을 먼저 만드세요.
  exit /b 1
)

set PY=venv\Scripts\python.exe
set FAILED_IDS=Q005,Q007,Q008,Q009,Q010,Q015,Q017,Q018,Q020,Q022,Q025,Q026,Q029,Q033,Q037,Q038,Q039,Q045,Q048,Q050

echo === [1/3] 과거 실패 20문항 빠른 확인 (약 30~60분) ===
%PY% eval\run_benchmark.py --preset FULL --execute --ids %FAILED_IDS%

echo.
echo === [2/3] FULL 50문항 전체 재실행 (약 2~3시간, Ollama+MES API 필요) ===
%PY% eval\run_benchmark.py --preset FULL --execute

echo.
echo === [3/3] 최신 결과 집계 ===
for /f %%f in ('dir /b /od eval\results\run_FULL_*.csv 2^>nul') do set LAST=%%f
%PY% eval\score.py eval\results\%LAST%
%PY% eval\score.py eval\results\%LAST% --by difficulty

echo.
echo 완료. PPT 수치는 eval\results\%LAST% 기준 EX_exec %% 를 사용하세요.
pause

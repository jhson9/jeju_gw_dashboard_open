@echo off
REM ==========================================================================
REM  scheduler_jeju_dashboard.bat  (2026-06-01)
REM
REM  Windows 작업 스케줄러용 — ASOS + 지하수위 야간 자동 수집.
REM
REM  【등록 방법】
REM    1. Windows 키 → "작업 스케줄러" 검색 → 실행
REM    2. 우측 패널 "작업 만들기" 클릭
REM    3. 일반 탭:
REM       - 이름: 제주 대시보드 야간 수집
REM       - "사용자가 로그온할 때만 실행" / "가장 높은 수준의 권한으로 실행" 체크
REM       - 구성 대상: Windows 10/11
REM    4. 트리거 탭 → 새로 만들기:
REM       - 일일, 시작 시간 02:30
REM       - 추가 설정: "최대 1시간 임의 지연" 체크 (검증 5팀 jitter 권고 충족)
REM    5. 동작 탭 → 새로 만들기:
REM       - 동작: 프로그램 시작
REM       - 프로그램/스크립트:  cmd.exe
REM       - 인수 추가:        /c "C:\COWORK_SPACE\jeju_groundwater_dashboard\scripts\scheduler_jeju_dashboard.bat"
REM       - 시작 위치:        C:\COWORK_SPACE\jeju_groundwater_dashboard
REM    6. 조건 탭:
REM       - "AC 전원에서만 실행" 권장 (노트북 배터리 보호)
REM       - "네트워크 연결 가능 시작" 체크
REM    7. 설정 탭:
REM       - "작업이 1시간 이상 실행되면 중지" 체크
REM       - "예약된 시작 시간 놓치면 가능한 빨리 시작" 체크
REM
REM  【로그】
REM    매 실행마다 logs/scheduler_YYYY-MM-DD.log 에 표준출력/오류 기록.
REM    수동 점검은 그 파일을 열어 확인하세요.
REM
REM  【수집 모드】
REM    ASOS:    smart 모드 — M-2·M-1·M 분석 기간만 (기상청 트래픽 보호)
REM    GWlevel: day + month 양쪽 — 부족분만 (증분)
REM
REM  【주의】
REM    이 파일은 ASCII-only 로 유지하세요. 한글 echo 는 cmd CP949 에서 깨집니다.
REM    한글 로그는 Python collector 가 직접 UTF-8 로 파일에 씁니다.
REM ==========================================================================

setlocal enableextensions
chcp 65001 >nul 2>nul

REM ---- 프로젝트 루트로 이동 ----
cd /d "%~dp0\.."
if errorlevel 1 (
    echo [FATAL] cd failed
    exit /b 1
)

REM ---- 로그 폴더 보장 ----
if not exist "logs" mkdir "logs"

REM ---- 로그 파일명 (YYYY-MM-DD) ----
for /f "tokens=2 delims==" %%a in ('wmic os get localdatetime /value ^| find "="') do set DT=%%a
set LOG=logs\scheduler_%DT:~0,4%-%DT:~4,2%-%DT:~6,2%.log

echo. >> "%LOG%"
echo ======================================================================= >> "%LOG%"
echo  Scheduled run started at %DATE% %TIME% >> "%LOG%"
echo ======================================================================= >> "%LOG%"

REM ---- Python 찾기 (py launcher → python 순) ----
set PY_CMD=
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys" >nul 2>nul
    if not errorlevel 1 set PY_CMD=py -3
)
if "%PY_CMD%"=="" (
    where python >nul 2>nul
    if not errorlevel 1 (
        python -c "import sys" >nul 2>nul
        if not errorlevel 1 set PY_CMD=python
    )
)
if "%PY_CMD%"=="" (
    echo [FATAL] Python not found >> "%LOG%"
    exit /b 1
)
echo Python launcher: %PY_CMD% >> "%LOG%"

REM ==========================================================================
REM  1) ASOS 자동 수집 (smart 모드)
REM ==========================================================================
echo. >> "%LOG%"
echo --- ASOS collector --- >> "%LOG%"
%PY_CMD% src\collectors\asos_collector.py --mode smart >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [WARN] ASOS collector exit=%errorlevel% >> "%LOG%"
)

REM ==========================================================================
REM  2) 지하수위 일평균 자동 수집
REM ==========================================================================
echo. >> "%LOG%"
echo --- GWlevel collector (day) --- >> "%LOG%"
%PY_CMD% src\collectors\jeju_gwlevel_collector.py --granularity day >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [WARN] GWlevel day collector exit=%errorlevel% >> "%LOG%"
)

REM ==========================================================================
REM  3) 지하수위 월평균 자동 수집
REM ==========================================================================
echo. >> "%LOG%"
echo --- GWlevel collector (month) --- >> "%LOG%"
%PY_CMD% src\collectors\jeju_gwlevel_collector.py --granularity month >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [WARN] GWlevel month collector exit=%errorlevel% >> "%LOG%"
)

echo. >> "%LOG%"
echo ======================================================================= >> "%LOG%"
echo  Scheduled run finished at %DATE% %TIME% >> "%LOG%"
echo ======================================================================= >> "%LOG%"

REM 정상 종료 (개별 collector 실패해도 다음 날 재시도되도록 0 반환)
endlocal
exit /b 0

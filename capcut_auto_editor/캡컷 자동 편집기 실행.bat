@echo off
chcp 949 > nul
title 캡컷 자동 편집기
cd /d "%~dp0"

echo ====================================================
echo   캡컷 자동 편집기
echo ====================================================
echo.

rem 파이썬 찾기 (py 런처 우선, 없으면 python)
set PYEXE=
where py >nul 2>nul && set PYEXE=py -3
if "%PYEXE%"=="" (
    where python >nul 2>nul && set PYEXE=python
)

if "%PYEXE%"=="" (
    echo [오류] 파이썬을 찾을 수 없습니다.
    echo        https://www.python.org/downloads/ 에서 설치할 때
    echo        "Add Python to PATH" 를 꼭 체크해 주세요.
    echo.
    pause
    exit /b 1
)

rem 처음 실행이면 필요한 패키지를 깔아 준다
%PYEXE% -c "import fastapi, uvicorn, pycapcut" >nul 2>nul
if errorlevel 1 (
    echo 필요한 패키지를 설치합니다. 처음 한 번만 조금 걸립니다...
    echo.
    %PYEXE% -m pip install --upgrade pip
    %PYEXE% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [오류] 패키지 설치에 실패했습니다. 인터넷 연결을 확인해 주세요.
        pause
        exit /b 1
    )
    echo.
)

echo 서버를 시작합니다. 잠시 뒤 브라우저가 열립니다.
echo 끝내려면 이 창을 닫거나 Ctrl+C 를 누르세요.
echo.

%PYEXE% run.py

echo.
echo 프로그램이 종료되었습니다.
pause

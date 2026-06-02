#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
launch_dashboard.py — 제주 농업용 지하수 대시보드 런처 (2026-05-29 SSOT).

이전엔 Run_JejuDashboard.bat 가 PowerShell 멀티라인 명령으로 포트 탐색을 했으나,
CP65001/escape/한글 환경에서 silent 실패 → 콘솔 즉시 닫힘으로 디버깅 불가.
본 launcher 는 모든 로직을 Python 으로 옮겨:

  1. config.PORT_CANDIDATES 의 첫 free port 자동 탐색 (socket.bind 시도)
  2. streamlit subprocess 실행 (--server.port 명시)
  3. 별도 스레드로 브라우저 자동 열기 (Edge → Chrome → 기본 브라우저)
  4. 모든 예외를 stderr 에 명시 출력 + traceback
  5. Ctrl+C / Quit 버튼 시 streamlit 깨끗하게 종료

사용법:
    python launch_dashboard.py            # 기본 — config.STREAMLIT_PORT
    python launch_dashboard.py --port 9999  # 강제 지정
    python launch_dashboard.py --no-browser # 브라우저 자동 열기 안 함

의존성: stdlib 만 사용 (subprocess, socket, threading, webbrowser).
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path


HERE = Path(__file__).resolve().parent


def find_free_port(candidates: list[int]) -> int | None:
    """후보 중 socket.bind 가능한 첫 포트 반환. 모두 실패 시 None.

    로직2팀 fix (2026-05-29): OverflowError 추가 캐치 — `--port 99999` 같은
    유효 범위 외 값 입력 시 socket.bind 가 OverflowError raise. 미캐치 시
    launcher 전체 크래시.
    """
    for port in candidates:
        # 1-65535 범위 사전 검증 (port 0 은 OS 임의할당 의미라 의도 모호 → 거부)
        if not isinstance(port, int) or not (1 <= port <= 65535):
            print(f"  ✗ port {port}: 1~65535 범위 외", file=sys.stderr)
            continue
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", port))
            return port
        except (OSError, PermissionError, OverflowError) as e:
            print(f"  ✗ port {port}: {e}", file=sys.stderr)
            continue
    return None


def open_browser_app_mode(url: str, delay_sec: float = 4.0) -> None:
    """Edge → Chrome → 기본 브라우저 순으로 --app 모드 시도."""
    time.sleep(delay_sec)  # streamlit 부팅 대기
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for browser_path in edge_paths + chrome_paths:
        if Path(browser_path).exists():
            try:
                subprocess.Popen([browser_path, f"--app={url}"])
                print(f"  ✓ 브라우저 시작: {Path(browser_path).name} --app={url}")
                return
            except Exception as e:
                print(f"  ⚠ {Path(browser_path).name} 실행 실패: {e}", file=sys.stderr)
                continue
    # 마지막 폴백: 기본 브라우저 (--app 미지원, 일반 탭)
    try:
        webbrowser.open(url)
        print(f"  ✓ 기본 브라우저 (탭 모드): {url}")
    except Exception as e:
        print(f"  ⚠ 기본 브라우저 실행 실패: {e}", file=sys.stderr)
        print(f"  → 수동으로 열어주세요: {url}")


def _auto_collect_if_stale() -> None:
    """🆕 2026-06-01 v2: 부팅 시 ASOS + GWlevel(일/월) 신선도 확인 → 오래된 것만 자동 수집.

    동작:
      1. 세 가지 데이터 소스의 마지막 일자를 각각 읽어 어제와 비교:
         · ASOS 기상       (>3일 차이면 수집)
         · GWlevel 일자료  (>3일 차이면 수집, JW연동 csv 기준)
         · GWlevel 월자료  (>35일 차이면 수집, JW연동 csv 기준)
      2. 셋 다 최신이면 한 줄만 출력하고 통과.
      3. 갱신 필요하면 어떤 소스인지 출력 후 순차 수집.
      4. 어떤 예외든 잡아서 경고만 출력 — 대시보드 부팅은 막지 않음.

    설계 메모:
      - 사용자가 상시 켜놓는 대시보드 아니므로 야간 스케줄러보다 부팅 시 자동
        수집이 더 자연스러움 (검증 5팀 권고와 약간 다르지만 실제 사용 패턴 우선).
      - GWlevel JW연동 1개 파일로 대표 신선도 판단 — 177개 다 읽으면 부팅 지연.
      - KMA_API_KEY 미설정·인터넷 없음 등은 collector 내부에서 처리되므로 본
        함수는 try/except 만 광범위하게.
    """
    try:
        from datetime import date, timedelta
        import pandas as pd
        from src.collectors import asos_collector, jeju_gwlevel_collector
        import config
    except Exception as e:
        print(f"  ⚠ collector import 실패 — 자동 수집 건너뜀: {e}")
        return

    today = date.today()
    yesterday = today - timedelta(days=1)

    def _last_date_in_csv(path, col):
        try:
            if not path.exists():
                return None
            df = pd.read_csv(path, encoding="utf-8-sig", usecols=[col])
            return pd.to_datetime(df[col], errors="coerce").max().date()
        except Exception:
            return None

    # 1) 신선도 확인
    asos_last = _last_date_in_csv(asos_collector.get_output_csv_path(), "일시")
    gw_day_last   = _last_date_in_csv(
        config.GW_STATION_DAY_DIR / "JW연동.csv", "날짜"
    )
    gw_month_last = _last_date_in_csv(
        config.GW_STATION_MONTH_DIR / "JW연동.csv", "날짜"
    )

    def _days_stale(d):
        if d is None:
            return None
        return (today - d).days

    asos_stale     = _days_stale(asos_last)
    gw_day_stale   = _days_stale(gw_day_last)
    gw_month_stale = _days_stale(gw_month_last)

    need_asos     = (asos_stale is None) or (asos_stale > 3)
    need_gw_day   = (gw_day_stale is None) or (gw_day_stale > 3)
    need_gw_month = (gw_month_stale is None) or (gw_month_stale > 35)

    # 상태 한 줄 요약
    def _fmt(d, stale, need):
        if d is None:
            return "없음"
        flag = "🔄" if need else "✓"
        return f"{d} ({stale}일 전) {flag}"

    print(f"  · ASOS:        {_fmt(asos_last, asos_stale, need_asos)}")
    print(f"  · GWlevel 일:  {_fmt(gw_day_last, gw_day_stale, need_gw_day)}")
    print(f"  · GWlevel 월:  {_fmt(gw_month_last, gw_month_stale, need_gw_month)}")

    if not (need_asos or need_gw_day or need_gw_month):
        print(f"  ✓ 모든 데이터 최신 — 수집 생략 (바로 대시보드 시작)")
        return

    print(f"")
    needs = [n for n, f in
             [("ASOS", need_asos), ("GWlevel 일", need_gw_day), ("GWlevel 월", need_gw_month)]
             if f]
    print(f"  📅 갱신 필요: {', '.join(needs)} — 부족분만 자동 수집 시작...")
    print(f"     (네트워크 문제 시 경고만 출력, 대시보드는 계속 띄웁니다)")

    # 2) 순차 수집 — 각각 try/except
    if need_asos:
        print(f"\n  [ASOS] smart 모드로 수집 중...")
        try:
            asos_collector.collect_asos_data(mode="smart")
            print(f"  ✓ ASOS 완료")
        except KeyboardInterrupt:
            print(f"  ⚠ ASOS 사용자 중단")
            return
        except Exception as e:
            print(f"  ⚠ ASOS 실패 ({type(e).__name__}: {e}) — 기존 CSV 유지")

    if need_gw_day:
        print(f"\n  [GWlevel 일] 177개소 부족분 수집 중...")
        try:
            jeju_gwlevel_collector.collect_all(granularity="day", force=False)
            print(f"  ✓ GWlevel 일 완료")
        except KeyboardInterrupt:
            print(f"  ⚠ GWlevel 일 사용자 중단")
            return
        except Exception as e:
            print(f"  ⚠ GWlevel 일 실패 ({type(e).__name__}: {e}) — 기존 CSV 유지")

    if need_gw_month:
        print(f"\n  [GWlevel 월] 177개소 부족분 수집 중...")
        try:
            jeju_gwlevel_collector.collect_all(granularity="month", force=False)
            print(f"  ✓ GWlevel 월 완료")
        except KeyboardInterrupt:
            print(f"  ⚠ GWlevel 월 사용자 중단")
            return
        except Exception as e:
            print(f"  ⚠ GWlevel 월 실패 ({type(e).__name__}: {e}) — 기존 CSV 유지")

    print(f"\n  ✅ 자동 수집 단계 완료 — 대시보드로 이동합니다.")


def main() -> int:
    parser = argparse.ArgumentParser(description="제주 지하수 대시보드 런처")
    parser.add_argument("--port", type=int, default=None,
                        help="강제 포트 지정 (config 무시)")
    parser.add_argument("--no-browser", action="store_true",
                        help="브라우저 자동 열기 안 함")
    args = parser.parse_args()

    print("=" * 60)
    print(" 제주 농업용 지하수 분석 대시보드 — Launcher")
    print("=" * 60)
    print()

    # 1. config 로드
    sys.path.insert(0, str(HERE))
    try:
        import config
        candidates = list(config.PORT_CANDIDATES)
        print(f"[1/3] config.PORT_CANDIDATES: {candidates}")
    except Exception as e:
        print(f"  ⚠ config 로드 실패: {e}")
        candidates = [18501, 18502, 28501, 38501, 49001]
        print(f"       폴백 후보: {candidates}")

    if args.port is not None:
        candidates = [args.port] + [p for p in candidates if p != args.port]
        print(f"       --port {args.port} 우선 적용")

    # 2. 사용 가능 포트 탐색
    print()
    print("[2/3] 사용 가능 포트 탐색 (socket.bind 시도)...")
    port = find_free_port(candidates)
    if port is None:
        print()
        print("[!] 모든 후보 포트가 차단되어 있습니다.")
        print("    PowerShell (관리자) 에서 예약 포트 범위 확인:")
        print("        netsh interface ipv4 show excludedportrange protocol=tcp")
        print("    그 결과의 어느 범위에도 포함되지 않는 포트를 골라:")
        print("        1) config.py 의 PORT_CANDIDATES 첫 자리에 추가, 또는")
        print("        2) python launch_dashboard.py --port <포트> 로 직접 지정")
        return 1
    print(f"  ✓ 선택된 포트: {port}")

    # 2.5. 🆕 (2026-06-01) 데이터 신선도 확인 + 자동 수집
    # 세 가지 데이터 소스의 마지막 일자를 확인:
    #   · ASOS 기상       (3일 이상 오래되면 ASOS smart 수집)
    #   · GWlevel 일자료  (3일 이상 오래되면 day 수집)
    #   · GWlevel 월자료  (35일 이상 오래되면 month 수집)
    # 모두 최신이면 스킵. 실패/오프라인 시 경고만 출력하고 대시보드 계속 띄움.
    print()
    print("[2.5/3] 데이터 신선도 확인...")
    _auto_collect_if_stale()

    # 3. streamlit 사전 검증 (오류4팀 fix 2026-05-29)
    # sys.executable 이 Microsoft Store stub 인 경우 silent 실패 차단.
    if "WindowsApps" in sys.executable:
        print("[!] sys.executable 이 Microsoft Store stub 경로입니다:")
        print(f"    {sys.executable}")
        print("    실제 Python 을 https://python.org 에서 설치 후 재시도.")
        print("    또는 Settings > Apps > Advanced > App execution aliases 에서")
        print("    python.exe / python3.exe 끄기.")
        return 1
    # streamlit 모듈 사전 import 검증 — 미설치 시 명확한 안내
    import importlib.util
    if importlib.util.find_spec("streamlit") is None:
        print("[!] streamlit 모듈이 설치되어 있지 않습니다.")
        print(f"    설치: {sys.executable} -m pip install streamlit")
        print(f"    또는: {sys.executable} -m pip install -r requirements.txt")
        return 1

    # 4. streamlit subprocess 실행
    print()
    print(f"[3/3] streamlit 시작 (port {port})...")
    print(f"      대시보드 URL: http://localhost:{port}")
    print()

    env = os.environ.copy()
    env["JEJU_PORT"] = str(port)   # 다른 헬퍼가 참조 가능

    # 백그라운드 브라우저 열기
    if not args.no_browser:
        threading.Thread(
            target=open_browser_app_mode,
            args=(f"http://localhost:{port}",),
            daemon=True,
        ).start()

    # streamlit 실행 (포그라운드 — Ctrl+C 까지 블록)
    streamlit_args = [
        sys.executable, "-m", "streamlit", "run",
        str(HERE / "src" / "dashboard" / "app.py"),
        "--server.port", str(port),
        "--server.headless", "true",
    ]
    try:
        result = subprocess.run(streamlit_args, env=env, cwd=str(HERE))
        return result.returncode
    except KeyboardInterrupt:
        print("\n[Ctrl+C] 사용자 중단 — streamlit 종료.")
        return 0
    except FileNotFoundError as e:
        print(f"\n[!] streamlit 실행 파일을 찾을 수 없습니다: {e}", file=sys.stderr)
        print(f"    설치: {sys.executable} -m pip install streamlit", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"\n[!] streamlit 실행 실패: {type(e).__name__}: {e}", file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    try:
        rc = main()
    except Exception:
        print("\n[!] 예상치 못한 launcher 오류:", file=sys.stderr)
        traceback.print_exc()
        rc = 1
    if rc != 0:
        # 콘솔 즉시 닫힘 방지 — bat 의 pause 가 미작동하는 경우 대비.
        try:
            input("\n오류가 발생했습니다. Enter 를 눌러 닫기...")
        except (EOFError, KeyboardInterrupt):
            pass
    sys.exit(rc)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
desktop_app.py — 네이티브 창(pywebview)으로 대시보드를 띄워
작업표시줄 아이콘을 "항상" 제주도 섬(Jeju_dashboard_island.ico)으로 표시한다.

배경:
  Edge --app 방식은 작업표시줄 버튼이 Edge 의 앱ID/아이콘을 쓰도록
  Windows 가 강제하여, 명령줄로는 작업표시줄 아이콘을 바꿀 수 없다.
  → 자체(네이티브) 창으로 호스팅하면 그 창의 작업표시줄 아이콘을
    우리가 직접 지정할 수 있다 (AppUserModelID + WM_SETICON).

안전장치:
  pywebview 미설치/설치실패/창 생성 실패 시 → 기존 Edge 런처로 자동 폴백
  하므로, 어떤 경우에도 대시보드는 열린다.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

ICON_PATH = HERE / "Jeju_dashboard_island.ico"
APP_TITLE = "JeJu 농업용 지하수 관리·분석"
AUMID = "Jeju.Groundwater.Dashboard"   # 작업표시줄 그룹 식별자


def _fallback_edge() -> int:
    """네이티브 창 불가 시 기존 Edge --app 런처로 폴백."""
    print("[i] 네이티브 창을 쓸 수 없어 Edge 모드로 실행합니다.")
    import launch_dashboard
    return launch_dashboard.main()


def _wait_port(port: int, timeout_sec: float = 90.0) -> bool:
    """streamlit 서버가 응답할 때까지 대기."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def _set_taskbar_icon() -> None:
    """창이 뜬 뒤 hwnd 를 찾아 WM_SETICON 으로 물방울 아이콘 적용 (Windows)."""
    if os.name != "nt" or not ICON_PATH.exists():
        return
    try:
        import ctypes
        u = ctypes.windll.user32
        WM_SETICON = 0x0080
        ICON_SMALL, ICON_BIG = 0, 1
        IMAGE_ICON, LR_LOADFROMFILE = 1, 0x0010
        for _ in range(120):  # 최대 ~60초 대기
            hwnd = u.FindWindowW(None, APP_TITLE)
            if hwnd:
                for size, which in ((16, ICON_SMALL), (32, ICON_BIG)):
                    h = u.LoadImageW(None, str(ICON_PATH), IMAGE_ICON,
                                     size, size, LR_LOADFROMFILE)
                    if h:
                        u.SendMessageW(hwnd, WM_SETICON, which, h)
                return
            time.sleep(0.5)
    except Exception:
        pass  # 아이콘 실패는 치명적이지 않음


def main() -> int:
    # 작업표시줄에서 python 과 분리 + 자체 그룹 (아이콘 제어 전제)
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(AUMID)
        except Exception:
            pass

    # pywebview 확보 (없으면 1회 자동 설치 시도 → 그래도 없으면 Edge 폴백)
    try:
        import webview  # noqa: F401
    except Exception:
        print("[i] pywebview 설치 시도 중... (최초 1회)")
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "pywebview"],
                check=False,
            )
            import webview  # noqa: F811
        except Exception:
            return _fallback_edge()

    import config
    import launch_dashboard as L

    port = L.find_free_port(config.PORT_CANDIDATES)
    if not port:
        return _fallback_edge()

    print("[2.5/3] 데이터 신선도 확인...")
    try:
        L._auto_collect_if_stale()
    except Exception as e:
        print(f"  (신선도 확인 건너뜀: {e})")

    print(f"[3/3] streamlit 시작 (port {port}) — 네이티브 창 모드")
    env = os.environ.copy()
    env["JEJU_PORT"] = str(port)
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run",
         str(HERE / "src" / "dashboard" / "app.py"),
         "--server.port", str(port), "--server.headless", "true",
         # 🆕 (2026-06-08) static 서빙 명시 — cwd/config 위치 무관 보장.
         # 지도 타일(/app/static/map_tiles/...) 404 방지.
         "--server.enableStaticServing", "true"],
        env=env, cwd=str(HERE),
    )

    if not _wait_port(port):
        print("[!] streamlit 시작 실패 — 종료")
        try:
            proc.terminate()
        except Exception:
            pass
        return 1

    threading.Thread(target=_set_taskbar_icon, daemon=True).start()

    import webview
    try:
        webview.create_window(
            APP_TITLE, f"http://localhost:{port}",
            width=1480, height=920,
            # 🛡️ (2026-06-11 사용자 보고) pywebview 는 기본적으로 텍스트
            # 선택을 막는다(text_select=False) — 표·숫자 복사가 안 되던 원인.
            # Edge 폴백 모드에서는 선택이 됐던 이유도 이것.
            text_select=True,
        )
        webview.start()   # 메인 스레드 블록 — 창 닫힐 때까지
    except Exception as e:
        print(f"[!] 네이티브 창 생성 실패 ({e}) — Edge 로 폴백")
        threading.Thread(
            target=L.open_browser_app_mode,
            args=(f"http://localhost:{port}",),
            daemon=True,
        ).start()
        try:
            proc.wait()
        except KeyboardInterrupt:
            pass
        return 0
    finally:
        try:
            proc.terminate()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())

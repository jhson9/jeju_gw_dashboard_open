# ==============================================================================
#  파일명: src/dashboard/pdf_server.py
#  관정 자료 PDF 정적 서버 (streamlit 옆 데몬 스레드).
# ------------------------------------------------------------------------------
#  목적:
#    streamlit 의 `/app/static/` 정적 서빙은 1GB hard limit (bootstrap.py:35)
#    가 있어 well_card 1.3GB 같은 대용량 PDF 를 두면 static serving 전체가
#    자동 비활성화된다. 본 모듈은 별도 포트(8766) 에서 localhost 만 listen 하는
#    가벼운 정적 서버를 띄워 streamlit 의 한계와 완전히 분리한다.
#
#  URL 매핑 (PdfDataSource dataclass 기반 plug-in 형):
#    http://localhost:8766/pdfs/well_card/{year}/{filename}    →  data_well_card/{year}/{filename}
#    http://localhost:8766/pdfs/drilling_log/{filename}        →  data_drilling_log/{filename}
#    (미래) http://localhost:8766/pdfs/{name}/{...}            →  data_{name}/{...}
#
#  확장 방법:
#    1) DATA_SOURCES 딕셔너리에 PdfDataSource(...) 한 줄 추가
#    2) well_card_pdf.py 에 그 source 용 discover/render 헬퍼 작성
#    → 별도 hook 또는 streamlit 재시작 불필요
#
#  보안:
#    - 127.0.0.1 만 listen (LAN/외부 접근 차단)
#    - 화이트리스트 URL prefix 만 허용 (다른 경로 = 403)
#    - Path traversal: `os.path.commonpath` 검사 + symlink/junction reject
#                      + DENY 토큰(`..`, `\\`, `:`, `\x00`) reject
#    - 허용 확장자: PdfDataSource.allowed_ext 만
#    - URL 디코딩 strict (잘못된 byte → 400)
#
#  안정성:
#    - SO_REUSEADDR 로 streamlit 재시작 시 TIME_WAIT 회피
#    - 모듈 레벨 `_server` global + threading.Lock 으로 hot-reload 중복 시작 차단
#    - port 이미 사용 중이면 `__ping__` 으로 우리 서버 인지 검증 후 graceful skip
#    - atexit 에 shutdown 등록
#    - log_message 침묵 (streamlit 콘솔 노이즈 방지)
#
#  운영 모니터링 (사용자 강조 사항 — 1GB 한계 재발 방지):
#    - 시작 시 `src/dashboard/static/` 사이즈 측정 → 800MB 초과면 stderr warning
#    - 1GB 초과 시점에서 streamlit 자체가 static 서빙 비활성화하므로 사전 경고
# ==============================================================================
from __future__ import annotations

import atexit
import logging
import os
import socket
import sys
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_logger = logging.getLogger(__name__)

# ── 설정 상수 ────────────────────────────────────────────────────────────────
PDF_SERVER_HOST = "127.0.0.1"
# 23차: Windows WinError 10013 (Hyper-V/WSL 동적 예약) 대응 PORT_CANDIDATES
PDF_SERVER_PORT_CANDIDATES: tuple[int, ...] = (8766, 18766, 28766, 38766, 49766)
PDF_SERVER_PORT = PDF_SERVER_PORT_CANDIDATES[0]   # 기본 8766, _select_port()로 동적 변경
PDF_SERVER_URL_BASE = f"http://{PDF_SERVER_HOST}:{PDF_SERVER_PORT}"

# streamlit static 폴더 사이즈 모니터 임계치 (1GB hard limit 사전 경고)
STATIC_FOLDER_WARN_BYTES = 800 * 1024 * 1024   # 800 MB

PROJECT_ROOT = Path(__file__).resolve().parents[2]
import config
STREAMLIT_STATIC_DIR = PROJECT_ROOT / "src" / "dashboard" / "static"


@dataclass(frozen=True)
class PdfDataSource:
    """미래 자료 종류 확장을 위한 plug-in 단위.

    - name        : URL prefix 구성 (예: "well_card" → "/pdfs/well_card/")
    - data_root   : 디스크 폴더 (예: PROJECT_ROOT / "data_well_card")
    - allowed_ext : 허용 확장자 (소문자, 점 포함; 기본 (".pdf",))
    - label       : UI 표시용 라벨 (선택)
    """
    name: str
    data_root: Path
    allowed_ext: tuple[str, ...] = (".pdf",)
    label: str = ""

    @property
    def url_prefix(self) -> str:
        return f"/pdfs/{self.name}/"

    @property
    def url_base(self) -> str:
        return f"{PDF_SERVER_URL_BASE}{self.url_prefix}".rstrip("/")


# ── 등록된 자료 소스 (미래 확장 시 여기에 추가) ────────────────────────────
DATA_SOURCES: dict[str, PdfDataSource] = {
    "well_card": PdfDataSource(
        name="well_card",
        data_root=config.WELL_CARD_DIR,
        allowed_ext=(".pdf",),
        label="관정카드",
    ),
    "drilling_log": PdfDataSource(
        name="drilling_log",
        data_root=config.DRILLING_LOG_DIR,
        allowed_ext=(".pdf",),
        label="시추 주상도",
    ),
    # ── 드론 영상 (Build 2.0, 2026-05-23) — tab31 ──────────────────────────
    # DJI Terra 산출물: 정사사진 다운샘플 PNG, 3D Tiles tileset.json + b3dm,
    # DSM(GeoTIFF — 직접 서빙은 안 하지만 미래 확장 대비), PLY 포인트클라우드.
    # data_drone/ 폴더 안 한글 미션명도 URL quote 로 안전 전달.
    "drone": PdfDataSource(
        name="drone",
        data_root=config.DRONE_DATA_ROOT,
        allowed_ext=(".png", ".jpg", ".json", ".b3dm", ".ply"),
        label="드론 자료",
    ),
    # ── CesiumJS 라이브러리 번들 (Build 2.0, 2026-05-23 추가) — tab33 ──
    # Streamlit 의 AppStaticFileHandler 가 .js/.css 를 강제로 text/plain 으로
    # 응답하여 브라우저 strict MIME 검사가 JS 실행 거부 → "Cesium is not defined"
    # → 검은 화면. Streamlit 의 의도적 보안 화이트리스트라 우회 어려움.
    # pdf_server 는 우리가 직접 만든 핸들러라 MIME 을 정확히 제어 가능 — 여기로
    # 우회 서빙. 번들 파일은 그대로 src/dashboard/static/libs/cesium/ 위치 유지
    # (1GB 한도 모니터 [[project-drone-cesium-bundle-path]] 정책 유지).
    "cesium_lib": PdfDataSource(
        name="cesium_lib",
        data_root=PROJECT_ROOT / "src" / "dashboard" / "static" / "libs" / "cesium",
        # Cesium 번들 안의 모든 정적 자원 확장자.
        allowed_ext=(
            ".js", ".css", ".wasm",
            ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
            ".json", ".xml", ".txt",
            ".glb", ".gltf", ".bin",
            ".ktx2", ".ktx", ".crn",
            ".woff", ".woff2", ".ttf", ".otf",
        ),
        label="CesiumJS",
    ),
    # ── 드론 3D 뷰어 HTML 페이지 (Build 2.1, 2026-05-24 추가) — tab33 ──
    # CesiumJS 뷰어 HTML 을 cesium_lib·drone 과 "같은 origin(8766)" 에서 서빙해
    # srcdoc/cross-origin worker 문제를 원천 제거(Draco worker 정상화).
    # 정적 HTML 1장(viewer3d.html)만 두고, 미션별 파라미터는 URL hash 로 전달.
    # 메모리 [[project-drone-purpose]] — 드론 시설물 관리·시계열 변화 감지용.
    "drone_viewer": PdfDataSource(
        name="drone_viewer",
        data_root=PROJECT_ROOT / "src" / "dashboard" / "static" / "drone_viewer",
        allowed_ext=(".html", ".js", ".css"),
        label="드론 3D 뷰어",
    ),
    # 향후 추가 예: PROJECT_ROOT / "data_water_quality_report" 등
}


# 확장자 → Content-Type 매핑 (DATA_SOURCES 의 allowed_ext 와 정합)
_CONTENT_TYPES: dict[str, str] = {
    ".pdf":   "application/pdf",
    ".png":   "image/png",
    ".jpg":   "image/jpeg",
    ".jpeg":  "image/jpeg",
    ".gif":   "image/gif",
    ".webp":  "image/webp",
    ".svg":   "image/svg+xml",
    ".json":  "application/json",
    ".xml":   "application/xml",
    ".txt":   "text/plain; charset=utf-8",
    ".html":  "text/html; charset=utf-8",   # drone_viewer/viewer3d.html
    # CesiumJS (cesium_lib 소스용) — strict MIME 검사 통과 필수.
    ".js":    "application/javascript",
    ".css":   "text/css",
    ".wasm":  "application/wasm",
    # 폰트
    ".woff":  "font/woff",
    ".woff2": "font/woff2",
    ".ttf":   "font/ttf",
    ".otf":   "font/otf",
    # 3D/binary
    ".glb":   "model/gltf-binary",
    ".gltf":  "model/gltf+json",
    ".bin":   "application/octet-stream",
    ".ktx2":  "image/ktx2",
    ".ktx":   "image/ktx",
    ".crn":   "application/octet-stream",
    ".b3dm":  "application/octet-stream",   # 3D Tiles binary
    ".ply":   "application/octet-stream",
}


def _content_type_for(suffix: str) -> str:
    return _CONTENT_TYPES.get(suffix.lower(), "application/octet-stream")


def get_source(name: str) -> PdfDataSource | None:
    return DATA_SOURCES.get(name)


def url_for(source_name: str, rel_path: str) -> str:
    """외부에서 URL 만들 때 사용. rel_path 의 한글/공백은 caller 가 quote()."""
    src = DATA_SOURCES.get(source_name)
    if src is None:
        raise ValueError(f"unknown PdfDataSource: {source_name}")
    return f"{src.url_base}/{rel_path.lstrip('/')}"


# ── 서버 상태 (모듈 전역 — hot-reload 중복 시작 방지) ─────────────────────
_server: "ThreadingHTTPServer | None" = None
_server_thread: "threading.Thread | None" = None
_server_started: bool = False
_server_lock = threading.Lock()


# Path traversal 차단용 DENY 토큰
_DENY_TOKENS = ("..", "\\", ":", "\x00")
_PING_PATH = "/__ping__"
_PING_OK_BODY = b"pdf-server-ok"


class _PDFHandler(BaseHTTPRequestHandler):
    """화이트리스트 + path traversal 차단된 PDF 정적 핸들러."""

    # streamlit 콘솔 노이즈 방지 — 매 GET 마다 stderr 출력 끔
    def log_message(self, format, *args):  # noqa: A002 — base 시그니처 유지
        return

    def _deny(self, code: int, msg: str = "") -> None:
        try:
            self.send_error(code, msg or None)
        except ConnectionError:
            pass

    def do_GET(self) -> None:  # noqa: N802 — base 시그니처
        # 헬스 체크 — start_once() 재시작 시 우리 서버 인지 식별
        if self.path == _PING_PATH:
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(_PING_OK_BODY)))
                self.end_headers()
                self.wfile.write(_PING_OK_BODY)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            return

        # URL 디코딩 (strict — 잘못된 byte 는 400)
        try:
            raw_path = urllib.parse.unquote(self.path, errors="strict")
        except (UnicodeDecodeError, ValueError):
            self._deny(400, "Bad URL encoding")
            return

        if "?" in raw_path:
            raw_path = raw_path.split("?", 1)[0]

        # 화이트리스트 prefix 매칭
        matched: PdfDataSource | None = None
        for src in DATA_SOURCES.values():
            if raw_path.startswith(src.url_prefix):
                matched = src
                break
        if matched is None:
            self._deny(403, "Forbidden")
            return

        rel = raw_path[len(matched.url_prefix):]

        # 빈 경로 / 디렉토리 listing 차단
        if not rel or rel.endswith("/"):
            self._deny(404, "Not Found")
            return

        # DENY 토큰 차단 (path traversal 1차 방어선)
        if any(tok in rel for tok in _DENY_TOKENS) or rel.startswith("/"):
            self._deny(403, "Forbidden")
            return

        # Path traversal 2차 방어선: commonpath + realpath
        try:
            real_root = matched.data_root.resolve(strict=True)
            target_raw = matched.data_root / rel
            real_target = target_raw.resolve(strict=True)
        except (OSError, RuntimeError):
            self._deny(404, "Not Found")
            return

        try:
            common = os.path.commonpath([str(real_target), str(real_root)])
        except ValueError:
            # 다른 드라이브 등 → 명백히 root 밖
            self._deny(403, "Forbidden")
            return
        if common != str(real_root):
            self._deny(403, "Forbidden")
            return

        # symlink/junction reject — Windows junction 우회 차단
        try:
            if real_target.is_symlink() or target_raw.is_symlink():
                self._deny(403, "Forbidden")
                return
        except OSError:
            self._deny(403, "Forbidden")
            return

        # 확장자 화이트리스트 (소문자 비교)
        if real_target.suffix.lower() not in matched.allowed_ext:
            self._deny(403, "Extension not allowed")
            return

        if not real_target.is_file():
            self._deny(404, "Not Found")
            return

        # 200 응답 + 스트리밍
        try:
            size = real_target.stat().st_size
            self.send_response(200)
            # Content-Type 은 확장자별 매핑 — drone 추가 시 .png/.json/.b3dm 등
            # 다양해짐. PDF 외 자료도 안전하게 inline 표시되도록.
            self.send_header("Content-Type", _content_type_for(real_target.suffix))
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "private, max-age=3600")
            self.send_header("X-Content-Type-Options", "nosniff")
            # CORS — 같은 streamlit 페이지에서 :8766 으로 fetch 하려면 CORS 허용 필요.
            # P4-1 (2026-05-29): '*' → localhost 특정 포트 화이트리스트.
            # SSOT (2026-05-29): config.STREAMLIT_PORT + PORT_CANDIDATES 동적 참조.
            # config.py 한 곳만 수정하면 본 화이트리스트도 자동 동기화 (재시작 필요).
            # legacy (8501, 8765) 도 마이그레이션 호환으로 포함.
            origin = self.headers.get("Origin", "")
            _allowed_ports = set()
            try:
                import config as _cfg
                _allowed_ports.add(int(_cfg.STREAMLIT_PORT))
                # PORT_CANDIDATES 도 모두 허용 (bat 의 자동 탐색이 다른 포트로 fallback 시)
                for _p in getattr(_cfg, "PORT_CANDIDATES", []):
                    _allowed_ports.add(int(_p))
            except (ImportError, AttributeError, TypeError, ValueError):
                _allowed_ports.add(18501)
            # legacy ports
            _allowed_ports.update({8501, 8765})
            allowed_origins = set()
            for _p in _allowed_ports:
                allowed_origins.add(f"http://localhost:{_p}")
                allowed_origins.add(f"http://127.0.0.1:{_p}")
            if origin in allowed_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
            else:
                # 같은 origin (예: 직접 :8766 페이지에서) 또는 미지정 — null 로
                # 응답 (모든 cross-origin 차단). Origin 없는 same-page 요청은
                # 어차피 CORS 검사 대상 아님.
                self.send_header("Access-Control-Allow-Origin", "null")
            # NOTE: Content-Disposition 헤더 의도적으로 제거.
            # 일부 브라우저(Edge 일부 빌드)는 `filename*=` 가 명시되어 있으면
            # `inline` 지시자를 무시하고 다운로드 대화상자를 띄움. 헤더 자체를
            # 빼면 브라우저가 Content-Type(application/pdf) + URL 의 `.pdf`
            # 확장자만 보고 내장 PDF 뷰어로 inline 표시. 한글 파일명은 URL 의
            # 마지막 segment 가 다운로드 시 기본 파일명으로 그대로 쓰임.
            self.end_headers()

            with real_target.open("rb") as f:
                while True:
                    chunk = f.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except ConnectionError:
            # 브라우저가 download 중 abort — Cesium 3D Tiles 의 표준 동작.
            # BrokenPipe / ConnectionReset / ConnectionAborted (WinError 10053) /
            # ConnectionRefused 모두 ConnectionError base 로 묶어 silent 처리.
            return
        except OSError as e:
            _logger.warning("[pdf_server] read failed: %s — %s", real_target, e)


class _ReuseAddrServer(ThreadingHTTPServer):
    """SO_REUSEADDR 활성화 — streamlit 재시작 시 TIME_WAIT 회피."""
    allow_reuse_address = True
    daemon_threads = True


def _static_folder_size() -> int:
    """src/dashboard/static/ 의 총 사이즈 (bytes). 디렉토리 없으면 0."""
    if not STREAMLIT_STATIC_DIR.exists():
        return 0
    total = 0
    try:
        for p in STREAMLIT_STATIC_DIR.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    continue
    except OSError:
        pass
    return total


def _suppress_all(fn) -> None:
    """M4 백그라운드 스레드용 — fn 호출 중 모든 예외 흡수.

    daemon 스레드가 STREAMLIT_STATIC_DIR rglob 도중 다른 cleanup 과 충돌해
    OSError 가 발생해도 main 흐름에 영향 없도록 광역 흡수.
    """
    try:
        fn()
    except Exception:  # noqa: BLE001
        pass


def _warn_if_static_oversized() -> None:
    """1GB 한계 사전 경고. 800MB 초과 시 stderr 로 출력 (streamlit 콘솔)."""
    size = _static_folder_size()
    if size <= STATIC_FOLDER_WARN_BYTES:
        return
    pct = size / (1024 * 1024 * 1024) * 100
    print(
        f"⚠️  [pdf_server] src/dashboard/static/ 사이즈 = {size/1024/1024:.0f} MB "
        f"(streamlit 1GB hard limit 의 {pct:.0f}%). "
        f"이 한도를 넘으면 모든 정적 서빙(map_tiles 포함)이 자동 비활성화됩니다. "
        f"data_*/ 폴더는 streamlit static 밖에서 pdf_server 가 서빙하므로 안전합니다.",
        file=sys.stderr,
    )
    # 폴더별 사이즈 top 3 (디버깅 단서)
    try:
        sizes: list[tuple[str, int]] = []
        for sub in STREAMLIT_STATIC_DIR.iterdir():
            if sub.is_dir():
                sub_size = sum(
                    p.stat().st_size
                    for p in sub.rglob("*")
                    if p.is_file()
                )
                sizes.append((sub.name, sub_size))
        sizes.sort(key=lambda t: t[1], reverse=True)
        for name, sz in sizes[:3]:
            print(
                f"    - {name}/: {sz/1024/1024:.0f} MB",
                file=sys.stderr,
            )
    except OSError:
        pass


def _is_our_server_listening() -> bool:
    """포트 8766 이 우리 pdf_server 인지 헬스 체크로 확인.

    어떤 예외든 잡아서 "우리 서버 아님" 으로 판단. 죽은 소켓이 비정상 응답
    (BadStatusLine 등) 하는 케이스 포함 — 이전 인스턴스가 깔끔히 종료 안
    됐을 때 start_once() 전체가 죽지 않도록 방어.
    """
    try:
        with urllib.request.urlopen(
            f"{PDF_SERVER_URL_BASE}{_PING_PATH}",
            timeout=1.0,
        ) as resp:
            return resp.status == 200 and resp.read() == _PING_OK_BODY
    except Exception:   # noqa: BLE001 — health check 는 어떤 실패도 = "우리 서버 아님"
        return False


def start_once() -> None:
    """PDF 서버를 한 번만 시작. streamlit hot-reload 시 중복 시작 방지.

    동작:
      1) 이미 우리 서버가 떠 있으면(=ping OK) skip
      2) port 점유된 다른 프로세스라면 warning + skip (streamlit 본체는 정상)
      3) 정상 시작 시 데몬 스레드 + atexit shutdown 등록
      4) src/dashboard/static/ 사이즈 800MB 초과 시 사전 경고
    """
    global _server, _server_thread, _server_started
    global PDF_SERVER_PORT, PDF_SERVER_URL_BASE  # 23차: 동적 포트 fallback

    with _server_lock:
        if _server_started and _server is not None:
            return

        # 1GB 재발 사전 경고 (실패해도 서버 시작은 계속)
        # M4 fix 2026-05-30: 동기 호출 시 STREAMLIT_STATIC_DIR rglob 가 cold-start 를
        # 수백 ms ~ 1s 까지 늦춰 사용자 체감 지연. 백그라운드 daemon 스레드로 분리.
        # 실패해도 stderr 출력만이라 timing 영향 없음. OSError(다른 cleanup race) 등은
        # try/except 광역으로 흡수 — 서버 시작 자체에 영향 주지 않음.
        threading.Thread(
            target=lambda: _suppress_all(_warn_if_static_oversized),
            name="pdf-server-warn",
            daemon=True,
        ).start()

        # 이미 우리 서버가 떠 있는 경우 (streamlit script 재실행 등)
        if _is_our_server_listening():
            _server_started = True
            _logger.info(
                "[pdf_server] already running on %s:%d (ping OK) — skip start",
                PDF_SERVER_HOST, PDF_SERVER_PORT,
            )
            return

        # 23차: PORT_CANDIDATES 순회로 사용 가능 포트 자동 선택
        # WinError 10013 (Windows 동적 포트 예약 — Hyper-V/WSL/Docker) 대응
        import socket as _sock
        srv = None
        _last_err = None
        for _p in PDF_SERVER_PORT_CANDIDATES:
            # 1) bind 가능성 사전 확인
            _tst = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
            try:
                _tst.bind((PDF_SERVER_HOST, _p))
            except OSError as _e:
                _last_err = _e
                try: _tst.close()
                except OSError: pass
                continue
            _tst.close()
            # 2) 실제 server 생성
            try:
                srv = _ReuseAddrServer((PDF_SERVER_HOST, _p), _PDFHandler)
                if _p != PDF_SERVER_PORT:
                    print(
                        f"[pdf_server] 기본 port {PDF_SERVER_PORT} 사용 불가 → port {_p} 자동 전환",
                        file=sys.stderr,
                    )
                PDF_SERVER_PORT = _p
                PDF_SERVER_URL_BASE = f"http://{PDF_SERVER_HOST}:{_p}"
                break
            except OSError as e:
                _last_err = e
                continue
        if srv is None:
            print(
                f"⚠️  [pdf_server] 모든 후보 포트 {list(PDF_SERVER_PORT_CANDIDATES)} 시작 실패 "
                f"— {_last_err}. "
                f"관리자 cmd: 'netsh interface ipv4 show excludedportrange protocol=tcp' "
                f"실행 → 예약 범위 확인. PDF 링크가 동작하지 않을 수 있습니다.",
                file=sys.stderr,
            )
            return

        thread = threading.Thread(
            target=srv.serve_forever,
            name="pdf-server",
            daemon=True,
        )
        thread.start()

        _server = srv
        _server_thread = thread
        _server_started = True

        # 종료 시 graceful shutdown
        atexit.register(_shutdown)

        _logger.info(
            "[pdf_server] started on %s:%d — sources=%s",
            PDF_SERVER_HOST, PDF_SERVER_PORT,
            list(DATA_SOURCES.keys()),
        )


def _shutdown() -> None:
    """atexit 콜백 — 서버 정리. streamlit 종료 시 호출."""
    global _server, _server_thread, _server_started
    if _server is not None:
        try:
            _server.shutdown()
            _server.server_close()
        except Exception:  # noqa: BLE001
            pass
        _server = None
        _server_thread = None
        _server_started = False

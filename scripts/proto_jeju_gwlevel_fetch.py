# ==============================================================================
#  파일명: scripts/proto_jeju_gwlevel_fetch.py
#  목적 : water.jeju.go.kr 의 selectObsvEachList.json 직접 호출 — 1개소 프로토타입
# ------------------------------------------------------------------------------
#  Build: 0.1 (2026-06-01)
#  사용법:
#      python scripts/proto_jeju_gwlevel_fetch.py
#
#  이 스크립트는 본격 collector 작성 전 "정말 이 방식으로 데이터를 받을 수 있는지"
#  를 1개 관측소(JW연동, siteCode=Y199310639) × 1개월(2026-05-01~31) 일평균으로
#  검증하기 위한 일회성 프로토타입입니다.
#
#  성공 기준:
#    1) JSESSIONID 발급 → POST 200 응답
#    2) JSON 응답에 31일치 일자료가 포함
#    3) 2026-05-31 값이 화면 캡처와 일치:
#         EL=33.53, GL=71.61, Pressure=6.28, Temp=14.69,
#         EC=117, Barometa=1009.58, Battery=13.31
#
#  결과 처리:
#    - 응답 raw JSON 을 outputs 폴더에 저장 (구조 분석용)
#    - 파싱한 DataFrame 을 CSV 로 저장
#    - 검증 결과(성공/실패 + 차이값) 콘솔 출력
#
#  검증 5팀 권고 반영:
#    - User-Agent 명시
#    - Referer 헤더 명시
#    - Hidden CSRF 토큰 후보 자동 추출
#    - 요청 1회만 — rate limit 우려 없음
# ==============================================================================
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import requests
import urllib3

# 출력은 프로젝트 루트의 임시 폴더 — 일회성 진단용
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "data" / "_proto"
OUT.mkdir(parents=True, exist_ok=True)

BASE = "https://water.jeju.go.kr"
SEARCH_PAGE = f"{BASE}/obsvsystem/gwobsv/obsvData/dataSearch/multiSearch.cs"
DATA_API = f"{BASE}/obsvsystem/gwobsv/selectObsvEachList.json"

# 테스트 대상 (CLI 로 오버라이드 가능 — 아래 main 의 argparse 참고)
SITE_CODE_DEFAULT = "Y199310639"   # JW연동
STATION_NAME_DEFAULT = "JW연동"
S_DATE_DEFAULT = "2026-05-01"
E_DATE_DEFAULT = "2026-05-31"
MEASURE_DEFAULT = "dayAvg"

# 화면 캡처 기준값 (2026-05-31 일평균)
# 🆕 검증 5팀 실측 결과 반영: 실제 JSON 키 이름으로 매핑.
EXPECTED_LAST_DAY = {
    "el": 33.53, "gl": 71.61, "wPress": 6.28,
    "wTemp": 14.69, "scond": 117, "wBaro": 1009.58, "battery": 13.31,
}

HEADERS_HTML = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def main() -> int:
    # 🆕 CLI 옵션 — 기본은 JW연동 / 2026-05 일평균.
    ap = argparse.ArgumentParser(description="제주 지하수 API 단일 관측소 프로토타입")
    ap.add_argument("--start", default=S_DATE_DEFAULT, help="시작일 YYYY-MM-DD")
    ap.add_argument("--end",   default=E_DATE_DEFAULT, help="종료일 YYYY-MM-DD")
    ap.add_argument("--site",  default=SITE_CODE_DEFAULT, help="siteCode (예: Y199310639)")
    ap.add_argument("--name",  default=STATION_NAME_DEFAULT, help="관측소명 (파일명에 사용)")
    ap.add_argument("--mode",  default=MEASURE_DEFAULT,
                    choices=["hourAvg", "dayAvg", "monAvg"], help="측정 단위")
    ap.add_argument("--cross-check", action="store_true",
                    help="기존 by_station_day CSV 와 겹치는 날짜에 대해 셀단위 대조")
    args = ap.parse_args()

    S_DATE, E_DATE = args.start, args.end
    SITE_CODE, STATION_NAME = args.site, args.name
    MEASURE = args.mode

    print("=" * 70)
    print(f"  제주 지하수정보관리시스템 API 프로토타입")
    print(f"  관측소: {STATION_NAME} ({SITE_CODE}) / 기간: {S_DATE} ~ {E_DATE} / {MEASURE}")
    print("=" * 70)

    session = requests.Session()
    session.headers.update(HEADERS_HTML)
    # SSL 검증: 한국 공공기관 사이트는 KISA/GPKI 루트 CA 사용 → Python certifi에
    # 없어 SSLError 발생. 브라우저는 OS 인증서 저장소를 써서 정상. 첫 시도는
    # verify=True, 실패 시 verify=False 로 폴백 (공공 데이터 조회용 표준 패턴).
    verify_mode: bool = True

    # 1) 세션 발급
    print("\n[1/3] 페이지 GET → JSESSIONID 발급...")
    try:
        r = session.get(SEARCH_PAGE, timeout=15, verify=verify_mode)
        r.raise_for_status()
    except requests.exceptions.SSLError as e:
        print(f"  ⚠ SSL 검증 실패 — Python certifi 에 한국 정부 루트 CA 미포함.")
        print(f"     상세: {str(e)[:120]}")
        print(f"     verify=False 로 재시도합니다 (브라우저는 이미 정상 동작 확인됨).")
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        verify_mode = False
        try:
            r = session.get(SEARCH_PAGE, timeout=15, verify=verify_mode)
            r.raise_for_status()
        except Exception as e2:
            print(f"  ❌ verify=False 재시도도 실패: {type(e2).__name__}: {e2}")
            return 1
    except Exception as e:
        print(f"  ❌ 페이지 GET 실패: {type(e).__name__}: {e}")
        return 1
    print(f"  ✓ status={r.status_code}, 쿠키={list(session.cookies.keys())}, verify={verify_mode}")

    # 1.5) CSRF 토큰 후보 자동 추출 (있으면)
    csrf_token = None
    csrf_header_name = None
    html = r.text
    for pat in [
        r'<meta\s+name="_csrf"\s+content="([^"]+)"',
        r'<input[^>]+name="_csrf"[^>]+value="([^"]+)"',
        r'<input[^>]+name="CSRF[^"]*"[^>]+value="([^"]+)"',
    ]:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            csrf_token = m.group(1)
            print(f"  ✓ CSRF 토큰 감지: {csrf_token[:20]}...")
            break
    # 헤더 이름도 함께 (Spring 패턴)
    m2 = re.search(r'<meta\s+name="_csrf_header"\s+content="([^"]+)"', html, re.IGNORECASE)
    if m2:
        csrf_header_name = m2.group(1)
    if not csrf_token:
        print("  · CSRF 토큰 없음 — 세션 쿠키만으로 진행")

    # 2) 데이터 API 호출
    # 🆕 2026-06-01 fix: 브라우저 캡처로 확인한 9개 정식 파라미터.
    #   이전 `sensorCb=S11` 은 잘못된 키 → `mSns=S11` 가 정답.
    #   isExcel/pageIndex/pageUnit/awsRainChck 누락 시 400 Bad Request.
    print("\n[2/3] selectObsvEachList.json POST...")
    payload = {
        "mesureUnit":    MEASURE,       # hourAvg / dayAvg / monAvg
        "sDate":         S_DATE,
        "eDate":         E_DATE,
        "siteCode":      SITE_CODE,
        "mSns":          "S11",         # 멀티 센서 (S11 = 표준 수위 센서)
        "isExcel":       "N",           # 화면 검색은 N, 엑셀 생성은 Y
        "pageIndex":     "1",
        "pageUnit":      "120",         # 일평균 최대 31, 시평균 최대 ~744, 여유 잡아 120
        "awsRainChck":   "false",       # AWS 강수 동시 조회 여부
    }
    headers = {
        "Referer": SEARCH_PAGE,
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    if csrf_token and csrf_header_name:
        headers[csrf_header_name] = csrf_token

    try:
        r2 = session.post(DATA_API, data=payload, headers=headers,
                          timeout=30, verify=verify_mode)
        r2.raise_for_status()
    except Exception as e:
        print(f"  ❌ 데이터 API POST 실패: {type(e).__name__}: {e}")
        if 'r2' in locals():
            print(f"     status={r2.status_code}, body[:300]={r2.text[:300]}")
        return 1
    print(f"  ✓ status={r2.status_code}, len={len(r2.content):,}바이트")

    # 응답 저장
    raw_path = OUT / f"raw_{STATION_NAME}_{S_DATE}_{E_DATE}.json"
    raw_path.write_bytes(r2.content)
    print(f"  · 원본 응답 저장: {raw_path}")

    # JSON 파싱
    try:
        data = r2.json()
    except Exception:
        print(f"  ❌ JSON 파싱 실패. body[:500]={r2.text[:500]}")
        return 1

    # 응답 구조 출력 (최상위 키만)
    print(f"\n  응답 최상위 타입: {type(data).__name__}")
    if isinstance(data, dict):
        for k, v in data.items():
            vsmall = type(v).__name__
            if isinstance(v, list):
                vsmall += f"(len={len(v)})"
                if v and isinstance(v[0], dict):
                    vsmall += f", item.keys={list(v[0].keys())[:8]}"
            print(f"    {k!r}: {vsmall}")
    elif isinstance(data, list):
        print(f"    list(len={len(data)})")
        if data and isinstance(data[0], dict):
            print(f"    item[0].keys={list(data[0].keys())[:10]}")

    # 3) 데이터 위치 자동 추론 + 검증
    print("\n[3/3] 데이터 추출 및 화면값과 대조...")
    rows = _find_rows(data)
    if not rows:
        print("  ❌ 데이터 행을 찾지 못함. 위 응답 구조를 보고 _find_rows 를 수정하세요.")
        return 1
    print(f"  · 추출된 행 수: {len(rows)}")
    print(f"  · 첫 행 키: {list(rows[0].keys())[:15]}")
    print(f"  · 마지막 행: {rows[-1]}")
    print(f"  · 첫 행: {rows[0]}")

    # 화면 캡처 기준값 대조는 JW연동/5월 기본 케이스에서만 의미 있음
    if STATION_NAME == STATION_NAME_DEFAULT and "2026-05-31" in [str(r.get("dataTime")) for r in rows]:
        last = _pick_by_date(rows, "2026-05-31")
        if last:
            print(f"\n  📊 화면 캡처(2026-05-31)와 셀단위 대조:")
            ok = 0
            for fld, expected in EXPECTED_LAST_DAY.items():
                got = last.get(fld)
                try:
                    got_num = float(got) if got is not None else None
                except (TypeError, ValueError):
                    got_num = None
                mark = "✓" if got_num is not None and abs(got_num - expected) < 0.01 else "❌"
                if mark == "✓":
                    ok += 1
                print(f"    {mark} {fld:10s}  기대={expected}  실제={got}")
            print(f"  결과: {ok}/{len(EXPECTED_LAST_DAY)} 컬럼 일치")

    # 🆕 Cross-check: 기존 CSV(by_station_day) 와 겹치는 날짜 셀 단위 대조
    if args.cross_check or "2026-04-28" in [str(r.get("dataTime")) for r in rows]:
        csv_path = (ROOT / "data" / "01_rain_gwlevel" / "GWlevel"
                    / "by_station_day" / f"{STATION_NAME}.csv")
        print(f"\n  📋 Cross-check vs {csv_path.name}")
        if not csv_path.exists():
            print(f"    · 기존 CSV 없음 — cross-check 스킵")
        else:
            try:
                import pandas as pd
                existing = pd.read_csv(csv_path, encoding="utf-8-sig")
                existing["날짜"] = pd.to_datetime(existing["날짜"]).dt.strftime("%Y-%m-%d")
                api_by_date = {str(r.get("dataTime")): r for r in rows}
                overlap = sorted(set(existing["날짜"]) & set(api_by_date.keys()))
                if not overlap:
                    print(f"    · 겹치는 날짜 0건 — cross-check 불가")
                else:
                    print(f"    · 겹치는 날짜 {len(overlap)}건: 모두 EL 1셀씩 대조")
                    print(f"    {'날짜':<12} {'CSV EL':>10} {'API el':>10} {'Δ':>10}")
                    diffs_ok = 0
                    for d in overlap:
                        csv_el = float(existing.loc[existing["날짜"] == d, "EL"].iloc[0])
                        try:
                            api_el = float(api_by_date[d].get("el"))
                        except (TypeError, ValueError):
                            api_el = None
                        if api_el is None:
                            print(f"    {d:<12} {csv_el:>10.2f} {'None':>10} {'N/A':>10}")
                            continue
                        delta = api_el - csv_el
                        mark = "✓" if abs(delta) < 0.01 else "❌"
                        if mark == "✓":
                            diffs_ok += 1
                        print(f"    {d:<12} {csv_el:>10.2f} {api_el:>10.2f} {delta:>+10.4f} {mark}")
                    print(f"\n    Cross-check 결과: {diffs_ok}/{len(overlap)} 정확 일치 (Δ<0.01)")
                    if diffs_ok == len(overlap):
                        print(f"\n  ✅ API ↔ 기존 CSV 1:1 동일 — 본격 collector 진행 가능")
                    else:
                        print(f"\n  ⚠ 일부 차이값 발생 — 단위 보정 또는 측정 정정 가능성 검토 필요")
            except Exception as e:
                print(f"    ❌ Cross-check 실패: {type(e).__name__}: {e}")

    return 0


def _find_rows(data) -> list[dict]:
    """응답 구조에서 행 리스트를 자동으로 찾는다.

    가능한 패턴:
      - {"resultList": [...]}, {"list": [...]}, {"data": [...]}
      - {"response": {"body": {"items": {"item": [...]}}}}
      - list 자체
    """
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    # 흔한 키
    for k in ("resultList", "list", "data", "rows", "items", "result"):
        v = data.get(k)
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v
    # 중첩 — public data portal 패턴
    body = data.get("response", {}).get("body", {})
    items = body.get("items")
    if isinstance(items, dict) and isinstance(items.get("item"), list):
        return items["item"]
    if isinstance(items, list):
        return items
    # 전수 탐색 (마지막 수단)
    for v in data.values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v
    return []


def _pick_by_date(rows: list[dict], date_str: str) -> dict | None:
    """rows 에서 2026-05-31 등에 해당하는 행을 찾는다.

    날짜 컬럼명은 다양: 날짜/일시/measureDate/checkDate/regDate/baseDate 등.
    """
    candidates = ["날짜", "일시", "measureDate", "checkDate", "regDate",
                  "baseDate", "obsvDate", "rcptYmd", "date"]
    short = date_str[-8:].replace("-", "")  # 20260531
    for row in rows:
        for k in candidates:
            if k in row and row[k]:
                v = str(row[k])
                if date_str in v or short in v.replace("-", ""):
                    return row
        # fallback — 어떤 값이라도 날짜 같은 게 들어 있으면
        for v in row.values():
            if isinstance(v, str) and (date_str in v or short in v.replace("-", "")):
                return row
    return None


def _try_get(row: dict, keys: list[str]):
    for k in keys:
        if k in row:
            return row[k]
    return None


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[Ctrl+C] 중단")
        sys.exit(130)

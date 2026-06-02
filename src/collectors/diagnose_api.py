# ==============================================================================
#  제주도 지하수위·강수량 분석 대시보드
#  파일명: src/collectors/diagnose_api.py
#  모듈: 기상청 API 진단 도구 (독립 실행)
# ------------------------------------------------------------------------------
#  Build: 0.4
#  최종 수정일: 2026-04-21
# ------------------------------------------------------------------------------
#  Changelog:
#  - v0.3 (2026-04-21): 최초 생성.
#                       API 키·URL·응답 형식을 단계별로 진단하여
#                       실패 원인을 즉시 특정할 수 있게 함.
#  - v0.4 (2026-04-21): User-Agent 헤더 유무 비교 테스트 추가.
#                       * WAF 403 Forbidden 차단 원인을 명확히 확인 가능.
#                       * config.HTTP_HEADERS 사용.
# ------------------------------------------------------------------------------
#  【이 파일의 역할】
#  "수집이 안 되는데 왜 안 되는지 모르겠다" 할 때 실행하는 진단 전용 도구.
#  작은 API 호출(5일치 1개 지점)만 하여 빠르게 원인을 파악합니다.
#
#  【실행 방법】
#      터미널에서 프로젝트 루트로 이동 후:
#          python src/collectors/diagnose_api.py
#
#  【검사 항목】
#   [1] .env 파일 및 API 키 확인
#   [2] HTTPS 엔드포인트 연결 테스트
#   [3] HTTP 엔드포인트 연결 테스트 (폴백)
#   [4] 응답 형식 분석 (JSON / XML / HTML / 텍스트)
#   [5] 에러 코드 해석 및 조치 방법 안내
# ==============================================================================

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[2]))

import requests
from json import JSONDecodeError

import config


# ==============================================================================
#  ■ 공통 에러 코드 해석 테이블
# ==============================================================================
#  공공데이터포털에서 반환하는 주요 에러 코드와 조치 방법
ERROR_CODE_GUIDE = {
    "00": ("정상", "✅ 정상 응답"),
    "01": ("Application Error", "서버 측 임시 오류. 잠시 후 재시도."),
    "02": ("DB Error", "서버 DB 오류. 잠시 후 재시도."),
    "03": ("No Data", "⚠️ 요청한 기간/지점에 데이터 없음"),
    "04": ("HTTP Error", "HTTP 요청 자체 오류. URL/파라미터 확인."),
    "05": ("Service Timeout", "서버 응답 지연. 재시도하거나 요청 범위를 줄이기."),
    "10": ("Invalid Request Parameter", "❗ 요청 파라미터 오류. 날짜/지점코드 확인."),
    "11": ("No Mandatory Parameter", "❗ 필수 파라미터 누락."),
    "12": ("No Open API Service", "❗ 해당 서비스가 존재하지 않음."),
    "20": ("Service Access Denied",
           "❗❗ API 키가 해당 서비스에 접근 권한이 없음. 활용신청 확인!"),
    "21": ("Limited Number Of Service Requests Exceeds",
           "❗❗ 일일 호출량 초과. 내일 다시 시도하거나 자동승인 개발용→운영용 전환."),
    "22": ("Service Request Limit Exceeds",
           "❗❗ 일일 트래픽 초과. 내일 다시 시도."),
    "30": ("Service Key Is Not Registered Error",
           "❌❌❌ API 키가 등록되지 않았거나 오타. 공공데이터포털에서 키 재확인!"),
    "31": ("Deadline Has Expired Error",
           "❌❌❌ API 키 만료. 공공데이터포털에서 기간 연장 또는 재발급."),
    "32": ("Unregistered IP Error",
           "❗ IP 등록 필요 (보통 기본값으로는 해당 없음)."),
    "33": ("Unsigned Call Error",
           "❗ 서명 누락 (보통 기본값으로는 해당 없음)."),
    "99": ("Unknown Error", "알 수 없는 오류. 공공데이터포털 문의."),
}


def interpret_error_code(code: str, msg: str = "") -> str:
    """에러 코드를 사람이 이해할 수 있는 안내로 변환"""
    if code in ERROR_CODE_GUIDE:
        name, guide = ERROR_CODE_GUIDE[code]
        return f"[{code}] {name}\n     👉 {guide}"
    return f"[{code}] {msg} (알 수 없는 코드)"


# ==============================================================================
#  ■ Step 1. .env 및 API 키 확인
# ==============================================================================
def check_api_key() -> bool:
    print("\n" + "─" * 70)
    print("[1/5] .env 파일 및 API 키 확인")
    print("─" * 70)

    env_file = config.PROJECT_ROOT / ".env"
    if not env_file.exists():
        print(f"  ❌ .env 파일 없음: {env_file}")
        print(f"     → .env.example 를 복사해서 .env 로 만드세요.")
        return False
    print(f"  ✅ .env 파일 존재: {env_file}")

    key = config.KMA_API_KEY
    if not key:
        print("  ❌ KMA_API_KEY 값이 비어있음")
        print("     → .env 파일 안에 'KMA_API_KEY=...' 형식으로 입력했는지 확인")
        return False

    # 키 길이 검증 (기상청 Decoding 키는 64자가 일반적, Encoding 키는 100자 내외)
    print(f"  ✅ KMA_API_KEY 로드됨")
    print(f"     길이: {len(key)}자")
    print(f"     앞 10자: {key[:10]}...")
    print(f"     뒤 5자: ...{key[-5:]}")

    # 일반적인 Decoding 키 패턴 (hex 문자열)
    if len(key) == 64 and all(c in "0123456789abcdefABCDEF" for c in key):
        print(f"     💡 형식: Decoding 키로 보임 (권장 형식 ✅)")
    elif "%" in key or "+" in key or "=" in key:
        print(f"     ⚠️ 형식: Encoding 키로 보임 (Decoding 키 권장)")
        print(f"        공공데이터포털 → 마이페이지 → 개발계정 → 인증키(Decoding) 복사")
    else:
        print(f"     💡 형식: 일반 문자열")

    return True


# ==============================================================================
#  ■ Step 2·3. API 호출 테스트 (HTTPS / HTTP)
# ==============================================================================
def test_api_call(url: str, label: str, use_headers: bool = True) -> dict:
    """
    작은 API 호출을 시도하고 결과를 상세히 반환.

    🆕 Build 0.4: use_headers 파라미터 추가.
       User-Agent 헤더 유무에 따른 차이를 확인하기 위함.
    """
    hdr_label = "User-Agent 포함" if use_headers else "User-Agent 없음 (구버전)"
    print(f"\n  🔄 {label} 테스트 중... ({hdr_label})")
    print(f"     URL: {url[:60]}...")

    # 2024-01-01 ~ 2024-01-05 (5일치만, 제주 지점)
    params = {
        "serviceKey": config.KMA_API_KEY,
        "pageNo": "1", "numOfRows": "5",
        "dataType": "JSON", "dataCd": "ASOS", "dateCd": "DAY",
        "startDt": "20240101", "endDt": "20240105",
        "stnIds": "184",
    }

    result = {
        "success": False,
        "url": url,
        "status_code": None,
        "content_type": None,
        "body_preview": None,
        "error": None,
        "api_code": None,
        "api_msg": None,
        "use_headers": use_headers,
    }

    try:
        # 🆕 Build 0.4: User-Agent 헤더 선택적 적용
        headers = config.HTTP_HEADERS if use_headers else None
        response = requests.get(url, params=params, headers=headers, timeout=15)
        result["status_code"] = response.status_code
        result["content_type"] = response.headers.get("Content-Type", "")
        result["body_preview"] = response.text[:500]

        print(f"     HTTP 상태: {response.status_code}")
        print(f"     Content-Type: {result['content_type']}")

        # HTTP 레벨 에러
        if response.status_code != 200:
            result["error"] = f"HTTP {response.status_code}"
            print(f"     ❌ HTTP 에러: {response.status_code}")
            print(f"     응답 본문 (처음 300자):\n     {response.text[:300]}")
            return result

        # 응답 본문 분석
        body = response.text.strip()
        if not body:
            result["error"] = "빈 응답"
            print(f"     ❌ 응답 본문이 비어있음")
            return result

        # JSON 파싱 시도
        try:
            json_data = response.json()
            header = json_data.get("response", {}).get("header", {})
            code = header.get("resultCode", "")
            msg = header.get("resultMsg", "")
            result["api_code"] = code
            result["api_msg"] = msg

            print(f"     응답 형식: JSON ✅")
            print(f"     API 결과 코드: {code}")
            print(f"     API 메시지: {msg}")

            if code == "00":
                items = (json_data.get("response", {})
                                  .get("body", {})
                                  .get("items", {})
                                  .get("item", []))
                print(f"     데이터 건수: {len(items)}개")
                if items:
                    print(f"     샘플: {items[0]}")
                result["success"] = True
            else:
                result["error"] = interpret_error_code(code, msg)
                print(f"     ❌ API 에러: {result['error']}")

        except JSONDecodeError:
            # JSON이 아니라면 XML 또는 HTML 에러 페이지 가능성
            result["error"] = "응답이 JSON이 아님"
            print(f"     ❌ 응답이 JSON이 아닙니다")

            # XML 에러인지 확인
            if "<?xml" in body[:100] or "<OpenAPI_ServiceResponse>" in body[:200]:
                print(f"     🔍 XML 응답으로 판단됨 (에러 XML일 가능성):")
                print(f"     {body[:500]}")

                # XML에서 errMsg, returnReasonCode 추출 시도
                import re
                err_code_match = re.search(r"<returnReasonCode>([^<]+)</returnReasonCode>", body)
                err_msg_match = re.search(r"<errMsg>([^<]+)</errMsg>", body)
                ret_auth_msg_match = re.search(r"<returnAuthMsg>([^<]+)</returnAuthMsg>", body)

                if err_code_match:
                    code = err_code_match.group(1).strip()
                    result["api_code"] = code
                    guide = interpret_error_code(code)
                    print(f"     💡 추출된 에러코드: {guide}")
                if err_msg_match:
                    print(f"     💡 에러 메시지: {err_msg_match.group(1)}")
                if ret_auth_msg_match:
                    ret_msg = ret_auth_msg_match.group(1).strip()
                    print(f"     💡 인증 메시지: {ret_msg}")
                    result["api_msg"] = ret_msg
            elif "<html" in body[:100].lower() or "<!DOCTYPE" in body[:100]:
                print(f"     🔍 HTML 응답입니다 (로그인 페이지/에러 페이지일 가능성)")
                print(f"     {body[:300]}")
            else:
                print(f"     응답 본문 (처음 300자):\n     {body[:300]}")

    except requests.exceptions.Timeout:
        result["error"] = "Timeout"
        print(f"     ❌ 타임아웃 (15초)")
    except requests.exceptions.SSLError as e:
        result["error"] = f"SSL Error: {e}"
        print(f"     ❌ SSL 오류: {e}")
    except requests.exceptions.ConnectionError as e:
        result["error"] = f"Connection Error: {e}"
        print(f"     ❌ 연결 오류: {e}")
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        print(f"     ❌ 예외: {result['error']}")

    return result


# ==============================================================================
#  ■ Step 5. 종합 진단 및 권장 조치
# ==============================================================================
def final_diagnosis(https_result: dict, http_result: dict,
                    https_no_ua_result: dict = None):
    print("\n" + "=" * 70)
    print("  📋 진단 결과 요약 및 권장 조치")
    print("=" * 70)

    # Case 1: 정상
    if https_result["success"]:
        print("\n  ✅ HTTPS 호출 정상! 수집 모듈을 다시 실행하세요.")
        print("     python src/collectors/asos_collector.py")
        return

    if http_result["success"]:
        print("\n  ⚠️ HTTPS는 실패했지만 HTTP는 성공했습니다.")
        print("     config.py의 KMA_API_URL 을 HTTP로 복원하세요.")
        return

    # 🆕 Build 0.4: User-Agent 유무 비교
    #   UA 없는 경우도 실패했는지, 아니면 그것만 성공했는지 확인
    if https_no_ua_result and https_no_ua_result.get("use_headers") is False:
        ua_status = "✅ 성공" if https_no_ua_result["success"] else "❌ 실패"
        ua_http_code = https_no_ua_result.get("status_code", "?")
        print(f"\n  📊 User-Agent 유무별 결과:")
        print(f"     - UA 포함: ❌ 실패 (HTTP {https_result.get('status_code', '?')})")
        print(f"     - UA 없음: {ua_status} (HTTP {ua_http_code})")

        # 두 경우 다 실패했지만 에러 내용이 다르다면 네트워크/WAF 문제
        if (not https_no_ua_result["success"]
                and https_result.get("body_preview", "").strip() == "Forbidden"
                and https_no_ua_result.get("body_preview", "").strip() == "Forbidden"):
            print("\n  🎯 양쪽 다 'Forbidden' 응답 → 네트워크 레벨 차단 가능성")
            print("     이 경우 User-Agent 문제가 아닙니다. 아래 확인:")
            print("     1) VPN/프록시 사용 여부 확인 (있으면 해제하고 재시도)")
            print("     2) 회사/학교 방화벽 차단 여부 (개인 네트워크에서 재시도)")
            print("     3) 기상청 API 서비스 일시 장애 여부")
            print("        → https://www.data.go.kr 공지사항 확인")
            return

    # Case 2: 둘 다 실패 — 원인별 분석
    print("\n  ❌ 양쪽 모두 실패. 원인 분석:")

    # API 에러 코드가 있으면 그것이 우선
    code = https_result.get("api_code") or http_result.get("api_code")
    if code and code != "00":
        print(f"\n  🎯 추출된 에러 코드: [{code}]")
        if code in ERROR_CODE_GUIDE:
            name, guide = ERROR_CODE_GUIDE[code]
            print(f"     의미: {name}")
            print(f"     조치: {guide}")

        # 키 관련 에러
        if code in ("30", "31", "20"):
            print("\n  👉 권장 조치:")
            print("     1) 공공데이터포털(data.go.kr) 로그인")
            print("     2) '마이페이지' → '개발계정' 메뉴 이동")
            print("     3) '기상청_지상(종관, ASOS) 일자료 조회서비스' 확인")
            print("        - 상태가 '정상'인지 확인")
            print("        - '정지'라면 → 활용신청을 '연장'하거나 재신청")
            print("        - '승인대기'라면 → 즉시승인임, 잠시 기다렸다 재시도")
            print("     4) 인증키(Decoding) 복사 → .env 파일 KMA_API_KEY 값 교체")
            print("     5) .env 저장 후 이 스크립트 재실행")

        elif code in ("21", "22"):
            print("\n  👉 권장 조치:")
            print("     일일 호출량 초과. 24시간 기다린 후 재시도하거나,")
            print("     공공데이터포털에서 운영계정(트래픽 증가) 신청 검토.")

        elif code == "03":
            print("\n  👉 권장 조치:")
            print("     요청한 날짜에 데이터가 없음. 2024년 대신 최근 날짜로 시도.")

        return

    # HTTP 레벨 403 Forbidden (WAF 차단)
    if (https_result.get("status_code") == 403
            or http_result.get("status_code") == 403):
        body = (https_result.get("body_preview", "") or "").strip()
        if body == "Forbidden" or body.startswith("Forbidden"):
            print("\n  🎯 403 Forbidden (plain text) — WAF/네트워크 차단")
            print("     (API 서비스에 도달하지 못하고 방화벽에서 차단됨)")
            print("\n  👉 권장 조치:")
            print("     1) VPN/프록시를 사용 중이라면 해제 후 재시도")
            print("     2) 회사/학교 네트워크라면 개인 네트워크(집/핫스팟)에서 재시도")
            print("     3) IP 차단 가능성: 공공데이터포털 고객센터 문의")
            print("     4) 브라우저에서 직접 URL 테스트 (아래 URL 복사하여 브라우저 주소창에):")
            # P4-5 (2026-05-29): API 키 앞 15자 → 5자로 축소.
            # 로그/스크린샷 공유 시 부분 키 유출 영향 최소화. 브라우저 테스트는
            # 사용자가 .env 의 KMA_API_KEY 를 직접 복사해 채우도록 안내.
            _key_prefix = (config.KMA_API_KEY or "")[:5]
            print(f"        {https_result['url']}?serviceKey={_key_prefix}***[전체키는 .env 참조]***"
                  f"&pageNo=1&numOfRows=5&dataType=JSON&dataCd=ASOS&dateCd=DAY"
                  f"&startDt=20240101&endDt=20240105&stnIds=184")
            return

    # 네트워크 레벨 실패
    err_https = https_result.get("error", "") or ""
    err_http = http_result.get("error", "") or ""

    if "Timeout" in (err_https + err_http):
        print("\n  🎯 네트워크 타임아웃")
        print("     - 인터넷 연결 상태 확인")
        print("     - 방화벽/VPN이 apis.data.go.kr 차단하는지 확인")
        print("     - 회사/학교 네트워크라면 IT 팀에 문의")
    elif "SSL" in err_https:
        print("\n  🎯 SSL/TLS 오류 (HTTPS)")
        print("     - pip install --upgrade certifi")
        print("     - pip install --upgrade requests")
    elif "Connection" in (err_https + err_http):
        print("\n  🎯 연결 실패")
        print("     - 인터넷 연결 확인")
        print("     - DNS 설정 확인 (apis.data.go.kr 접속 가능한지)")
    else:
        print(f"\n  🎯 HTTPS 오류: {err_https}")
        print(f"     HTTP 오류:  {err_http}")
        print("     → 에러 메시지를 Claude에게 복사해서 보내세요.")


# ==============================================================================
#  ■ 메인 실행
# ==============================================================================
def main():
    print("=" * 70)
    print("  🩺 기상청 ASOS API 진단 도구 (Build 0.4)")
    print("=" * 70)
    print("  이 도구는 작은 API 호출 1~2회만 수행하여 문제 원인을 파악합니다.")
    print("  기존 수집기가 실패할 때 먼저 이 도구를 실행하세요.")

    # Step 1: API 키
    if not check_api_key():
        print("\n❌ API 키 문제로 진단 중단.")
        return

    # Step 2: HTTPS 테스트 (User-Agent 포함)
    print("\n" + "─" * 70)
    print("[2/5] HTTPS 엔드포인트 테스트 (User-Agent 헤더 포함)")
    print("─" * 70)
    https_result = test_api_call(config.KMA_API_URL, "HTTPS", use_headers=True)

    # 🆕 Build 0.4: User-Agent 없이 재테스트 (WAF 차단 원인 확인용)
    # HTTPS+UA 실패 시에만 실행 (성공했으면 의미 없음)
    https_no_ua_result = {"success": False, "error": "생략됨"}
    if not https_result["success"]:
        print("\n" + "─" * 70)
        print("[추가] User-Agent 없이 동일 테스트 (WAF 차단 원인 확인)")
        print("─" * 70)
        https_no_ua_result = test_api_call(
            config.KMA_API_URL, "HTTPS (UA 없음)", use_headers=False
        )

    # Step 3: HTTP 테스트 (HTTPS+UA 도 실패 시만)
    http_result = {"success": False, "error": "생략됨"}
    if not https_result["success"]:
        print("\n" + "─" * 70)
        print("[3/5] HTTP 엔드포인트 테스트 (폴백, User-Agent 포함)")
        print("─" * 70)
        http_result = test_api_call(
            config.KMA_API_URL_FALLBACK, "HTTP", use_headers=True
        )
    else:
        print("\n[3/5] HTTP 테스트 생략 (HTTPS 성공)")

    # Step 4·5: 종합 진단
    print("\n" + "─" * 70)
    print("[4-5/5] 응답 분석 및 권장 조치")
    print("─" * 70)
    final_diagnosis(https_result, http_result, https_no_ua_result)

    print("\n" + "=" * 70)
    print("  진단 완료.")
    print("=" * 70)


if __name__ == "__main__":
    main()

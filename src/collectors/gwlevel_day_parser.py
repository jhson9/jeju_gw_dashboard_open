# ==============================================================================
#  제주도 지하수위·강수량 분석 대시보드
#  파일명: src/collectors/gwlevel_day_parser.py
#  모듈: 지하수위 일자료 xls(HTML) 파일 파서 (관측정별 일별 EL)
# ------------------------------------------------------------------------------
#  Build: 1.2.01
#  최초 생성: 2026-04-26
# ------------------------------------------------------------------------------
#  【원본 파일 형식】
#  제주 지하수정보관리시스템(water.jeju.go.kr)에서 다운로드한 .xls 는
#  실제로는 HTML 테이블(<html xm...> 시그니처). pd.read_html 로 파싱.
#
#  Wide 포맷 (날짜 × 연도):
#      날짜          2026   2025    2024   2023   2022 ...  2016
#      2026-12-31    -      15.95   23.40  17.71  17.27 ... 18.38
#      2026-12-30    -      15.99   23.53  17.76  17.30 ... 18.42
#      ...
#      2026-01-01    15.91  23.28   17.69  17.23  21.07 ... 20.13
#
#  - 첫 컬럼 '날짜' = 'YYYY-MM-DD' 이지만, 실제는 (월·일) 키 (연도는 무시).
#  - 나머지 컬럼 = 정수 연도. 셀 값은 해당 (연-월-일) 의 EL 수위(m).
#  - 결측치 = '-' 문자 → NaN 처리.
#
#  【출력 형식 (long-format CSV)】
#      관측소명, 날짜(YYYY-MM-DD), EL(수위 m)
#  저장 경로: data/GWlevel/by_station_day/{관측소명}.csv
#
#  【향후 확장 (요청 12)】
#  - 컬럼 헤더가 정수형(년)인 모든 컬럼을 자동으로 unpivot 하므로,
#    2015·2014 등 과거 연도가 추가된 파일이 들어와도 코드 수정 불필요.
#  - 신규 다운로드 시 기존 CSV 와 (관측소명, 날짜) 키로 upsert(병합)되어
#    이전 자료가 사라지지 않고 누적됨.
# ==============================================================================

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[2]))

import re
import warnings
import pandas as pd
from tqdm import tqdm

import config


MISSING_TOKENS = ["-", "", "NaN", "nan", "N/A", "None"]


# ==============================================================================
#  ■ 1. 단일 파일 파싱
# ==============================================================================
def parse_single_day_xls(file_path: Path) -> tuple[str, pd.DataFrame | None]:
    """
    단일 일자료 xls(HTML) 파일을 읽어 long-format DataFrame으로 반환.

    Returns
    -------
    (status, dataframe)
        status : "SUCCESS" / "PARSE_ERROR" / "EMPTY"
        dataframe columns: 관측소명, 날짜(YYYY-MM-DD), EL(float)
    """
    station = file_path.stem  # 파일명에서 관측소명 추출 (요청 13)

    # ── (사전) 원본은 <thead style="display:none"> 으로 헤더가 숨겨져 있어
    #          pd.read_html 이 헤더를 인식하지 못함. 직접 HTML 에서 추출. ──
    try:
        html_text = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"PARSE_ERROR: read_text {e}", None

    thead_match = re.search(r"<thead[^>]*>(.*?)</thead>", html_text, re.DOTALL | re.IGNORECASE)
    if thead_match:
        ths = re.findall(r"<th[^>]*>(.*?)</th>", thead_match.group(1),
                         re.DOTALL | re.IGNORECASE)
        header = [re.sub(r"<[^>]+>", "", t).strip() for t in ths]
    else:
        header = []

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            # header=None: pd.read_html 이 첫 행을 데이터로 인식하도록 함
            tables = pd.read_html(file_path, encoding="utf-8", header=None,
                                  flavor="lxml")
    except Exception as e:
        return f"PARSE_ERROR: {type(e).__name__}: {e}", None

    if not tables:
        return "EMPTY", None

    raw = tables[0].copy()
    if raw.empty:
        return "EMPTY", None

    # ── 1) 추출된 thead 기반으로 컬럼명 부여 ──
    if header and len(header) == raw.shape[1]:
        raw.columns = header
    else:
        # 헤더 추출 실패 시: 관례상 첫 컬럼=날짜, 나머지는 첫 행이 보통 날짜이므로
        # 컬럼 수가 맞지 않으면 에러로 처리
        if raw.shape[1] < 2:
            return "PARSE_ERROR: 컬럼 수 부족", None
        cols = ["날짜"] + [str(c) for c in raw.columns[1:]]
        raw.columns = cols

    if "날짜" not in raw.columns:
        # 첫 컬럼이 날짜 패턴이면 '날짜' 로 강제 변경
        sample = str(raw.iloc[0, 0]) if len(raw) > 0 else ""
        if re.match(r"^\d{4}-\d{2}-\d{2}$", sample):
            raw = raw.rename(columns={raw.columns[0]: "날짜"})
        else:
            return "PARSE_ERROR: 날짜 컬럼을 찾지 못함", None

    # ── 2) 결측 토큰 → NaN ──
    raw = raw.replace(MISSING_TOKENS, pd.NA)

    # ── 3) 연도 컬럼만 추려 wide → long ──
    year_cols = []
    for c in raw.columns:
        # 헤더가 int(2026) 또는 str("2026") 형태
        try:
            y = int(str(c).strip())
            if 1900 <= y <= 2100:
                year_cols.append(c)
        except (ValueError, TypeError):
            continue

    if not year_cols:
        return "PARSE_ERROR: 연도 컬럼을 찾지 못함", None

    long_df = raw.melt(
        id_vars=["날짜"],
        value_vars=year_cols,
        var_name="연도",
        value_name="EL",
    )

    # ── 4) (월·일) 키 + 연도 → 실제 날짜 조합 ──
    # 원본 '날짜' = "2026-MM-DD" 이므로 MM-DD 추출
    long_df["연도"] = long_df["연도"].astype(str).str.strip().astype(int)
    md = long_df["날짜"].astype(str).str.extract(r"(\d{4})-(\d{2})-(\d{2})")
    long_df["MM"] = md[1]
    long_df["DD"] = md[2]
    # 실제 측정일 = "{연도}-MM-DD"
    long_df["날짜"] = (
        long_df["연도"].astype(str)
        + "-" + long_df["MM"]
        + "-" + long_df["DD"]
    )
    # datetime 변환 (윤년 등 잘못된 조합 → NaT 로 떨어짐)
    long_df["날짜_dt"] = pd.to_datetime(long_df["날짜"], errors="coerce")
    long_df = long_df.dropna(subset=["날짜_dt"])

    # ── 5) EL 수치화 + 결측 제거 ──
    long_df["EL"] = pd.to_numeric(long_df["EL"], errors="coerce")
    long_df = long_df.dropna(subset=["EL"])

    if long_df.empty:
        return "EMPTY", None

    # ── 6) 정렬·정리 ──
    long_df = long_df.sort_values("날짜_dt").reset_index(drop=True)
    out = pd.DataFrame({
        "관측소명": station,
        "날짜": long_df["날짜_dt"].dt.strftime("%Y-%m-%d"),
        "EL": long_df["EL"].astype(float).round(3),
    })

    # 중복 제거 (드물지만 같은 날짜가 두 번 나오는 경우 가장 마지막 값 채택)
    out = out.drop_duplicates(subset=["관측소명", "날짜"], keep="last")
    return "SUCCESS", out


# ==============================================================================
#  ■ 2. Upsert (기존 CSV 와 병합)
# ==============================================================================
def upsert_station_csv(station: str, new_df: pd.DataFrame) -> Path:
    """
    by_station_day/{station}.csv 에 신규 데이터를 upsert.

    - 기존 파일이 있으면 로드 → 합치고 (관측소명, 날짜) 중복은 새 값 우선.
    - 정렬 후 저장.
    - 향후 4월 22일 이후 자료를 재다운로드해 추가하더라도 안전.
    """
    config.GW_STATION_DAY_DIR.mkdir(parents=True, exist_ok=True)
    out_path = config.GW_STATION_DAY_DIR / f"{station}.csv"

    if out_path.exists():
        try:
            old_df = pd.read_csv(out_path, encoding="utf-8-sig")
            old_df = old_df[["관측소명", "날짜", "EL"]] if not old_df.empty else old_df
        except Exception:
            old_df = pd.DataFrame(columns=["관측소명", "날짜", "EL"])
        merged = pd.concat([old_df, new_df], ignore_index=True)
    else:
        merged = new_df.copy()

    # 새 값 우선(keep='last' = 뒤에 들어온 new_df 가 후순위) → 새 데이터로 덮어쓰기
    merged = merged.drop_duplicates(subset=["관측소명", "날짜"], keep="last")
    merged["날짜_dt"] = pd.to_datetime(merged["날짜"], errors="coerce")
    merged = merged.dropna(subset=["날짜_dt"]).sort_values("날짜_dt")
    merged = merged.drop(columns=["날짜_dt"])
    merged.to_csv(out_path, index=False, encoding="utf-8-sig")
    return out_path


# ==============================================================================
#  ■ 3. 전체 폴더 일괄 처리
# ==============================================================================
def run_full_day_pipeline(verbose: bool = True) -> dict:
    """
    Row_Data/Day/JD*.xls 를 모두 파싱해 by_station_day/{관측소명}.csv 로 저장.
    """
    config.ensure_directories()

    src_dir = config.ROW_DATA_DAY_DIR
    files = sorted(list(src_dir.glob("JD*.xls")) + list(src_dir.glob("JD*.xlsx")))

    if not files:
        if verbose:
            print(f"⚠️ {src_dir} 에 일자료 xls 파일이 없습니다.")
        return {"success": [], "failed": [], "total_files": 0, "success_count": 0}

    if verbose:
        print("=" * 70)
        print("🌊 지하수위 일자료 xls 파싱 시작")
        print(f"   대상 경로: {src_dir}")
        print(f"   파일 수: {len(files)}개")
        print("=" * 70)

    success, failed = [], []
    iterator = tqdm(files, desc="일자료 파싱") if verbose else files
    for fp in iterator:
        status, df = parse_single_day_xls(fp)
        if status == "SUCCESS" and df is not None and not df.empty:
            station = df["관측소명"].iloc[0]
            out_path = upsert_station_csv(station, df)
            success.append((station, out_path, len(df)))
        else:
            failed.append((fp.name, status))
            if verbose:
                tqdm.write(f"   ⚠️ {fp.name} 실패: {status}")

    if verbose:
        total_rows = sum(n for *_, n in success)
        print(f"\n✅ 완료: 성공 {len(success)}개 / 실패 {len(failed)}개")
        print(f"   누적 신규 레코드: {total_rows:,}개")
        print(f"   저장 위치: {config.GW_STATION_DAY_DIR}")
        if failed:
            print("\n❌ 실패한 파일:")
            for name, reason in failed:
                print(f"   - {name}: {reason}")

    return {
        "success": success,
        "failed": failed,
        "total_files": len(files),
        "success_count": len(success),
    }


# ==============================================================================
#  ■ 4. 대시보드용 헬퍼
# ==============================================================================
def load_station_day(station: str) -> pd.DataFrame:
    """관측정 1개의 일자료 CSV 로드. 컬럼: 관측소명, 날짜(datetime), EL(float)."""
    p = config.GW_STATION_DAY_DIR / f"{station}.csv"
    if not p.exists():
        return pd.DataFrame(columns=["관측소명", "날짜", "EL"])
    df = pd.read_csv(p, encoding="utf-8-sig")
    if df.empty:
        return df
    df["날짜"] = pd.to_datetime(df["날짜"], errors="coerce")
    df = df.dropna(subset=["날짜"]).sort_values("날짜").reset_index(drop=True)
    return df


def list_day_stations() -> list[str]:
    """by_station_day/ 에 저장된 관측정 이름 목록."""
    if not config.GW_STATION_DAY_DIR.exists():
        return []
    return sorted([p.stem for p in config.GW_STATION_DAY_DIR.glob("*.csv")])


if __name__ == "__main__":
    run_full_day_pipeline()

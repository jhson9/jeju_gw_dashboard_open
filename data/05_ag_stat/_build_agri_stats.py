# -*- coding: utf-8 -*-
"""
농업통계 데이터 빌드 (tab41~45 데이터 파이프라인) — 연 1회 갱신용
================================================================
실행:  python data/05_ag_stat/_build_agri_stats.py
출력:  data/05_ag_stat/*.csv  +  _meta.json

연도 갱신 방법:
  1) 새 통계연보를 SRC_YEARBOOK 경로(아래)에 두고
  2) YEARBOOK_EDITION / BASE_YEAR 를 새 연도로 변경
  3) 본 스크립트 재실행 → CSV 자동 갱신, 앱 재시작 시 tab41~45 반영
2013 등 과거 비교: 생성된 *_yearly.csv 에 연도 행을 직접 append.
"""
from __future__ import annotations
import json, shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent            # data/05_ag_stat
COWORK = Path(r"C:/COWORK_SPACE")

# ── 원천 경로 (사용자 PC 기준) ──
BASELINE = COWORK / "jeju_agri_baseline_proposal" / "data" / "processed"
SRC_YEARBOOK = COWORK / "보고서" / "2024년 기준 제65회 통계연보(게시용)" / "6.농림수산업.xlsx"
YEARBOOK_EDITION = "제65회 제주통계연보(2024년 기준)"
BASE_YEAR = 2024

BASELINE_FILES = [
    "population_by_eupmyeon.csv", "population_yearly_total.csv",
    "farm_household_yearly.csv", "farmland_area_yearly.csv",
    "crop_cultivation_area.csv", "data_dictionary.csv",
]


def copy_baseline():
    copied = []
    for fn in BASELINE_FILES:
        src = BASELINE / fn
        if src.exists():
            shutil.copy2(src, HERE / fn); copied.append(fn)
        else:
            print(f"  [경고] baseline 누락: {src}")
    return copied


def extract_farm_size():
    import openpyxl, pandas as pd
    wb = openpyxl.load_workbook(SRC_YEARBOOK, read_only=True, data_only=True)
    ws = wb["4.경지규모별농가"]; rows = list(ws.iter_rows(values_only=True)); wb.close()
    cols = ["연도", "합계", "경지없는농가", "경지있는농가", "0.1ha미만", "0.1~0.5ha",
            "0.5~1.0ha", "1.0~1.5ha", "1.5~2.0ha", "2.0~3.0ha", "3.0~5.0ha", "5.0~10.0ha"]
    out = []
    for r in rows:
        if not r or r[0] is None:
            continue
        try:
            yr = int(str(r[0]).strip())
        except (ValueError, TypeError):
            continue
        if yr < 2000 or yr > 2100:
            continue
        rec = {"연도": yr}
        for j, name in enumerate(cols[1:], start=1):
            v = r[j] if j < len(r) else None
            rec[name] = None if v in (None, "") else int(float(v))
        out.append(rec)
    pd.DataFrame(out, columns=cols).sort_values("연도").to_csv(
        HERE / "farm_size_distribution.csv", index=False, encoding="utf-8-sig")
    return len(out)


def write_meta(copied, extra):
    meta = {
        "title": "제주 농업통계 데이터셋 (tab41~45) — V3 data/05_ag_stat",
        "primary_sources": [YEARBOOK_EDITION, "2025 제주 주요행정통계",
                            "제주특별자치도 농업용수 종합계획 수립 보고서"],
        "datasets": copied + extra, "base_year": BASE_YEAR,
        "comparison_slots": {"2013_baseline": "보고서(2013) 확보 시 연도=2013 행을 *_yearly.csv 에 append"},
        "eupmyeon_geojson_names": ["한림읍", "애월읍", "구좌읍", "조천읍", "한경면", "대정읍",
                                   "남원읍", "성산읍", "안덕면", "표선면", "제주시 동지역", "서귀포시 동지역"],
        "geojson_unmapped_eupmyeon": ["추자면", "우도면"],
    }
    (HERE / "_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    print(f"[빌드] 출력: {HERE}")
    copied = copy_baseline(); print(f"  baseline 계승: {len(copied)}개")
    extra = []
    if SRC_YEARBOOK.exists():
        n = extract_farm_size(); extra.append("farm_size_distribution.csv")
        print(f"  경지규모별농가 추출: {n}행")
    else:
        print(f"  [경고] 통계연보 미발견: {SRC_YEARBOOK} → 경지규모 생략")
    write_meta(copied, extra); print("  _meta.json 작성 완료")
    print("[빌드] 완료")


if __name__ == "__main__":
    main()

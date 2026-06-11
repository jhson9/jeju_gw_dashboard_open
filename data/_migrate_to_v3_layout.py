# -*- coding: utf-8 -*-
"""
데이터 폴더 V3.0 레이아웃 마이그레이션 (멱등·rename 기반·삭제 없음)
====================================================================
실행:  python data/_migrate_to_v3_layout.py
       (대시보드를 종료한 상태에서 실행 권장 — 파일 잠금 방지)

동작:
  - 기존 폴더를 새 도메인 폴더로 '이동(rename)' 합니다. 삭제는 하지 않습니다.
  - 이미 이동된 항목은 건너뜁니다(여러 번 실행해도 안전).
  - config.py 는 신규우선+폴백이라 실행 전/중/후 모두 앱이 정상 동작합니다.

V3 레이아웃:
  data/00_source/<항목>/   원자료 보관(stat·rain_gwlevel·well·usage_quality·drone·map)
  data/00_map/             ← GIS_Map
  data/01_rain_gwlevel/    ← data/ASOS + data/GWlevel + data/Row_Data
  data/02_well/            ← data_ag_well(+well_card, drilling_log)  ※ usage·water_quality 제외
  data/03_usage_quality/   ← data_ag_well/usage + data_ag_well/water_quality
  data/04_drone/           ← data_drone
  data/05_ag_stat/         ← (이미 생성됨) 농업통계
"""
from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # 프로젝트 루트
DATA = ROOT / "data"

# (src, dst) — 순서 중요: data_ag_well 먼저 02_well 로 옮긴 뒤 usage/water_quality 분리
MOVES = [
    (ROOT / "GIS_Map",            DATA / "00_map"),
    (DATA / "ASOS",               DATA / "01_rain_gwlevel" / "ASOS"),
    (DATA / "GWlevel",            DATA / "01_rain_gwlevel" / "GWlevel"),
    (DATA / "Row_Data",           DATA / "01_rain_gwlevel" / "Row_Data"),
    (ROOT / "data_ag_well",       DATA / "02_well"),
    (DATA / "02_well" / "usage",          DATA / "03_usage_quality" / "usage"),
    (DATA / "02_well" / "water_quality",  DATA / "03_usage_quality" / "water_quality"),
    (ROOT / "data_well_card",     DATA / "02_well" / "well_card"),
    (ROOT / "data_drilling_log",  DATA / "02_well" / "drilling_log"),
    (ROOT / "data_drone",         DATA / "04_drone"),
]

SOURCE_SUBDIRS = ["stat", "rain_gwlevel", "well", "usage_quality", "drone", "map"]


def main() -> None:
    print("=" * 64)
    print(" 데이터 V3 레이아웃 마이그레이션 (rename 기반, 삭제 없음)")
    print(" 루트:", ROOT)
    print("=" * 64)

    # 1) 00_source 골격
    for sub in SOURCE_SUBDIRS:
        (DATA / "00_source" / sub).mkdir(parents=True, exist_ok=True)
    print("[00_source] 항목별 폴더 준비 완료:", SOURCE_SUBDIRS)

    # 2) 이동
    done, skipped, missing = 0, 0, 0
    for src, dst in MOVES:
        if dst.exists():
            print(f"  SKIP (이미 이동됨)  {dst.relative_to(ROOT)}")
            skipped += 1
            continue
        if not src.exists():
            print(f"  MISS (원본 없음)    {src.relative_to(ROOT)}")
            missing += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.rename(src, dst)
        print(f"  MOVE  {src.relative_to(ROOT)}  ->  {dst.relative_to(ROOT)}")
        done += 1

    print("-" * 64)
    print(f" 이동 {done} · 건너뜀 {skipped} · 원본없음 {missing}")

    # 3) 검증 — config 경로가 새 위치로 해석되는지
    import sys
    sys.path.insert(0, str(ROOT))
    import importlib, config
    importlib.reload(config)
    print("-" * 64)
    print(" config 경로 해석 검증:")
    checks = [
        ("MAP_DIR", config.MAP_DIR), ("ASOS_DIR", config.ASOS_DIR),
        ("ROW_DATA_DIR", config.ROW_DATA_DIR), ("WELL_DIR", config.WELL_DIR),
        ("AG_USAGE_DIR", config.AG_USAGE_DIR), ("AG_QUALITY_DIR", config.AG_QUALITY_DIR),
        ("WELL_CARD_DIR", config.WELL_CARD_DIR), ("DRILLING_LOG_DIR", config.DRILLING_LOG_DIR),
        ("DRONE_DATA_ROOT", config.DRONE_DATA_ROOT), ("AGRI_STATS_DIR", config.AGRI_STATS_DIR),
    ]
    for name, p in checks:
        tag = "신규" if "data" + os.sep + "0" in str(p) or str(p).replace("/", os.sep).find(os.sep+"0")>=0 else "?"
        print(f"   {name:16s} exists={Path(p).exists()}  -> ...{str(p)[-44:]}")
    print("=" * 64)
    print(" 완료. 대시보드를 실행해 정상 동작을 확인하세요.")


if __name__ == "__main__":
    main()

# ==============================================================================
#  제주도 지하수위·강수량 분석 대시보드
#  파일명: scripts/precompute_robust_bayes.py
#  스크립트: 유역별 로버스트-베이지안(F) 등 7개 방식 사전계산 → parquet 캐시
# ------------------------------------------------------------------------------
#  Build: 1.0
#  최종 수정일: 2026-06-11
# ------------------------------------------------------------------------------
#  【역할 — Hybrid 운영 전략 (검토 문서 확정안)】
#   - 완료월(M-2·M-1·완료 M)의 16유역 × 7방식(REF·A~F) 편차를 월 1회 사전계산
#     → data/01_rain_gwlevel/GWlevel/robust/gwlevel_robust_methods.parquet
#   - 대시보드(tab01/tab03)는 저장값만 표시 (체감 ≈0초). E·F MCMC (~1초/월)
#     부담을 화면 렌더에서 완전히 분리.
#   - 부분월(M partial)은 여기서 계산하지 않음 — tab03 이 일자료 기반
#     로버스트(D Biweight) 잠정치를 실시간(ms급) 계산.
#
#  【실행 방법】
#      python scripts/precompute_robust_bayes.py                 # 오늘 기준 M-2/M-1/M
#      python scripts/precompute_robust_bayes.py --base-date 2026-06-01
#      python scripts/precompute_robust_bayes.py --backfill 12   # 직전 12개 완료월
#
#  【자동수집 연계】
#   - docs/2026-06-01-자동수집-시스템.md 파이프라인 말미에 본 스크립트 1회
#     호출을 추가하면 월 변경 시 캐시가 자동 갱신된다.
# ==============================================================================

import argparse
import sys
import time
from datetime import date
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pandas as pd

import config
from src.analysis import robust_aggregator, watershed_mapper, period_calculator
from src.collectors import gwlevel_parser


def _completed_months(periods: dict) -> list:
    """periods dict 에서 partial 이 아닌 (year, month) 목록."""
    out = []
    for pk in ("M-2", "M-1", "M"):
        p = periods.get(pk)
        if not p:
            continue
        if p.get("partial"):
            print(f"  ↪ {pk} ({p['year']}-{p['month']:02d}) 은 부분월 — "
                  f"사전계산 제외 (대시보드가 D Biweight 잠정치 실시간 계산)")
            continue
        out.append((p["year"], p["month"]))
    return out


def _prev_months(base: date, n: int) -> list:
    """base 가 속한 달의 직전 n개 완료월 (최신부터)."""
    y, m = base.year, base.month
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y -= 1
            m = 12
        out.append((y, m))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="유역별 로버스트-베이지안(F) 등 7개 방식 사전계산")
    ap.add_argument("--base-date", type=str, default=None,
                    help="기준일 YYYY-MM-DD (기본: 오늘)")
    ap.add_argument("--backfill", type=int, default=0,
                    help="직전 N개 완료월 일괄 계산 (기본 0 = M-2/M-1/M 만)")
    args = ap.parse_args()

    base = (pd.to_datetime(args.base_date).date()
            if args.base_date else date.today())

    print("=" * 70)
    print("🧮 로버스트-베이지안 유역 대표값 사전계산 (Hybrid — 완료월 캐시)")
    print("=" * 70)

    # ── 1) 대상 월 결정 ──────────────────────────────────────
    if args.backfill > 0:
        targets = _prev_months(base, args.backfill)
    else:
        periods = period_calculator.compute_periods(
            base_date=base, partial_month=True)
        targets = _completed_months(periods)
    if not targets:
        print("❌ 계산할 완료월이 없습니다.")
        return 1
    print(f"📅 대상 월: {', '.join(f'{y}-{m:02d}' for y, m in targets)}")

    # ── 2) 데이터 로드 (1회) ─────────────────────────────────
    t0 = time.time()
    station_map = watershed_mapper.load_station_to_watershed_map(verbose=False)
    df_long = gwlevel_parser.load_all_station_data()
    if df_long.empty:
        print("❌ 관측소별 데이터 없음 — 먼저 gwlevel_parser 파이프라인 실행")
        return 1
    ws_data_all = watershed_mapper.load_watershed_data()   # REF 용
    mat = robust_aggregator.build_station_month_matrix(df_long)
    anom = robust_aggregator.build_anomaly_matrix(
        mat, config.GWLEVEL_BASELINE_YEARS)
    print(f"📂 관측소 {mat.shape[0]}개 × 연월 {mat.shape[1]}개 행렬 "
          f"(로드 {time.time()-t0:.1f}s)")

    # ── 3) 월별 7개 방식 계산 ────────────────────────────────
    frames = []
    for y, m in targets:
        t1 = time.time()
        df_m = robust_aggregator.compute_methods_for_month(
            mat, anom, station_map, y, m,
            n_years=config.GWLEVEL_BASELINE_YEARS,
            ws_data_all=ws_data_all,
        )
        n_f = int((df_m["방법"] == "F").sum()) if not df_m.empty else 0
        print(f"  ✅ {y}-{m:02d}: {len(df_m)} rows (F {n_f}유역) "
              f"— {time.time()-t1:.1f}s")
        if not df_m.empty:
            frames.append(df_m)

    if not frames:
        print("❌ 산출 결과 없음")
        return 1

    # ── 4) parquet 캐시 병합 저장 ────────────────────────────
    all_df = pd.concat(frames, ignore_index=True)
    robust_aggregator.save_to_cache(all_df)

    # ── 5) 요약 출력 (F 기준) ────────────────────────────────
    f_df = all_df[all_df["방법"] == "F"]
    if not f_df.empty:
        print("\n📊 로버스트-베이지안(F) 유역 편차 요약 (m):")
        for ym in sorted(f_df["연월"].unique()):
            sub = f_df[f_df["연월"] == ym].sort_values("유역")
            line = ", ".join(f"{r['유역']} {r['편차']:+.2f}"
                             for _, r in sub.iterrows())
            print(f"  {ym}: {line}")
    print(f"\n총 소요 {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

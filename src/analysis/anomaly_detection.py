# ==============================================================================
#  파일명: src/analysis/anomaly_detection.py
#  ---------------------------------------------------------------------------
#  도메인 데이터의 명백한 이상값을 표시(마킹) 전담.
#
#  사용자 정책 (jhson9, 2026-05):
#  - 이용량(volume_m3): 표시만. drop 하지 않음. 사용자가 화면에서 ⚠ 확인 후
#    수동으로 검토.
#  - 지하수위 / 수질 / 다변량 동시 이상 (기기 오동작 의심) 은 별도 함수에서
#    판단 (이 모듈에 함수 추가 예정).
#
#  임계는 "절대 이상" 만 사용. 통계적(IQR/z-score) 컷은 도입하지 않음 —
#  관정별 데이터 분포가 매우 다르고 소수 관측치에서 오작동 위험.
# ==============================================================================
from __future__ import annotations

from datetime import date

import pandas as pd


# 이용량 절대 임계 ---------------------------------------------------------------
# - 음수: 측정 오류 (이용량은 음수 불가)
# - 1e8 m³/월: 관정 1개의 월 이용량 한계. 일평균 약 333만㎥/일에 해당하며
#   현실 농업 관정에서 절대 도달 불가. 이상값팀 보고 (ad7a1b...) 권장값.
# - 미래 연도: 현재 연도보다 큰 year 는 데이터 오기입.
USAGE_VOLUME_NEGATIVE = 0.0
USAGE_VOLUME_HARD_MAX = 1e8


def detect_usage_anomalies(
    df: pd.DataFrame,
    *,
    current_year: int | None = None,
) -> pd.DataFrame:
    """`load_usage_long()` 출력에 이상값 마킹 두 컬럼을 추가.

    추가 컬럼:
        is_anomaly:     bool   — 명백한 이상 여부
        anomaly_reason: str    — 사유 ("" = 정상). 다중이면 "; " 로 구분

    원본 df 는 수정하지 않고 사본을 반환.

    Parameters
    ----------
    df : pd.DataFrame
        load_usage_long() 반환과 같은 스키마.
        필수 컬럼: volume_m3, year. 없는 컬럼은 건너뜀.
    current_year : int | None
        "미래 연도" 판정 기준. 기본 = 오늘 날짜의 연도.
    """
    if df is None or df.empty:
        return df

    out = df.copy()
    n = len(out)
    reasons = pd.Series([""] * n, index=out.index, dtype="object")
    flag = pd.Series([False] * n, index=out.index, dtype=bool)

    # 1) volume_m3 음수
    if "volume_m3" in out.columns:
        v = pd.to_numeric(out["volume_m3"], errors="coerce")
        m_neg = v < USAGE_VOLUME_NEGATIVE
        if m_neg.any():
            flag |= m_neg
            reasons.loc[m_neg] = _append_reason(reasons.loc[m_neg], "음수")

        # 2) volume_m3 비현실적 극값
        m_big = v > USAGE_VOLUME_HARD_MAX
        if m_big.any():
            flag |= m_big
            reasons.loc[m_big] = _append_reason(
                reasons.loc[m_big], f"월 {USAGE_VOLUME_HARD_MAX:.0e}㎥ 초과"
            )

    # 3) 미래 연도 (오기입)
    if "year" in out.columns:
        cy = current_year if current_year is not None else date.today().year
        y = pd.to_numeric(out["year"], errors="coerce")
        m_future = y > cy
        if m_future.any():
            flag |= m_future
            reasons.loc[m_future] = _append_reason(
                reasons.loc[m_future], f"미래 연도(>{cy})"
            )

    out["is_anomaly"] = flag
    out["anomaly_reason"] = reasons
    return out


def _append_reason(existing: pd.Series, new_reason: str) -> pd.Series:
    """기존 reason 문자열에 새 사유를 '; ' 로 이어붙임."""
    return existing.apply(
        lambda s: new_reason if not s else f"{s}; {new_reason}"
    )


# ==============================================================================
#  지하수위 (gwlevel) 이상값 — 다중 컬럼 동시 이상 = 기기 오동작으로 drop
# ==============================================================================
#
#  사용자 정책 (jhson9, 2026-05):
#  - EL(수위)은 단독 이상이어도 자연 변동일 수 있으므로 임계 카운트에서 제외.
#  - 그 외 센서값(GL/Pressure/Temp/EC/Barometa/Battery) 중 2개 이상이 동시에
#    절대 임계를 벗어나면 = 기기 오동작 의심 = 그 행 drop.
#  - 1개 컬럼만 위반이면 자연 현상일 수 있어 warning 만 표시 (drop 안 함).
#  - drop 된 행은 caption 으로 "(관측소명, YYMMDD, 이상치추정 자료 미표시)"
#    형식 요약 표기.
#
#  임계는 보수적 절대값. 통계적 컷(IQR/z-score) 미사용.
# ------------------------------------------------------------------------------
GWLEVEL_THRESHOLDS = {
    # column   :  (low,    high,   단위)
    "GL":        (-100.0,  100.0,  "m"),
    "Pressure":  (-10.0,   200.0,  "dbar"),
    "Temp":      (-5.0,    50.0,   "°C"),
    "EC":        (0.0,     100000.0, "µS/cm"),
    "Barometa":  (800.0,   1200.0, "hPa"),
    "Battery":   (0.0,     30.0,   "V"),
}
# EL 은 의도적으로 제외 — 단독 이상은 자연 변동일 수 있음.

GWLEVEL_DROP_MIN_COLS = 2  # 위반 컬럼 수가 이 값 이상이면 drop


def detect_gwlevel_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """지하수위 long DataFrame 에 이상값 마킹 컬럼을 추가.

    추가 컬럼:
        is_anomaly:     bool — 임계 위반 컬럼 ≥ GWLEVEL_DROP_MIN_COLS (drop 대상)
        is_warning:     bool — 임계 위반 컬럼 == 1 (drop 안 함, 표시만)
        anomaly_reason: str  — "Barometa(1487.43); Battery(0.0)" 처럼 위반 내역

    원본은 수정하지 않고 사본 반환.
    """
    if df is None or df.empty:
        return df

    out = df.copy()
    n = len(out)
    violation_count = pd.Series([0] * n, index=out.index, dtype=int)
    reasons = pd.Series([""] * n, index=out.index, dtype="object")

    for col, (lo, hi, _unit) in GWLEVEL_THRESHOLDS.items():
        if col not in out.columns:
            continue
        v = pd.to_numeric(out[col], errors="coerce")
        m_violate = v.notna() & ((v < lo) | (v > hi))
        if not m_violate.any():
            continue
        violation_count.loc[m_violate] += 1
        # reason 문자열에 컬럼명(값) 추가
        for idx in out.index[m_violate]:
            piece = f"{col}({v.loc[idx]:.2f})"
            existing = reasons.loc[idx]
            reasons.loc[idx] = piece if not existing else f"{existing}; {piece}"

    out["is_anomaly"] = violation_count >= GWLEVEL_DROP_MIN_COLS
    out["is_warning"] = violation_count == 1
    out["anomaly_reason"] = reasons
    return out


def drop_gwlevel_anomalies(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """`detect_gwlevel_anomalies` 출력에서 is_anomaly 행을 제거하고,
    제거된 행의 요약 리스트를 함께 반환.

    Returns
    -------
    (df_clean, dropped_records)
        df_clean       : is_anomaly 행이 제거된 DataFrame
        dropped_records: [{"station": str, "yymmdd": str, "reason": str}, ...]
                         caption "(관측소명, YYMMDD, 이상치추정 자료 미표시)"
                         형식으로 표기하기 위한 요약
    """
    if df is None or df.empty or "is_anomaly" not in df.columns:
        return df, []

    flagged = df[df["is_anomaly"]].copy()
    dropped: list[dict] = []
    for _, row in flagged.iterrows():
        station = str(row.get("관측소명", "?"))
        date_val = row.get("날짜")
        try:
            yymmdd = pd.to_datetime(date_val).strftime("%y%m%d")
        except Exception:
            yymmdd = str(date_val)[:10]
        dropped.append({
            "station": station,
            "yymmdd": yymmdd,
            "reason": str(row.get("anomaly_reason", "")),
        })

    df_clean = df[~df["is_anomaly"]].reset_index(drop=True)
    return df_clean, dropped


def format_gwlevel_dropped_caption(dropped: list[dict],
                                   max_items: int = 5) -> str:
    """drop 요약 list 를 '(JD간드락, 250623, 이상치추정 자료 미표시)' 형식의
    caption 문자열로 변환. 항목이 max_items 초과면 '외 N건' 으로 압축.
    """
    if not dropped:
        return ""

    head = dropped[:max_items]
    parts = [f"({d['station']}, {d['yymmdd']}, 이상치추정 자료 미표시)"
             for d in head]
    text = " ".join(parts)
    rest = len(dropped) - len(head)
    if rest > 0:
        text += f" 외 {rest}건"
    return text


# ==============================================================================
#  요약 함수 (이용량용)
# ==============================================================================
def summarize_usage_anomalies(df: pd.DataFrame) -> dict:
    """tab7/대시보드 표시용 요약 dict.

    Returns
    -------
    {
        "total_rows": int,
        "anomaly_rows": int,
        "by_reason": {"음수": 12, "미래 연도(>2026)": 4, ...},
        "affected_permits": int,   # 이상값에 걸린 고유 permit_no 수
    }
    """
    if df is None or df.empty or "is_anomaly" not in df.columns:
        return {"total_rows": 0, "anomaly_rows": 0,
                "by_reason": {}, "affected_permits": 0}

    n_total = int(len(df))
    flagged = df[df["is_anomaly"]]
    n_flag = int(len(flagged))

    by_reason: dict[str, int] = {}
    for r in flagged["anomaly_reason"]:
        for piece in str(r).split(";"):
            piece = piece.strip()
            if piece:
                by_reason[piece] = by_reason.get(piece, 0) + 1

    affected = (
        int(flagged["permit_no"].nunique())
        if "permit_no" in flagged.columns else 0
    )
    return {
        "total_rows": n_total,
        "anomaly_rows": n_flag,
        "by_reason": by_reason,
        "affected_permits": affected,
    }

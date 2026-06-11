# ==============================================================================
#  제주도 지하수위·강수량 분석 대시보드
#  파일명: src/analysis/robust_aggregator.py
#  모듈: 유역별 지하수위 대표값 — 로버스트-베이지안(F) 및 비교 방식(REF·A~E)
# ------------------------------------------------------------------------------
#  Build: 1.0
#  최종 수정일: 2026-06-11
# ------------------------------------------------------------------------------
#  Changelog:
#  - v1.1 (2026-06-11): 검증2팀 MAJOR 2건 반영 — ① Biweight 1-pass 고정
#                       (반복 시 MAD 재계산으로 로버스트성 상실), ② E·F
#                       hyper-prior InvGamma(2,1)→약정보 InvGamma(0.01,0.01)
#                       (소표본 유역 과잉 shrinkage 해소).
#  - v1.0 (2026-06-11): 최초 생성 — "[Ai]수위 대표값 지정 오류 극복" 검토 결과
#                       (제주_지하수위_대표값산정법_종합보고서_V2, 6개방법 비교 xlsx,
#                       260607 로버스트 베이지안 적용 가이드라인) 반영.
#                       * 관측소별 anomaly(자기 직전 N년 동월 평균 대비) 우선 변환
#                       * 7개 방식: REF(현행 단순평균) · A(정규화) · B(분산가중) ·
#                         C(패널균형) · D(로버스트 Tukey Biweight) ·
#                         E(베이지안 계층 Normal-Normal) · F(로버스트-베이지안
#                         Student-t 계층, 본채택)
#                       * E·F 는 numpy Gibbs MCMC (16유역 동시 적합 — 섬 전체
#                         평균 μ_섬 으로 shrinkage)
#                       * 사전계산 캐시(parquet) 저장/로드 + 대시보드 조회 dict
# ------------------------------------------------------------------------------
#  【이 파일의 역할】
#  - 관측소(by_station)×월 수위(EL) → 관측소별 anomaly aᵢ = EL(y,m) − 자기
#    직전 N년 동월 평균  (표고 이질성·N_drop 왜곡 차단의 핵심)
#  - anomaly 들을 유역 단위로 7개 방식으로 집계해 "유역 변동폭(편차)" 산출
#  - F(Student-t 계층모형)가 공식 표시값, D(Biweight)는 부분월 잠정치용
#
#  【모형식 — 검토 문서 원문】
#      yᵢ ~ Student-t( ν, θ_w, σ_w )   ← 두꺼운 꼬리: 이상치 관측정 영향↓
#      θ_w ~ Normal( μ_섬, τ )          ← 계층 사전: 소표본 유역 shrinkage
#      → θ_w 사후평균 = 유역 편차 대표값, 95% 신뢰구간 병기
#
#  【실행 방법】 (사전계산 — scripts/precompute_robust_bayes.py 가 호출)
#      python -m src.analysis.robust_aggregator  (간이 self-test)
# ==============================================================================

import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd

import config

logger = logging.getLogger(__name__)

# CLI 실행 호환: streamlit 가 없을 때 no-op 데코레이터로 폴백 (watershed_mapper 동일 패턴)
try:
    import streamlit as _st
    _cache_data = _st.cache_data(ttl=600, show_spinner=False, max_entries=4)
except Exception:
    def _cache_data(fn):
        return fn


# ==============================================================================
#  ■ 0. 상수 — 검토 문서 확정 파라미터
# ==============================================================================
METHODS = ["REF", "A", "B", "C", "D", "E", "F"]
METHOD_LABELS = {
    "REF": "단순평균",
    "A": "정규화",
    "B": "분산가중",
    "C": "패널균형",
    "D": "로버스트(Biweight)",
    "E": "베이지안 계층",
    "F": "로버스트-베이지안 메타분석",
}

BIWEIGHT_C = 6.0          # Tukey Biweight: u = (x−med)/(c·MAD), c=6 (Felo 브리핑)
STUDENT_T_NU = 4.0        # F 가능도 자유도 ν — 문서에 기호만 명시 → ν=4 채택
                          #   (두꺼운 꼬리 표준 선택; 60개월 백테스트로 조정 가능)
MCMC_ITER = 3000          # Gibbs 반복
MCMC_BURN = 1000          # burn-in
MCMC_SEED = 42            # 재현성 고정
SIGMA_WINDOW = 60         # 방법 B σᵢ 산출 — 직전 60개월 anomaly 변동성
SIGMA_FLOOR = 0.05        # σᵢ 하한 (분모 폭발 가드)
MIN_BASELINE_YEARS = 1    # anomaly 산출에 필요한 최소 baseline 연수

# 사전계산 캐시 (parquet)
ROBUST_DIR = getattr(config, "GW_ROBUST_DIR",
                     config.RAIN_GW_DIR / "GWlevel" / "robust")
ROBUST_PARQUET = ROBUST_DIR / "gwlevel_robust_methods.parquet"


# ==============================================================================
#  ■ 1. 관측소×월 행렬 + anomaly 행렬
# ==============================================================================
def build_station_month_matrix(df_long: pd.DataFrame) -> pd.DataFrame:
    """관측소별 월자료(long) → pivot 행렬 (index=관측소명, columns=연월, values=EL).

    Parameters
    ----------
    df_long : DataFrame — gwlevel_parser.load_all_station_data() 결과.
        필수 컬럼: 관측소명, 연월, EL
    """
    if df_long is None or df_long.empty:
        return pd.DataFrame()
    df = df_long.dropna(subset=["EL"]).copy()
    df["연월"] = df["연월"].astype(str)
    mat = df.pivot_table(index="관측소명", columns="연월",
                         values="EL", aggfunc="mean")
    return mat[sorted(mat.columns)]


def build_anomaly_matrix(mat: pd.DataFrame, n_years: int) -> pd.DataFrame:
    """전체 anomaly 행렬 — 각 (관측소, 연월) 에 대해
    aᵢ(y,m) = EL(y,m) − mean( EL(y−1,m), …, EL(y−n_years,m) ).

    baseline 가용 연수가 MIN_BASELINE_YEARS 미만이면 NaN (신규/누락 관측정
    자동 제외 — N_drop 왜곡 차단).
    """
    if mat.empty:
        return pd.DataFrame()
    cols = list(mat.columns)
    col_set = set(cols)
    anom = pd.DataFrame(index=mat.index, columns=cols, dtype=float)
    for ym in cols:
        try:
            y, m = int(ym[:4]), int(ym[5:7])
        except (ValueError, IndexError):
            continue
        base_cols = [f"{y - k}-{m:02d}" for k in range(1, n_years + 1)
                     if f"{y - k}-{m:02d}" in col_set]
        if not base_cols:
            continue
        base = mat[base_cols]
        n_avail = base.notna().sum(axis=1)
        base_mean = base.mean(axis=1)
        a = mat[ym] - base_mean
        a[n_avail < MIN_BASELINE_YEARS] = np.nan
        anom[ym] = a
    return anom


def station_sigma(anom: pd.DataFrame, ym: str,
                  window: int = SIGMA_WINDOW) -> pd.Series:
    """방법 B 가중치용 관측소별 변동성 σᵢ — 분석월 직전 window개월 anomaly 표준편차."""
    if anom.empty or ym not in anom.columns:
        return pd.Series(dtype=float)
    cols = [c for c in anom.columns if c < ym][-window:]
    if not cols:
        return pd.Series(np.nan, index=anom.index)
    sig = anom[cols].std(axis=1, ddof=1)
    return sig.clip(lower=SIGMA_FLOOR)


# ==============================================================================
#  ■ 2. 폐쇄형 방식 — A · B · C · D
# ==============================================================================
def biweight_location(x: np.ndarray, c: float = BIWEIGHT_C) -> float:
    """Tukey Biweight 위치 추정 (방법 D) — 1-pass.

    u = (x − M) / (c·MAD),  w = (1−u²)² (|u|<1, 그 외 0)
    MAD=0 또는 표본 ≤2 → 중앙값 폴백.

    🛡️ (2026-06-11 검증2팀 MAJOR-1) 반복(iterative) 적용 시 MAD 를 갱신된
    위치 중심으로 재계산하면 MAD 가 부풀며 이상치 가중치가 복원되어
    로버스트성을 상실 (서서귀 2026-05 실측 −2.03 m 왜곡 재현). 검토 문서
    (Felo 브리핑)·기준 xlsx 정의와 동일한 **1-pass** (중앙값·MAD 1회 산출
    → 가중평균 1회) 로 고정한다.
    """
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return float("nan")
    if x.size <= 2:
        return float(np.median(x))
    m = float(np.median(x))
    mad = float(np.median(np.abs(x - m)))
    if mad <= 1e-12:
        return m
    u = (x - m) / (c * mad)
    w = np.where(np.abs(u) < 1.0, (1.0 - u ** 2) ** 2, 0.0)
    if w.sum() <= 1e-12:
        return m
    return float(np.sum(w * x) / np.sum(w))


def _closed_form_methods(a: pd.Series, sig: pd.Series,
                         panel_ok: pd.Series) -> dict:
    """유역 1개의 anomaly 벡터 → A·B·C·D 산출.

    Parameters
    ----------
    a        : Series(관측소명 → anomaly) — NaN 제외 전
    sig      : Series(관측소명 → σᵢ)
    panel_ok : Series(관측소명 → bool) — 분석월+모든 baseline 연도 자료 보유
    """
    av = a.dropna()
    out = {}
    n = int(av.size)
    out["n"] = n
    if n == 0:
        for mth in ("A", "B", "C", "D"):
            out[mth] = None
        return out
    vals = av.to_numpy(dtype=float)

    # A 정규화 — 단순평균(가중치 1)
    out["A"] = float(np.mean(vals))

    # B 분산가중 — Σ(wᵢaᵢ)/Σwᵢ, wᵢ = 1/σᵢ²
    s = sig.reindex(av.index)
    s = s.fillna(s.median() if np.isfinite(s.median()) else 1.0)
    s = s.clip(lower=SIGMA_FLOOR)
    w = 1.0 / (s.to_numpy(dtype=float) ** 2)
    out["B"] = float(np.sum(w * vals) / np.sum(w)) if np.isfinite(w).all() else out["A"]

    # C 패널균형 — 완전 패널(분석월+모든 baseline 보유) 관측소만 단순평균
    pidx = [st for st in av.index if bool(panel_ok.get(st, False))]
    out["C"] = float(av.loc[pidx].mean()) if pidx else None

    # D 로버스트 — Tukey Biweight
    out["D"] = biweight_location(vals)
    return out


# ==============================================================================
#  ■ 3. 베이지안 계층 Gibbs — E (Normal) · F (Student-t, 본채택)
# ==============================================================================
def fit_hierarchical_gibbs(groups: dict, student_t: bool = True,
                           nu: float = STUDENT_T_NU,
                           n_iter: int = MCMC_ITER,
                           burn: int = MCMC_BURN,
                           seed: int = MCMC_SEED) -> dict:
    """16개 유역 동시 계층모형 Gibbs 적합.

    모형 (F: student_t=True / E: student_t=False)
        yᵢ ~ N(θ_w, σ_w²/λᵢ),  λᵢ ~ Gamma(ν/2, ν/2)   [E 는 λᵢ≡1]
        θ_w ~ N(μ, τ²),  μ ~ N(0, 10²),  τ² ~ InvGamma(2, 1),
        σ_w² ~ InvGamma(2, 1)   (유역별)

    Parameters
    ----------
    groups : dict {유역명: np.ndarray(anomaly)} — NaN 제거 후, size≥1 만 포함

    Returns
    -------
    dict {유역명: {"mean": float, "lo": float, "hi": float, "n": int}}
    """
    names = [k for k, v in groups.items() if len(v) > 0]
    if not names:
        return {}
    rng = np.random.default_rng(seed)
    W = len(names)
    ys = [np.asarray(groups[k], dtype=float) for k in names]
    ns = np.array([len(y) for y in ys])

    # 초기값
    theta = np.array([float(np.median(y)) for y in ys])
    sigma2 = np.array([max(float(np.var(y)), 1e-4) if len(y) > 1 else 0.25
                       for y in ys])
    mu = float(np.mean(theta))
    tau2 = max(float(np.var(theta)), 1e-4)
    lam = [np.ones(n) for n in ns]

    # hyper-prior
    # 🛡️ (2026-06-11 검증2팀 MAJOR-2) InvGamma(2,1) 은 prior 평균 1 m²·유효
    # 가상표본 ≈4개로 3~6개소 소표본 유역에서 prior 가 지배 → 과잉 shrinkage
    # (서제주 F −2.854 vs 기준 −2.419). 약정보 InvGamma(0.01,0.01) 로 교체
    # — 재실행 시 기준 xlsx 와 괴리 0.46→0.07 m 수준으로 해소 확인.
    MU_PRIOR_VAR = 100.0
    A_TAU, B_TAU = 0.01, 0.01
    A_SIG, B_SIG = 0.01, 0.01

    keep = np.empty((n_iter - burn, W))
    for it in range(n_iter):
        # θ_w | rest
        for w in range(W):
            prec = np.sum(lam[w]) / sigma2[w] + 1.0 / tau2
            mean = (np.sum(lam[w] * ys[w]) / sigma2[w] + mu / tau2) / prec
            theta[w] = rng.normal(mean, np.sqrt(1.0 / prec))
        # μ | θ
        prec_mu = W / tau2 + 1.0 / MU_PRIOR_VAR
        mean_mu = (np.sum(theta) / tau2) / prec_mu
        mu = rng.normal(mean_mu, np.sqrt(1.0 / prec_mu))
        # τ² | θ, μ
        tau2 = 1.0 / rng.gamma(A_TAU + W / 2.0,
                               1.0 / (B_TAU + 0.5 * np.sum((theta - mu) ** 2)))
        tau2 = max(tau2, 1e-6)
        # σ_w², λᵢ | rest
        for w in range(W):
            resid2 = (ys[w] - theta[w]) ** 2
            sigma2[w] = 1.0 / rng.gamma(
                A_SIG + ns[w] / 2.0,
                1.0 / (B_SIG + 0.5 * np.sum(lam[w] * resid2)))
            sigma2[w] = max(sigma2[w], 1e-6)
            if student_t:
                lam[w] = rng.gamma((nu + 1.0) / 2.0,
                                   2.0 / (nu + resid2 / sigma2[w]))
                lam[w] = np.clip(lam[w], 1e-6, None)
        if it >= burn:
            keep[it - burn] = theta

    out = {}
    for w, name in enumerate(names):
        draws = keep[:, w]
        out[name] = {
            "mean": float(np.mean(draws)),
            "lo": float(np.percentile(draws, 2.5)),
            "hi": float(np.percentile(draws, 97.5)),
            "n": int(ns[w]),
        }
    return out


# ==============================================================================
#  ■ 4. 월 단위 — 7개 방식 일괄 산출
# ==============================================================================
def compute_methods_for_month(mat: pd.DataFrame, anom: pd.DataFrame,
                              station_map: dict, year: int, month: int,
                              n_years: int,
                              ws_data_all: "dict | None" = None) -> pd.DataFrame:
    """분석월 (year, month) 의 16유역 × 7방식 편차 DataFrame 산출.

    Returns
    -------
    DataFrame [유역, 연월, 방법, 편차, ci_low, ci_high, n_station]
    """
    ym = f"{year}-{month:02d}"
    rows = []
    if mat.empty or ym not in mat.columns:
        return pd.DataFrame(
            columns=["유역", "연월", "방법", "편차", "ci_low", "ci_high", "n_station"])

    a_all = anom[ym] if ym in anom.columns else pd.Series(dtype=float)
    sig = station_sigma(anom, ym)

    # 패널균형(C) 판정 — 분석월 + 모든 baseline 연도 자료 보유
    base_cols = [f"{year - k}-{month:02d}" for k in range(1, n_years + 1)
                 if f"{year - k}-{month:02d}" in mat.columns]
    if len(base_cols) == n_years:
        panel_ok = mat[ym].notna() & mat[base_cols].notna().all(axis=1)
    else:
        panel_ok = pd.Series(False, index=mat.index)

    ws_names = [w["name"] for w in config.WATERSHEDS]
    ws_stations = {wn: [st for st, w in station_map.items() if w == wn]
                   for wn in ws_names}

    # ── 폐쇄형 A·B·C·D + REF ──────────────────────────────────
    groups_for_bayes: dict = {}
    closed: dict = {}
    for wn in ws_names:
        sts = [s for s in ws_stations[wn] if s in a_all.index]
        a_w = a_all.reindex(sts)
        closed[wn] = _closed_form_methods(a_w, sig, panel_ok)
        av = a_w.dropna()
        if av.size > 0:
            groups_for_bayes[wn] = av.to_numpy(dtype=float)

    # ── E (Normal) · F (Student-t) — 16유역 동시 Gibbs ────────
    res_e = fit_hierarchical_gibbs(groups_for_bayes, student_t=False)
    res_f = fit_hierarchical_gibbs(groups_for_bayes, student_t=True)

    # ── REF — 현행 유역 절대수위 단순평균 편차 (by_watershed CSV) ─
    ref_vals: dict = {}
    if ws_data_all:
        for wn in ws_names:
            df_w = ws_data_all.get(wn)
            if df_w is None or df_w.empty or "연월" not in df_w.columns:
                continue
            ra = df_w[df_w["연월"].astype(str) == ym]
            if ra.empty or pd.isna(ra["EL_평균"].iloc[0]):
                continue
            actual = float(ra["EL_평균"].iloc[0])
            bv = []
            for y in range(year - n_years, year):
                rb = df_w[df_w["연월"].astype(str) == f"{y}-{month:02d}"]
                if not rb.empty and pd.notna(rb["EL_평균"].iloc[0]):
                    bv.append(float(rb["EL_평균"].iloc[0]))
            if bv:
                ref_vals[wn] = actual - sum(bv) / len(bv)

    # ── 조립 ───────────────────────────────────────────────────
    for wn in ws_names:
        c = closed.get(wn, {})
        n = c.get("n", 0)
        per_method = {
            "REF": ref_vals.get(wn),
            "A": c.get("A"), "B": c.get("B"),
            "C": c.get("C"), "D": c.get("D"),
            "E": (res_e.get(wn) or {}).get("mean"),
            "F": (res_f.get(wn) or {}).get("mean"),
        }
        for mth in METHODS:
            v = per_method.get(mth)
            if v is None or not np.isfinite(v):
                continue
            lo = hi = None
            if mth == "E":
                lo, hi = res_e[wn]["lo"], res_e[wn]["hi"]
            elif mth == "F":
                lo, hi = res_f[wn]["lo"], res_f[wn]["hi"]
            rows.append({
                "유역": wn, "연월": ym, "방법": mth,
                "편차": round(float(v), 3),
                "ci_low": round(float(lo), 3) if lo is not None else None,
                "ci_high": round(float(hi), 3) if hi is not None else None,
                "n_station": n,
            })
    return pd.DataFrame(rows)


# ==============================================================================
#  ■ 5. 사전계산 캐시 (parquet) 저장 / 로드
# ==============================================================================
def save_to_cache(df_new: pd.DataFrame, verbose: bool = True) -> Path:
    """월별 산출 결과를 parquet 캐시에 병합 저장 (같은 연월 행은 교체)."""
    ROBUST_DIR.mkdir(parents=True, exist_ok=True)
    if ROBUST_PARQUET.exists():
        try:
            old = pd.read_parquet(ROBUST_PARQUET)
            yms = set(df_new["연월"].unique())
            old = old[~old["연월"].isin(yms)]
            df_new = pd.concat([old, df_new], ignore_index=True)
        except Exception as e:
            logger.warning("robust 캐시 기존 파일 로드 실패 — 새로 생성: %s", e)
    df_new = df_new.sort_values(["연월", "유역", "방법"]).reset_index(drop=True)
    df_new["계산일시"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    df_new.to_parquet(ROBUST_PARQUET, index=False)
    if verbose:
        print(f"📁 robust 캐시 저장: {ROBUST_PARQUET} ({len(df_new)} rows)")
    return ROBUST_PARQUET


def load_cache() -> pd.DataFrame:
    """parquet 캐시 로드 — 없으면 빈 DataFrame."""
    if not ROBUST_PARQUET.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(ROBUST_PARQUET)
    except Exception as e:
        logger.warning("robust 캐시 로드 실패: %s", e)
        return pd.DataFrame()


def cache_mtime() -> float:
    """캐시 파일 mtime — streamlit 캐시 키 무효화용."""
    try:
        return ROBUST_PARQUET.stat().st_mtime
    except OSError:
        return 0.0


def build_period_dict(periods: dict) -> dict:
    """캐시 → 대시보드 조회 dict.

    Returns
    -------
    dict {유역명: {pk: {방법: {"편차","ci_low","ci_high","n"}}}}
        pk ∈ {"M-2","M-1","M"}. 캐시에 없는 (유역, 연월) 은 미포함.
    """
    df = load_cache()
    if df.empty:
        return {}
    out: dict = {}
    for pk in ("M-2", "M-1", "M"):
        p = periods.get(pk)
        if not p:
            continue
        ym = f"{p['year']}-{p['month']:02d}"
        sub = df[df["연월"] == ym]
        for _, r in sub.iterrows():
            wn = r["유역"]
            rec = {
                "편차": float(r["편차"]),
                "ci_low": float(r["ci_low"]) if pd.notna(r.get("ci_low")) else None,
                "ci_high": float(r["ci_high"]) if pd.notna(r.get("ci_high")) else None,
                "n": int(r["n_station"]),
            }
            out.setdefault(wn, {}).setdefault(pk, {})[r["방법"]] = rec
    return out


@_cache_data
def build_period_dict_cached(periods_key: str, mtime: float,
                             _periods: dict) -> dict:
    """streamlit 캐시 래퍼 — 키: periods_key(str) + 캐시파일 mtime.

    `_periods` 는 `_` prefix 로 hash 제외 (app.py `_cached_gwlevel_diff_dict`
    와 동일 패턴).
    """
    return build_period_dict(_periods)


# ==============================================================================
#  ■ 6. 부분월(1~D-1) 잠정치 — 방법 D (Biweight) 관측소 anomaly 집계
# ==============================================================================
def partial_month_biweight(daily_df: pd.DataFrame, station_map: dict,
                           base_date, n_years: int) -> dict:
    """부분월 로버스트 잠정 편차 — 관측소별 부분월 anomaly → 유역 Biweight.

    aᵢ = mean(EL, 당월 1~D-1) − mean( 과거 n_years 각 연도 같은 월 1~D-1 평균 )

    Parameters
    ----------
    daily_df : DataFrame [관측소명, 날짜(datetime), EL] — gwlevel_day parquet
    base_date : date — 기준일 (D). 부분월 윈도우는 1 ~ D-1 일.

    Returns
    -------
    dict {유역명: {"dev": float, "n": int}}
    """
    out: dict = {}
    if daily_df is None or daily_df.empty or base_date.day < 2:
        return out
    end_day = base_date.day - 1
    df = daily_df.dropna(subset=["EL", "날짜"]).copy()
    mask = ((df["날짜"].dt.month == base_date.month)
            & (df["날짜"].dt.day <= end_day))
    df = df[mask]
    if df.empty:
        return out
    df["_year"] = df["날짜"].dt.year

    # 관측소 × 연도 부분월 평균
    pm = (df.groupby(["관측소명", "_year"])["EL"].mean().unstack("_year"))
    cur_y = base_date.year
    if cur_y not in pm.columns:
        return out
    base_years = [y for y in range(cur_y - n_years, cur_y) if y in pm.columns]
    if not base_years:
        return out
    base_mean = pm[base_years].mean(axis=1)
    n_avail = pm[base_years].notna().sum(axis=1)
    a = pm[cur_y] - base_mean
    a[n_avail < MIN_BASELINE_YEARS] = np.nan
    a = a.dropna()

    ws_of = pd.Series({st: station_map.get(st) for st in a.index})
    for wn in set(station_map.values()):
        vals = a[ws_of.reindex(a.index) == wn].to_numpy(dtype=float)
        vals = vals[np.isfinite(vals)]
        if vals.size == 0:
            continue
        out[wn] = {"dev": round(biweight_location(vals), 3),
                   "n": int(vals.size)}
    return out


# ==============================================================================
#  ■ 7. 간이 self-test
# ==============================================================================
if __name__ == "__main__":
    # Biweight: 이상치 1개가 위치 추정을 흔들지 못해야 함
    x = np.array([0.1, 0.15, 0.05, 0.12, -8.0])
    bw = biweight_location(x)
    print(f"biweight({x}) = {bw:.3f}  (단순평균 {np.mean(x):.3f})")
    assert abs(bw - 0.1) < 0.2, "Biweight 이상치 저항 실패"

    # Gibbs: 알려진 θ 복원
    rng = np.random.default_rng(0)
    g = {f"W{i}": rng.normal(0.5, 0.3, size=8) for i in range(4)}
    g["W_out"] = np.concatenate([rng.normal(0.5, 0.3, size=7), [-9.0]])
    res = fit_hierarchical_gibbs(g, student_t=True)
    for k, v in res.items():
        print(f"{k}: θ={v['mean']:.3f} [{v['lo']:.3f}, {v['hi']:.3f}] n={v['n']}")
    assert abs(res["W_out"]["mean"] - 0.5) < 0.5, "Student-t 이상치 저항 실패"
    print("✅ self-test 통과")

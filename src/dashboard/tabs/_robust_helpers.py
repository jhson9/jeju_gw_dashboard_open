# ==============================================================================
#  파일명: src/dashboard/tabs/_robust_helpers.py
#  공용 헬퍼: 로버스트-베이지안(F) 유역 대표값 조회 + 7개 방식 비교표 + 설명 PDF
# ------------------------------------------------------------------------------
#  Build: 1.0
#  최종 수정일: 2026-06-11
# ------------------------------------------------------------------------------
#  【역할】 tab01_overview · tab03_gwlevel 이 공유.
#   - get_f_dev()        : robust dict 에서 F(로버스트-베이지안) 편차 lookup
#   - resolve_dev()      : F 우선 → REF(현행) 폴백 + 출처 태그
#   - render_method_comparison() : 하단 비교표 (REF·A~F × 16유역, 사용자 요청)
#   - render_method_ref_buttons(): 산정방법 설명 PDF chip 버튼 (pdf_server :8766)
#
#  【표시 정책 — 사용자 확정 2026-06-11】
#   - 완료월 편차의 공식 표시값 = F (Student-t 계층 MCMC, 사전계산 캐시)
#   - 부분월(M partial) 잠정치 = D (Tukey Biweight, 실시간)
#   - 캐시 미존재 시 REF(현행 단순평균) 폴백 + "(현행)" 라벨
# ==============================================================================

from urllib.parse import quote

import streamlit as st

import config
from src.analysis.robust_aggregator import METHOD_LABELS, METHODS
from src.dashboard import theme

# 비교표/캡션 공용 문구
F_LABEL = "로버스트-베이지안(Robust Bayesian) 메타분석"
F_SHORT_NOTE = (
    f"관측소별 변화량(자기 직전 {config.GWLEVEL_BASELINE_YEARS}년 동월 평균 "
    f"대비)을 Student-t 계층모형으로 집계한 대표값 — 이상치·관측소 "
    f"누락(N_drop)에 강건. 95% 신뢰구간은 하단 유역별 산정비교 표 참조."
)


# ==============================================================================
#  ■ 1. 조회 헬퍼
# ==============================================================================
def get_f_dev(robust_dict: "dict | None", ws: str, pk: str) -> "dict | None":
    """robust dict 에서 (유역, 기간) 의 F 레코드.

    Returns
    -------
    dict {"편차","ci_low","ci_high","n"} 또는 None
    """
    if not robust_dict:
        return None
    return (robust_dict.get(ws) or {}).get(pk, {}).get("F")


def get_method_dev(robust_dict: "dict | None", ws: str, pk: str,
                   method: str) -> "dict | None":
    if not robust_dict:
        return None
    return (robust_dict.get(ws) or {}).get(pk, {}).get(method)


def resolve_dev(robust_dict: "dict | None", diff_rec: "dict | None",
                ws: str, pk: str) -> "tuple | None":
    """편차 표시값 결정 — F 우선, 없으면 REF(현행) 폴백.

    Parameters
    ----------
    diff_rec : compute_gwlevel_diff_dict 의 {ws: {pk: {"실측","평균","편차"}}}
               중 [ws][pk] 레코드 (현행 폴백용)

    Returns
    -------
    (dev: float, ci: tuple|None, n: int|None, src: "F"|"REF") 또는 None
    """
    f = get_f_dev(robust_dict, ws, pk)
    if f is not None and f.get("편차") is not None:
        # (2026-06-11 검증1팀) ci_low·ci_high 동시 존재 시에만 CI 사용
        ci = ((f["ci_low"], f["ci_high"])
              if (f.get("ci_low") is not None
                  and f.get("ci_high") is not None) else None)
        return (float(f["편차"]), ci, f.get("n"), "F")
    if diff_rec is not None and diff_rec.get("편차") is not None:
        return (float(diff_rec["편차"]), None, None, "REF")
    return None


def dev_color_html(dev: "float | None", dec: int = 2,
                   unit: str = "", bold: bool = True) -> str:
    """편차 → 부호 색상 HTML (기존 tbl-pos/tbl-neg 색상 정책과 동일)."""
    if dev is None:
        return '<span style="color:#999;">–</span>'
    c = theme.COLOR_SUCCESS if dev >= 0 else theme.COLOR_DANGER
    sg = "+" if dev >= 0 else ""
    fw = "600" if bold else "500"
    return (f'<span style="color:{c};font-weight:{fw};">'
            f'{sg}{dev:.{dec}f}{unit}</span>')


def src_badge_html(src: str) -> str:
    """출처 미니 배지 — F(로버스트-베이지안) / REF(현행) / D(잠정)."""
    label, bg, fg = {
        "F":   ("RB", theme.COLOR_BG_INFO, theme.COLOR_TEXT_INFO),
        "D":   ("잠정·RB", "rgba(250,200,80,0.15)", "#8a6d1a"),
        "REF": ("현행", theme.COLOR_BG_SECONDARY, theme.COLOR_TEXT_TERTIARY),
    }.get(src, ("", "", ""))
    if not label:
        return ""
    return (f'<span style="display:inline-block;padding:0 5px;margin-left:4px;'
            f'border-radius:3px;font-size:11px;font-weight:600;'
            f'background:{bg};color:{fg};vertical-align:middle;">{label}</span>')


# ==============================================================================
#  ■ 2. 산정방법 설명 PDF chip 버튼 (pdf_server :8766 — well_card_pdf 동일 패턴)
# ==============================================================================
def render_method_ref_buttons(key_prefix: str = "rb"):
    """data/01_rain_gwlevel/Ref/ 의 설명 PDF 들을 chip 버튼으로 표시.

    클릭 = <a target="_blank"> → streamlit rerun 0회, 새 탭에서 PDF 오픈
    (well_card_pdf.py 의 chip 패턴 준수, reverse tabnabbing 차단).
    """
    ref_dir = config.GW_REF_DIR
    pdfs = sorted(ref_dir.glob("*.pdf")) if ref_dir.exists() else []
    if not pdfs:
        return

    try:
        from src.dashboard import pdf_server
        src = pdf_server.DATA_SOURCES.get("gw_ref")
        url_base = src.url_base if src else ""
    except Exception:
        url_base = ""
    if not url_base:
        return

    # (2026-06-11 사용자 확정) 표시 라벨 매핑 — 미등록 파일은 stem 정리 폴백
    _PDF_LABELS = {
        "260607_로버스트 베이지안 적용 가이드라인": "로버스트 베이지안 인포그래픽",
        "260607_로버스트 베이지안 적용": "유역평균 산정 상세 설명자료",
    }
    chips = []
    for p in pdfs:
        label = _PDF_LABELS.get(p.stem)
        if label is None:
            label = p.stem
            # "260607_xxx" → "xxx" (날짜 prefix 제거)
            if "_" in label and label.split("_")[0].isdigit():
                label = label.split("_", 1)[1]
        href = f"{url_base}/{quote(p.name, safe='')}"
        chips.append(
            f'<a href="{href}" target="_blank" rel="noopener noreferrer" '
            f'style="display:inline-block;text-align:center;'
            f'padding:4px 12px;margin:2px 6px 2px 0;'
            f'background:{theme.COLOR_BG_INFO};color:{theme.COLOR_TEXT_INFO};'
            f'border:0.5px solid {theme.COLOR_BORDER_INFO};border-radius:4px;'
            f'font-size:14px;font-weight:600;text-decoration:none;">'
            f'📄 {label}</a>'
        )
    st.markdown(
        f'<div style="display:flex;flex-wrap:wrap;align-items:center;'
        f'margin:2px 0 4px;">'
        f'<span style="font-size:14px;color:{theme.COLOR_TEXT_SECONDARY};'
        f'margin-right:8px;">산정방법 설명자료 :</span>'
        + "".join(chips)
        + '</div>',
        unsafe_allow_html=True,
    )


# ==============================================================================
#  ■ 3. 하단 비교표 — 현행(REF) + A~F 6개 방식 (사용자 요청 2026-06-11)
# ==============================================================================
_METHOD_DESC = {
    "REF": "유역 절대수위 단순평균 차 (구 방식 — 표고·N_drop 왜곡)",
    "A": "관측소 anomaly 단순평균",
    "B": "분산가중 Σ(wᵢaᵢ)/Σwᵢ, wᵢ=1/σᵢ²",
    "C": "완전 패널(분석월+baseline 모두 보유) 관측소만 평균",
    "D": "Tukey Biweight 위치추정 (c=6·MAD) — 부분월 잠정치용",
    "E": "Normal-Normal 계층 MCMC",
    "F": "Student-t 계층 MCMC (본채택 — 공식 표시값)",
}


def render_method_comparison(robust_dict: "dict | None", periods: dict,
                             key_prefix: str):
    """유역(16) × 방법(REF·A~F) 비교표 — 탭 하단 배치.

    기간(M-2/M-1/M 중 캐시 보유분)을 radio 로 선택. F 열 강조(배경 tint +
    굵게 + 95% 신뢰구간 병기). 색상은 부호 기준 (기존 tbl-pos/neg 정책).
    """
    if not robust_dict:
        st.caption(
            "ℹ️ 로버스트-베이지안 메타분석 사전계산 캐시가 없습니다 — "
            "`python scripts/precompute_robust_bayes.py` 실행 후 표시됩니다.")
        return

    # 캐시가 있는 기간만 라디오 후보로
    avail_pks = []
    for pk in ("M-2", "M-1", "M"):
        p = periods.get(pk)
        if not p:
            continue
        if any(pk in (robust_dict.get(w["name"]) or {})
               for w in config.WATERSHEDS):
            avail_pks.append(pk)
    if not avail_pks:
        st.caption("ℹ️ 표시 기간(M-2/M-1/M)에 해당하는 사전계산 캐시가 없습니다.")
        return

    st.markdown(
        f'<p class="section-title">'
        f'<span class="emoji">🧮</span>유역별 산정비교</p>',
        unsafe_allow_html=True,
    )
    render_method_ref_buttons(key_prefix=key_prefix)

    # 기본 선택: 가장 최신 완료월
    default_idx = len(avail_pks) - 1
    pk = st.radio(
        "비교 기간", options=avail_pks, index=default_idx, horizontal=True,
        format_func=lambda k: f"{k} ({periods[k]['label']})",
        key=f"{key_prefix}_cmp_pk", label_visibility="collapsed",
    )

    ws_color = {w["name"]: w["color"] for w in config.WATERSHEDS}
    th_base = (
        'padding:6px 8px;background:var(--color-bg-secondary);'
        'text-align:center;border-bottom:1.5px solid #ccc;'
    )
    th_f = th_base + f'background:{theme.COLOR_BG_INFO};'
    td_base = ('padding:6px 8px;border-bottom:0.5px solid #eee;'
               'text-align:center;')
    td_f = td_base + f'background:{theme.COLOR_BG_INFO}60;'

    head = (
        '<table style="width:100%;border-collapse:collapse;'
        'table-layout:fixed;font-size:15px;">'
        '<colgroup><col style="width:72px;"><col style="width:46px;">'
        + ''.join('<col>' for _ in range(6))
        + '<col style="width:170px;"></colgroup>'
        '<thead><tr>'
        f'<th style="{th_base}">유역</th>'
        f'<th style="{th_base}">N</th>'
        + ''.join(
            f'<th style="{th_base}">{m}<br>'
            f'<span style="font-size:12px;font-weight:400;'
            f'color:var(--color-text-secondary);">{METHOD_LABELS[m]}</span></th>'
            for m in ("REF", "A", "B", "C", "D", "E"))
        + f'<th style="{th_f}">F<br>'
        f'<span style="font-size:12px;font-weight:400;'
        f'color:var(--color-text-secondary);">{METHOD_LABELS["F"]} '
        f'(95% CI)</span></th>'
        '</tr></thead><tbody>'
    )

    body = ""
    for w in config.WATERSHEDS:
        wn = w["name"]
        recs = (robust_dict.get(wn) or {}).get(pk, {})
        if not recs:
            continue
        n = None
        for m in METHODS:
            if m in recs and recs[m].get("n"):
                n = recs[m]["n"]
                break
        cells = (
            f'<td style="{td_base}color:{ws_color.get(wn, "#333")};'
            f'font-weight:600;">{wn}</td>'
            f'<td style="{td_base}font-size:13px;'
            f'color:var(--color-text-secondary);">{n if n else "–"}</td>'
        )
        for m in ("REF", "A", "B", "C", "D", "E"):
            r = recs.get(m)
            v = r.get("편차") if r else None
            cells += (f'<td style="{td_base}">'
                      f'{dev_color_html(v, bold=False)}</td>')
        rf = recs.get("F")
        if rf and rf.get("편차") is not None:
            ci_txt = ""
            if (rf.get("ci_low") is not None
                    and rf.get("ci_high") is not None):
                ci_txt = (f'<div style="font-size:12px;'
                          f'color:var(--color-text-secondary);">'
                          f'[{rf["ci_low"]:+.2f}, {rf["ci_high"]:+.2f}]</div>')
            cells += (f'<td style="{td_f}">'
                      f'{dev_color_html(float(rf["편차"]))}{ci_txt}</td>')
        else:
            cells += f'<td style="{td_f}">–</td>'
        body += f'<tr>{cells}</tr>'

    st.markdown(head + body + "</tbody></table>", unsafe_allow_html=True)

    # 방법 설명 캡션 (expander — 화면 점유 최소화)
    with st.expander("ℹ️ 산정방식 설명 (REF·A~F)", expanded=False):
        st.markdown(
            "\n".join(
                f"- **{m} ({METHOD_LABELS[m]})** — {_METHOD_DESC[m]}"
                for m in METHODS
            )
            + "\n\n- 모든 개선 방식(A~F)은 관측소별 **변화량(anomaly) = "
              "분석월 수위 − 자기 직전 3년 동월 평균** 을 먼저 구해 표고 "
              "이질성·관측소 누락(N_drop) 왜곡을 차단합니다.\n"
              "- **F (본채택)**: yᵢ ~ Student-t(ν, θ_w, σ_w), θ_w ~ N(μ_섬, τ) "
              "— 60개월 검증에서 안정성 SD 3.89→1.17 m (검토보고서 V2)."
        )
    st.markdown(
        '<div style="font-size:14px;color:#888;margin:-2px 0 8px;'
        'text-align:right;">'
        '근거: 제주_지하수위_대표값산정법_종합보고서_V2 · '
        '유역별_변동폭_6개방법_비교 (2026-06-07)</div>',
        unsafe_allow_html=True,
    )

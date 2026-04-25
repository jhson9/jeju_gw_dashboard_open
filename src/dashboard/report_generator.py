# ==============================================================================
#  제주도 지하수위·강수량 분석 대시보드
#  파일명: src/dashboard/report_generator.py
#  모듈: 분석 리포트 HTML 생성 (PDF 저장용)
# ------------------------------------------------------------------------------
#  Build: 1.0.33
# ------------------------------------------------------------------------------
#  【이 파일의 역할】
#  대시보드의 강수량/지하수위 분석 결과를 한 장의 인쇄 친화적 HTML 리포트로
#  내보냅니다. 카드·차트(Plotly inline)·표를 모두 포함하여 A4 인쇄 시 정돈된
#  레이아웃이 되도록 CSS 를 최적화했습니다.
# ==============================================================================

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[2]))

from datetime import datetime, date
from html import escape

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

import config
from src.analysis import effective_rainfall, watershed_mapper
from src.collectors import gwlevel_parser


# ==============================================================================
#  ■ CSS 스타일 (인쇄 최적화 포함)
# ==============================================================================
REPORT_CSS = """
<style>
  @page {
    size: A4;
    margin: 14mm 14mm 18mm 14mm;
    @bottom-right {
      content: counter(page) " / " counter(pages);
      font-family: 'Malgun Gothic', sans-serif;
      font-size: 9pt; color: #5f5e5a;
    }
    @bottom-left {
      content: "제주도 강수량 및 지하수위 분석";
      font-family: 'Malgun Gothic', sans-serif;
      font-size: 9pt; color: #5f5e5a;
    }
  }
  * { box-sizing: border-box; }
  body {
    font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif;
    color: #1a1a18; line-height: 1.5;
    margin: 0; padding: 18px;
    background: #fff; font-size: 11px;
  }
  .report-wrap { max-width: 1080px; margin: 0 auto; }

  /* ── 표지 페이지 ─────────────────── */
  .cover {
    page-break-after: always;
    min-height: 90vh;
    display: flex; flex-direction: column;
    justify-content: center; align-items: center;
    text-align: center;
    background: linear-gradient(135deg, #f5f9fd 0%, #e6f1fb 100%);
    border-radius: 8px;
    padding: 60px 40px 80px;
    margin-bottom: 20px;
    position: relative;
  }
  .cover .badge { font-size: 11px; color: #185fa5; letter-spacing: 0.2em; margin-bottom: 12px; }
  .cover h1 {
    font-size: 38px; color: #185fa5; margin: 0 0 10px;
    border: none; padding: 0; font-weight: 700; letter-spacing: -0.02em;
  }
  .cover .subtitle { font-size: 14px; color: #5f5e5a; margin: 6px 0 36px; }
  .cover .baseinfo { font-size: 16px; color: #1a1a18; margin: 6px 0; }
  .cover .baseinfo strong { color: #185fa5; font-weight: 700; }
  .cover .footer-line {
    margin-top: 60px; padding-top: 14px;
    border-top: 0.5px solid rgba(26,26,24,0.15);
    font-size: 10px; color: #888;
  }
  .cover .developer-line {
    position: absolute;
    bottom: 28px; left: 0; right: 0;
    text-align: center;
    font-size: 12px; color: #5f5e5a;
    letter-spacing: 0.02em;
  }
  .cover .developer-line strong { color: #185fa5; font-weight: 600; }

  /* ── 목차 ──────────────────────── */
  .toc { page-break-after: always; padding: 20px 0; }
  .toc h2 { font-size: 18px; color: #185fa5; border: none; padding: 0; margin: 0 0 14px; }
  .toc ul { list-style: none; padding: 0; margin: 0; }
  .toc li {
    padding: 6px 0;
    border-bottom: 0.5px dashed rgba(26,26,24,0.18);
    font-size: 12px;
  }
  .toc li.lvl2 { font-weight: 600; color: #185fa5; padding-top: 14px; font-size: 13px; }
  .toc li.lvl3 { padding-left: 16px; color: #1a1a18; }
  .toc li.lvl4 { padding-left: 32px; color: #5f5e5a; font-size: 11px; }
  .toc a {
    display: flex; align-items: baseline;
    text-decoration: none; color: inherit;
    gap: 6px;
  }
  .toc a:hover { color: #185fa5; }
  .toc .toc-title  { flex: 0 1 auto; }
  .toc .toc-leader {
    flex: 1 1 auto; min-width: 12px;
    border-bottom: 1px dotted rgba(0,0,0,0.30);
    margin: 0 4px 4px;
    align-self: flex-end;
  }

  h1 {
    font-size: 22px; margin: 0 0 6px;
    border-bottom: 2px solid #185fa5;
    padding-bottom: 8px; color: #185fa5;
  }
  h2 {
    font-size: 18px; margin: 24px 0 10px;
    color: #1a1a18;
    border-left: 4px solid #185fa5;
    padding-left: 12px;
    page-break-before: always;     /* 새 섹션 = 새 페이지 */
    page-break-after: avoid;
  }
  h2:first-of-type { page-break-before: auto; }
  h3 {
    font-size: 14px; margin: 16px 0 8px;
    color: #185fa5; font-weight: 600;
    border-bottom: 0.5px solid #e6f1fb;
    padding-bottom: 4px;
  }
  h4 {
    font-size: 12px; margin: 10px 0 4px;
    color: #5f5e5a; font-weight: 600;
  }

  .meta-box {
    background: #f5f5f3;
    border-left: 3px solid #185fa5;
    padding: 10px 14px;
    margin: 12px 0 16px;
    border-radius: 4px;
  }
  .meta-box .row { display: flex; gap: 14px; flex-wrap: wrap; font-size: 11px; }
  .meta-box .row .item { min-width: 150px; }
  .meta-box .label { color: #5f5e5a; font-size: 10px; }

  /* AWS 카드 4개 */
  .aws-cards {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px; margin: 10px 0;
  }
  .aws-card {
    background: #f5f5f3; border-radius: 6px;
    padding: 8px 10px;
    border-left: 3px solid #888;
  }
  .aws-card .ttl { font-size: 12px; font-weight: 700; }
  .aws-card .sub { font-size: 9px; color: #5f5e5a; margin-bottom: 3px; }
  .aws-card .val { font-size: 18px; font-weight: 600; }
  .aws-card .meta { font-size: 10px; color: #5f5e5a; margin-top: 2px; }

  table {
    width: 100%; border-collapse: collapse;
    font-size: 10.5px; margin: 6px 0 10px;
  }
  th {
    background: #f5f5f3; color: #5f5e5a; font-weight: 600;
    padding: 5px 6px;
    border-bottom: 1.5px solid rgba(26,26,24,0.3);
    text-align: center; white-space: nowrap;
  }
  td {
    padding: 4px 6px;
    border-bottom: 0.5px solid rgba(26,26,24,0.15);
    text-align: center;
  }
  td.lft, th.lft { text-align: left; }
  .caption { font-size: 10px; color: #5f5e5a; margin: 3px 0 8px; }
  .footer {
    margin-top: 28px; padding-top: 8px;
    border-top: 1px solid rgba(26,26,24,0.15);
    font-size: 9px; color: #888780; text-align: center;
  }
  .pos { color: #1d9e75; font-weight: 600; }
  .neg { color: #e24b4a; font-weight: 600; }

  /* ── 유역 블록 — 각 유역마다 새 페이지 + 강조된 헤더 ── */
  .ws-block {
    page-break-before: always;
    page-break-inside: avoid;
    margin: 0 0 18px;
    padding: 14px 18px;
    background: #fafafa;
    border-radius: 8px;
    border-left: 4px solid #185fa5;
  }
  .ws-block:first-of-type { page-break-before: always; }
  .ws-banner {
    background: linear-gradient(90deg, #185fa5 0%, #4a89c6 100%);
    color: #fff;
    padding: 12px 16px;
    border-radius: 6px;
    margin: -14px -18px 12px;
    display: flex; justify-content: space-between; align-items: center;
  }
  .ws-banner .ws-name {
    font-size: 18px; font-weight: 700; letter-spacing: 0.02em;
  }
  .ws-banner .ws-meta {
    font-size: 11px; opacity: 0.92;
  }
  .ws-block h4 { margin-top: 12px; color: #185fa5; font-size: 13px; }
  .ws-block h4:first-of-type { margin-top: 0; }

  /* 인쇄 최적화 */
  @media print {
    body { padding: 0; }
    .no-print { display: none !important; }
    table { page-break-inside: avoid; }
    h2 { page-break-after: avoid; }
    .ws-block { page-break-inside: avoid; }
    .toc, .cover { page-break-after: always; }
  }
  .print-btn { position: sticky; top: 10px; text-align: right; margin-bottom: 6px; z-index: 10; }
  .print-btn button {
    background: #185fa5; color: #fff; border: none;
    padding: 7px 14px; border-radius: 6px; font-size: 12px; cursor: pointer;
    box-shadow: 0 2px 6px rgba(24,95,165,0.25);
  }
</style>
"""


# ==============================================================================
#  ■ 유틸리티
# ==============================================================================
def _fmt(v, decimals=1, default="-"):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return default
    try:
        return f"{int(round(v))}" if decimals == 0 else f"{v:.{decimals}f}"
    except (ValueError, TypeError):
        return default


def _diff_html(actual, avg, decimals=1, unit=""):
    if (actual is None or (isinstance(actual, float) and pd.isna(actual))
            or avg is None or (isinstance(avg, float) and pd.isna(avg))):
        return "-"
    d = actual - avg
    cls = "pos" if d >= 0 else "neg"
    sg = "+" if d >= 0 else ""
    return f'<span class="{cls}">{sg}{d:.{decimals}f}{unit}</span>'


def _hex_alpha(hex_col, alpha):
    h = hex_col.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _fig_to_div(fig, include_plotlyjs=False):
    """Plotly Figure → HTML <div>. plotly.js 는 첫 호출에서만 CDN 로드."""
    return fig.to_html(
        full_html=False,
        include_plotlyjs=("cdn" if include_plotlyjs else False),
        config={"displayModeBar": False},
    )


# ==============================================================================
#  ■ 헤더
# ==============================================================================
def _render_cover(base_date, periods, generated_at):
    """표지 페이지 — 큰 타이틀, 기준일, 기간 요약, 하단 개발자 정보."""
    mode_text = ("매월 1~15일 규칙 (M=전월)"
                 if periods["mode"] == "normal"
                 else "매월 16일 이후 규칙 (M=당월 1~15일 반월)")
    return f"""
<div class="cover">
  <div class="badge">JEJU GROUNDWATER & RAINFALL ANALYSIS</div>
  <h1>🌊 제주도 강수량 및 지하수위 분석</h1>
  <div class="subtitle">월별 강수량 · 농업유효강수일수 · 14개 유역 지하수위 분석</div>
  <div class="baseinfo">기준일&nbsp;&nbsp;<strong>{base_date}</strong></div>
  <div class="baseinfo" style="font-size:13px;color:#5f5e5a;">
    분석 기간 :
    M-2 {periods['M-2']['label']} ·
    M-1 {periods['M-1']['label']} ·
    M {periods['M']['label']}
  </div>
  <div class="baseinfo" style="font-size:11px;color:#888;">{mode_text}</div>
  <div class="footer-line">
    생성 {generated_at.strftime('%Y-%m-%d %H:%M')} ·
    Build {config.BUILD_VERSION} ·
    데이터 출처: 기상청 ASOS / 제주특별자치도 지하수정보관리시스템
  </div>
  <div class="developer-line">
    개발자 : <strong>손주형</strong> (jhson9@gmail.com)
  </div>
</div>
"""


def _render_toc(ws_data_all):
    """목차 — 섹션·유역 앵커 + 페이지 번호.

    PagedJS 폴리필이 .toc a::after { content: target-counter(...) } 를 해석해
    각 항목 우측에 실제 출력될 페이지 번호를 채워준다.
    """
    def entry(cls, href, label):
        return (f'<li class="{cls}">'
                f'<a href="#{href}">'
                f'<span class="toc-title">{label}</span>'
                f'<span class="toc-leader"></span>'
                f'</a></li>')
    items = [
        entry("lvl2", "sec-rain", "🌧️ 강수량 분석"),
        entry("lvl3", "sub-aws-cards", "AWS 지점별 강수량 (M-2 · M-1 · M)"),
        entry("lvl3", "sub-rain-chart", "월별 강수량 : 4개 AWS (mm)"),
        entry("lvl3", "sub-rain-table", "강수량 비교표"),
        entry("lvl3", "sub-eff-chart", "월별 농업유효 강수일수 (일)"),
        entry("lvl3", "sub-eff-table", "농업유효강수일수 비교표"),
        entry("lvl2", "sec-gw", "💧 지하수위 분석"),
        entry("lvl3", "sub-overall-diff", "유역별 지하수위(EL) 변동 — 최근 3개월 편차"),
        entry("lvl3", "sub-ws-detail", "유역별 상세 분석"),
    ]
    if ws_data_all:
        for w in config.WATERSHEDS:
            wn = w["name"]
            slug = f"ws-{wn}"
            items.append(entry("lvl4", slug, f"　• {escape(wn)} 유역"))
    return f"""
<div class="toc">
  <h2>📑 목차</h2>
  <ul>
    {''.join(items)}
  </ul>
</div>
"""


# ==============================================================================
#  ■ 강수량 분석 섹션
# ==============================================================================
def _render_aws_cards(asos_df, periods):
    """대시보드 요약의 AWS 강수량 카드 4개를 HTML 로 재현."""
    if asos_df is None or asos_df.empty:
        return "<p class='caption'>ASOS 데이터 없음</p>"
    monthly = effective_rainfall.aggregate_monthly(asos_df)
    half = effective_rainfall.aggregate_half_monthly(asos_df)

    cards = []
    for s in config.STATIONS_ASOS:
        st_name = s["name"]
        col = s["color"]
        rows_html = ""
        for key in ["M-2", "M-1", "M"]:
            p = periods[key]
            actual = effective_rainfall.get_period_value(monthly, half, p, st_name, "월강수량(mm)")
            avg, used_years = effective_rainfall.get_baseline_average(
                monthly, half, p, st_name, "월강수량(mm)")
            if used_years:
                bl_short = f"{str(used_years[0])[2:]}~{str(used_years[-1])[2:]}"
            else:
                bl = list(range(p["year"] - config.RAINFALL_BASELINE_YEARS, p["year"]))
                bl_short = f"{str(bl[0])[2:]}~{str(bl[-1])[2:]}"
            actual_str = f"{actual:.1f} mm" if actual is not None else "-"
            avg_str = f"{bl_short}년 {p['month']}월 평균: " + (
                f"{avg:.1f} mm" if avg is not None else "-")
            diff_str = _diff_html(actual, avg, 1, "mm")
            rows_html += (
                f'<div style="padding:4px 0;border-top:0.5px dashed rgba(26,26,24,0.15);">'
                f'<div style="font-size:10px;color:#5f5e5a;font-weight:500;">'
                f'{p["label"]} ({key})</div>'
                f'<div style="font-size:13px;font-weight:600;color:{col};">'
                f'{actual_str}</div>'
                f'<div style="font-size:9.5px;color:#5f5e5a;">'
                f'{avg_str} | {diff_str}</div>'
                f'</div>'
            )
        cards.append(
            f'<div class="aws-card" style="border-left-color:{col};background:{_hex_alpha(col, 0.08)};">'
            f'<div class="ttl" style="color:{col};">{escape(st_name)} ({s["id"]})</div>'
            f'<div class="sub">최근 3개월 월강수량</div>'
            f'{rows_html}'
            f'</div>'
        )
    return f'<div class="aws-cards">{"".join(cards)}</div>'


def _build_rainfall_chart(asos_df, periods, metric="rain"):
    """4개 지점 1×4 grouped 막대(평균 vs 실측). metric: 'rain' or 'eff'."""
    if asos_df is None or asos_df.empty:
        return ""
    monthly = effective_rainfall.aggregate_monthly(asos_df)
    half = effective_rainfall.aggregate_half_monthly(asos_df)
    ps_keys = ["M-2", "M-1", "M"]
    ps = [periods[k] for k in ps_keys]
    n_rain = config.RAINFALL_BASELINE_YEARS
    xlabels = [f"{p['month']}월 ({k})" for k, p in zip(ps_keys, ps)]
    metric_col = "월강수량(mm)" if metric == "rain" else "유효강수일수(일)"
    unit = "mm" if metric == "rain" else "일"
    decimals = 0

    fig = make_subplots(rows=1, cols=4, shared_yaxes=False,
                        horizontal_spacing=0.04,
                        subplot_titles=[f"{s['name']} ({s['id']})" for s in config.STATIONS_ASOS])
    for i, s in enumerate(config.STATIONS_ASOS, start=1):
        sn, col = s["name"], s["color"]
        rain_a = [effective_rainfall.get_period_value(monthly, half, p, sn, metric_col) for p in ps]
        rain_v = [effective_rainfall.get_baseline_average(monthly, half, p, sn, metric_col, n_years=n_rain)[0] for p in ps]
        fig.add_trace(go.Bar(
            name=f"과거 {n_rain}년 평균", x=xlabels, y=rain_v,
            marker=dict(color=_hex_alpha(col, 0.18), line=dict(color=col, width=1.5)),
            text=[_fmt(v, decimals) if v is not None else "" for v in rain_v],
            textposition="outside", textfont=dict(size=9, color="#5f5e5a"),
            cliponaxis=False, showlegend=(i == 1), legendgroup="avg",
            hovertemplate=f"%{{x}}<br>과거평균: %{{y:.{decimals}f}} {unit}<extra></extra>",
        ), row=1, col=i)
        fig.add_trace(go.Bar(
            name="최근", x=xlabels, y=rain_a,
            marker=dict(color=col),
            text=[_fmt(v, decimals) if v is not None else "" for v in rain_a],
            textposition="outside", textfont=dict(size=9, color="#1a1a18"),
            cliponaxis=False, showlegend=(i == 1), legendgroup="act",
            hovertemplate=f"%{{x}}<br>최근: %{{y:.{decimals}f}} {unit}<extra></extra>",
        ), row=1, col=i)
    for i in range(1, 5):
        fig.update_yaxes(title_text=unit if i == 1 else "", row=1, col=i)
    fig.update_annotations(font_size=11)
    fig.update_layout(
        height=240, barmode="group", bargap=0.3, bargroupgap=0.15,
        margin=dict(t=30, b=8, l=40, r=10),
        legend=dict(orientation="h", yanchor="top", y=1.18, xanchor="center", x=0.5,
                    font=dict(size=10)),
        font=dict(size=10),
    )
    return _fig_to_div(fig, include_plotlyjs=True)


def _build_aws_table(asos_df, periods, metric="rain"):
    if asos_df is None or asos_df.empty:
        return ""
    monthly = effective_rainfall.aggregate_monthly(asos_df)
    half = effective_rainfall.aggregate_half_monthly(asos_df)
    ps_keys = ["M-2", "M-1", "M"]
    ps = [periods[k] for k in ps_keys]
    n = config.RAINFALL_BASELINE_YEARS
    metric_col = "월강수량(mm)" if metric == "rain" else "유효강수일수(일)"
    unit = "mm" if metric == "rain" else "일"
    dec = 0

    stations = config.STATIONS_ASOS
    head = ('<tr>'
            '<th rowspan="2">기간</th>'
            + "".join(f'<th colspan="3" style="color:{s["color"]};">{escape(s["name"])} ({s["id"]})</th>'
                      for s in stations)
            + '</tr>'
            '<tr>'
            + "".join('<th>최근</th><th>평균</th><th>편차</th>' for _ in stations)
            + '</tr>')
    body_rows = []
    for pk, p in zip(ps_keys, ps):
        cells = [f'<td><strong>{p["month"]}월</strong><br><span style="font-size:9px;color:#5f5e5a;">({pk})</span></td>']
        for s in stations:
            sn = s["name"]
            a = effective_rainfall.get_period_value(monthly, half, p, sn, metric_col)
            v, _ = effective_rainfall.get_baseline_average(monthly, half, p, sn, metric_col, n_years=n)
            cells.append(f'<td><strong>{_fmt(a, dec)}</strong></td>')
            cells.append(f'<td>{_fmt(v, dec)}</td>')
            cells.append(f'<td>{_diff_html(a, v, dec)}</td>')
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    title = "강수량 비교표 (mm)" if metric == "rain" else "농업유효강수일수 비교표 (일)"
    return f'<h4>{title}</h4><table><thead>{head}</thead><tbody>{"".join(body_rows)}</tbody></table>'


# ==============================================================================
#  ■ 지하수위 분석 — 14개 유역 종합 차트 (대시보드 요약)
# ==============================================================================
def _build_overall_diff_chart(ws_data_all, periods):
    """14개 유역 × M-2/M-1/M 편차(현재 - 과거 3년 평균) 그룹드 바."""
    n_gw = config.GWLEVEL_BASELINE_YEARS
    ps_keys = ["M-2", "M-1", "M"]
    ps_list = [periods[k] for k in ps_keys]

    region_map = {
        "구좌": "동부", "성산": "동부", "표선": "동부",
        "대정": "서부", "한경": "서부", "한림": "서부",
        "남원": "남부", "동서귀": "남부", "중서귀": "남부", "서서귀": "남부",
        "동제주": "북부", "중제주": "북부", "서제주": "북부", "조천": "북부",
    }
    region_color = {"동부": "#E24B4A", "서부": "#BA7517", "남부": "#1D9E75", "북부": "#378ADD"}
    period_alpha = {"M-2": 0.35, "M-1": 0.65, "M": 1.0}

    diff_table = {}
    for w in config.WATERSHEDS:
        wn = w["name"]
        df_w = ws_data_all.get(wn, pd.DataFrame()) if ws_data_all else pd.DataFrame()
        if df_w.empty:
            continue
        per = {}
        for pk, p in zip(ps_keys, ps_list):
            ym = f"{p['year']}-{p['month']:02d}"
            bl = list(range(p["year"] - n_gw, p["year"]))
            ra = df_w[df_w["연월"] == ym]
            if ra.empty:
                continue
            actual = float(ra["EL_평균"].iloc[0])
            bv = []
            for y in bl:
                rb = df_w[df_w["연월"] == f"{y}-{p['month']:02d}"]
                if not rb.empty:
                    v = float(rb["EL_평균"].iloc[0])
                    if pd.notna(v):
                        bv.append(v)
            if not bv:
                continue
            per[pk] = round(actual - sum(bv)/len(bv), 2)
        if per:
            diff_table[wn] = per
    if not diff_table:
        return ""

    ws_order = [w["name"] for w in config.WATERSHEDS if w["name"] in diff_table]
    fig = go.Figure()
    for pk in ps_keys:
        ys, txt, colors = [], [], []
        for w in ws_order:
            v = diff_table[w].get(pk)
            ys.append(v)
            txt.append(f"{'+' if (v is not None and v > 0) else ''}{v:.2f}" if v is not None else "")
            base = region_color[region_map.get(w, "북부")]
            colors.append(_hex_alpha(base, period_alpha[pk]))
        fig.add_trace(go.Bar(
            name=pk, x=ws_order, y=ys,
            marker=dict(color=colors, line=dict(color="rgba(255,255,255,1)", width=1)),
            text=txt, textposition="outside", textfont=dict(size=9),
            cliponaxis=False, width=0.22,
            hovertemplate=f"{pk}<br>%{{x}}<br>편차: %{{y:.2f}} m<extra></extra>",
            showlegend=False,
        ))
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    short_m = ", ".join(f"{str(p['year'])[2:]}년 {p['month']}월" for p in ps_list)
    fig.update_layout(
        height=320, barmode="group", bargap=0.25, bargroupgap=0.18,
        title=dict(text=f"유역별 지하수위(EL) 변동 — 최근 3개월 ({short_m}) 편차", font=dict(size=12), x=0.01),
        xaxis_title="", yaxis_title=f"현재 EL - 과거 {n_gw}년 평균 EL (m)",
        yaxis=dict(range=[-5, 5], zeroline=True),
        margin=dict(t=40, b=20, l=60, r=20), font=dict(size=10),
    )
    return _fig_to_div(fig)


# ==============================================================================
#  ■ 유역별 지하수위 분석 (Tab 4 의 컨텐츠)
# ==============================================================================
def _build_ws_bar(ws_df, periods, ws_col):
    """유역의 M-2/M-1/M × (과거평균 vs 실측) grouped bar."""
    n_gw = config.GWLEVEL_BASELINE_YEARS
    ps_keys = ["M-2", "M-1", "M"]
    ps = [periods[k] for k in ps_keys]
    xlabels = [f"{p['month']}월 ({k})" for k, p in zip(ps_keys, ps)]
    act_v, avg_v = [], []
    for p in ps:
        ym = f"{p['year']}-{p['month']:02d}"
        bl = list(range(p["year"] - n_gw, p["year"]))
        ra = ws_df[ws_df["연월"] == ym]
        act_v.append(float(ra["EL_평균"].iloc[0]) if not ra.empty else None)
        bv = [float(ws_df[ws_df["연월"] == f"{y}-{p['month']:02d}"]["EL_평균"].iloc[0])
              for y in bl
              if not ws_df[ws_df["연월"] == f"{y}-{p['month']:02d}"].empty]
        avg_v.append(sum(bv)/len(bv) if bv else None)
    all_v = [v for v in act_v + avg_v if v is not None]
    y_min = min(all_v) * 0.96 if all_v else 0
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name=f"과거 {n_gw}년 해당월 평균", x=xlabels, y=avg_v,
        marker=dict(color=_hex_alpha(ws_col, 0.18), line=dict(color=ws_col, width=1.5)),
        text=[f"{v:.2f}" if v is not None else "" for v in avg_v],
        textposition="outside", textfont=dict(size=9, color="#5f5e5a"),
        cliponaxis=False,
    ))
    fig.add_trace(go.Bar(
        name="최근 지하수위", x=xlabels, y=act_v,
        marker=dict(color=ws_col),
        text=[f"{v:.2f}" if v is not None else "" for v in act_v],
        textposition="outside", textfont=dict(size=9, color="#1a1a18"),
        cliponaxis=False,
    ))
    fig.update_layout(
        barmode="group", height=180,
        bargap=0.35, bargroupgap=0.18,
        xaxis_title="", yaxis_title="m",
        yaxis=dict(range=[y_min, None]),
        margin=dict(t=4, b=4, l=38, r=8),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0.0, font=dict(size=9)),
        font=dict(size=10),
    )
    return _fig_to_div(fig)


def _build_ws_trend(ws_df, periods, ws_col):
    """유역의 EL 시계열 (최근 60개월)."""
    if ws_df is None or ws_df.empty:
        return ""
    plot_df = ws_df.copy().sort_values("연월")
    if len(plot_df) > 60:
        plot_df = plot_df.tail(60)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=plot_df["연월"], y=plot_df["EL_평균"],
        mode="lines+markers",
        line=dict(color=ws_col, width=1.5), marker=dict(size=3),
        hovertemplate="%{x}<br>EL: %{y:.2f} m<extra></extra>",
    ))
    m_ym = f"{periods['M']['year']}-{periods['M']['month']:02d}"
    m_row = plot_df[plot_df["연월"] == m_ym]
    if not m_row.empty:
        fig.add_trace(go.Scatter(
            x=m_row["연월"], y=m_row["EL_평균"],
            mode="markers+text",
            marker=dict(color="#e24b4a", size=8, line=dict(color="white", width=2)),
            text=["M"], textposition="top center",
            textfont=dict(color="#e24b4a", size=10),
            showlegend=False,
        ))
    fig.update_layout(
        height=180, xaxis_title="", yaxis_title="EL (m)",
        margin=dict(t=4, b=4, l=40, r=10),
        showlegend=False, font=dict(size=10),
    )
    return _fig_to_div(fig)


def _build_ws_detail_table(ws_df, periods):
    n_gw = config.GWLEVEL_BASELINE_YEARS
    ps_keys = ["M-2", "M-1", "M"]
    ps = [periods[k] for k in ps_keys]
    rows = []
    for pk, p in zip(ps_keys, ps):
        ym = f"{p['year']}-{p['month']:02d}"
        bl = list(range(p["year"] - n_gw, p["year"]))
        ra = ws_df[ws_df["연월"] == ym]
        actual = float(ra["EL_평균"].iloc[0]) if not ra.empty else None
        bv = [float(ws_df[ws_df["연월"] == f"{y}-{p['month']:02d}"]["EL_평균"].iloc[0])
              for y in bl
              if not ws_df[ws_df["연월"] == f"{y}-{p['month']:02d}"].empty]
        avg = sum(bv)/len(bv) if bv else None
        rows.append((pk, p, actual, avg))
    head = (
        '<tr>'
        '<th>기간</th>'
        '<th>최근 월 수위 (m)</th>'
        f'<th>과거 {n_gw}년 해당월 평균 (m)</th>'
        '<th>지하수위 편차 (m)</th>'
        '</tr>'
    )
    body = []
    for pk, p, a, v in rows:
        body.append(
            f'<tr>'
            f'<td><strong>{p["month"]}월</strong> ({pk})</td>'
            f'<td><strong>{_fmt(a, 2)}</strong></td>'
            f'<td>{_fmt(v, 2)}</td>'
            f'<td>{_diff_html(a, v, 2)}</td>'
            f'</tr>'
        )
    return f'<h4>지하수위(EL) 현황</h4><table><thead>{head}</thead><tbody>{"".join(body)}</tbody></table>'


def _build_stations_chart_table(sel, periods, station_df, ws_to_stations):
    """관측정별 그룹드 바 + 상세 표."""
    if station_df is None or station_df.empty or not ws_to_stations:
        return ""
    stations_all = ws_to_stations.get(sel, [])
    stations = [s for s in stations_all
                if s in station_df["관측소명"].unique().tolist()]
    if not stations:
        return ""
    n_gw = config.GWLEVEL_BASELINE_YEARS
    ps_keys = ["M-2", "M-1", "M"]
    ps = [periods[k] for k in ps_keys]
    period_alpha = {"M-2": 0.35, "M-1": 0.65, "M": 1.0}
    palette = px.colors.qualitative.Plotly + px.colors.qualitative.Dark24
    station_colors = {stn: palette[i % len(palette)] for i, stn in enumerate(stations)}

    # 데이터
    stn_data = {}
    for stn in stations:
        df_s = station_df[station_df["관측소명"] == stn]
        per = {}
        for pk, p in zip(ps_keys, ps):
            ym = f"{p['year']}-{p['month']:02d}"
            bl = list(range(p["year"] - n_gw, p["year"]))
            ra = df_s[df_s["연월"] == ym]
            actual = float(ra["EL"].iloc[0]) if not ra.empty else None
            bv = [float(df_s[df_s["연월"] == f"{y}-{p['month']:02d}"]["EL"].iloc[0])
                  for y in bl
                  if not df_s[df_s["연월"] == f"{y}-{p['month']:02d}"].empty]
            avg = sum(bv)/len(bv) if bv else None
            per[pk] = {"actual": actual, "avg": avg}
        stn_data[stn] = per

    # 차트
    fig = go.Figure()
    for pk in ps_keys:
        ys, txt, colors = [], [], []
        for stn in stations:
            v = stn_data[stn][pk]["actual"]
            ys.append(v)
            txt.append(f"{v:.2f}" if v is not None else "")
            colors.append(_hex_alpha(station_colors[stn], period_alpha[pk]))
        fig.add_trace(go.Bar(
            name=pk, x=stations, y=ys,
            marker=dict(color=colors, line=dict(color="rgba(255,255,255,1)", width=1)),
            text=txt, textposition="outside", textfont=dict(size=8),
            cliponaxis=False, width=0.22, showlegend=False,
        ))
    all_vals = [stn_data[s][pk]["actual"] for s in stations for pk in ps_keys
                if stn_data[s][pk]["actual"] is not None]
    if all_vals:
        y_min, y_max = min(all_vals), max(all_vals)
        pad = max((y_max - y_min) * 0.12, 0.5)
        y_range = [y_min - pad, y_max + pad]
    else:
        y_range = None
    fig.update_layout(
        height=220, barmode="group", bargap=0.25, bargroupgap=0.18,
        xaxis_title="", yaxis_title="EL (m)",
        xaxis=dict(categoryorder="array", categoryarray=stations,
                   tickfont=dict(size=9)),
        yaxis=dict(range=y_range) if y_range else dict(),
        margin=dict(t=4, b=20, l=40, r=10),
        font=dict(size=10),
    )
    chart_html = _fig_to_div(fig)

    # 표
    head = (
        '<tr>'
        '<th rowspan="2">관측정</th>'
        + "".join(f'<th colspan="3">{p["month"]}월 ({pk})</th>'
                  for pk, p in zip(ps_keys, ps))
        + '</tr>'
        '<tr>'
        + "".join('<th>최근</th><th>과거 평균</th><th>편차</th>' for _ in ps_keys)
        + '</tr>'
    )
    body = []
    for stn in stations:
        cells = [f'<td><strong>{escape(stn)}</strong></td>']
        for pk in ps_keys:
            a = stn_data[stn][pk]["actual"]
            v = stn_data[stn][pk]["avg"]
            cells.append(f'<td><strong>{_fmt(a, 2)}</strong></td>')
            cells.append(f'<td>{_fmt(v, 2)}</td>')
            cells.append(f'<td>{_diff_html(a, v, 2)}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    table_html = (
        f'<h4>관측정별 상세 ({len(stations)}개 관측정)</h4>'
        f'<table><thead>{head}</thead><tbody>{"".join(body)}</tbody></table>'
    )
    return (f'<h4>관측정별 지하수위(EL)</h4>'
            f'{chart_html}'
            f'{table_html}')


def _render_watershed_section(sel, periods, ws_data_all, station_df, ws_to_stations):
    """단일 유역의 모든 분석 콘텐츠 블록 — 새 페이지에서 시작, 큰 배너로 유역명 강조."""
    ws_color = {w["name"]: w["color"] for w in config.WATERSHEDS}
    ws_aws = {w["name"]: w["aws"] for w in config.WATERSHEDS}
    nearby = ws_aws.get(sel, "")
    ws_col = ws_color.get(sel, "#185fa5")
    ws_df = ws_data_all.get(sel) if ws_data_all else None
    slug = f"ws-{sel}"

    if ws_df is None or ws_df.empty:
        return (
            f'<div class="ws-block" id="{slug}">'
            f'<div class="ws-banner" style="background:linear-gradient(90deg,{ws_col} 0%,#888 100%);">'
            f'<div class="ws-name">{escape(sel)} 유역</div>'
            f'<div class="ws-meta">인근 AWS : {escape(nearby)}</div>'
            f'</div>'
            f'<p class="caption">{sel} 유역 데이터가 없습니다.</p>'
            f'</div>'
        )

    bar = _build_ws_bar(ws_df, periods, ws_col)
    detail = _build_ws_detail_table(ws_df, periods)
    trend = _build_ws_trend(ws_df, periods, ws_col)
    stations_block = _build_stations_chart_table(sel, periods, station_df, ws_to_stations) \
        if station_df is not None else ""

    # 유역 색상으로 배너 그라데이션
    return f"""
<div class="ws-block" id="{slug}">
  <div class="ws-banner" style="background:linear-gradient(90deg,{ws_col} 0%,#185fa5 100%);">
    <div class="ws-name">📍 {escape(sel)} 유역</div>
    <div class="ws-meta">인근 AWS : <strong>{escape(nearby)}</strong></div>
  </div>
  <h4>지하수위(EL) — 최근 3개월 vs 과거 3년 평균</h4>
  {bar}
  {detail}
  <h4>지하수위(EL) 추이 (최근 60개월)</h4>
  {trend}
  {stations_block}
</div>
"""


# ==============================================================================
#  ■ 메인: HTML 리포트 생성
# ==============================================================================
def build_report_html(base_date, periods,
                      asos_df=None, ws_data_all=None,
                      rainfall_table=None, effective_table=None,
                      gwlevel_table=None, title=None) -> str:
    """전체 리포트 HTML 문자열 생성.

    asos_df, ws_data_all 이 주어지면 차트 포함 풀 리포트.
    이전 시그니처 호환을 위해 rainfall_table 등 인자도 그대로 받음(미사용).
    """
    generated_at = datetime.now()

    # 관측정 데이터 (선택적)
    try:
        station_df = gwlevel_parser.load_all_station_data()
        ws_to_stations = watershed_mapper.get_watershed_to_stations_map()
    except Exception:
        station_df = pd.DataFrame()
        ws_to_stations = {}

    parts = []
    # 표지 + 목차
    parts.append(_render_cover(base_date, periods, generated_at))
    parts.append(_render_toc(ws_data_all))

    # ── 강수량 분석 ─────────────────────────────────────
    parts.append('<h2 id="sec-rain">🌧️ 강수량 분석</h2>')
    parts.append('<h3 id="sub-aws-cards">AWS 지점별 강수량 (M-2 · M-1 · M)</h3>')
    parts.append(_render_aws_cards(asos_df, periods))
    parts.append('<h3 id="sub-rain-chart">월별 강수량 : 4개 AWS (mm)</h3>')
    parts.append(_build_rainfall_chart(asos_df, periods, metric="rain"))
    parts.append('<h4 id="sub-rain-table">강수량 비교표</h4>')
    parts.append(_build_aws_table(asos_df, periods, metric="rain"))
    parts.append('<h3 id="sub-eff-chart">월별 농업유효 강수일수 (일)</h3>')
    parts.append(f'<p class="caption">기준: 일강수량 {config.EFFECTIVE_RAINFALL_THRESHOLD_MM} mm 이상</p>')
    parts.append(_build_rainfall_chart(asos_df, periods, metric="eff"))
    parts.append('<h4 id="sub-eff-table">농업유효강수일수 비교표</h4>')
    parts.append(_build_aws_table(asos_df, periods, metric="eff"))

    # ── 지하수위 분석 ───────────────────────────────────
    parts.append('<h2 id="sec-gw">💧 지하수위 분석</h2>')
    parts.append('<h3 id="sub-overall-diff">유역별 지하수위(EL) 변동 — 최근 3개월 편차</h3>')
    parts.append(_build_overall_diff_chart(ws_data_all, periods))

    # 14개 유역 각각의 상세
    if ws_data_all:
        parts.append('<h3 id="sub-ws-detail">유역별 상세 분석</h3>')
        for w in config.WATERSHEDS:
            parts.append(_render_watershed_section(
                w["name"], periods, ws_data_all, station_df, ws_to_stations
            ))

    parts.append(_render_footer(generated_at))

    print_button = (
        '<div class="print-btn no-print">'
        '<button onclick="window.print()">🖨️ 인쇄 / PDF 저장</button>'
        '</div>'
    )

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>제주도 강수량 및 지하수위 분석 — {base_date}</title>
{REPORT_CSS}
</head>
<body>
<div class="report-wrap">
{print_button}
{''.join(parts)}
</div>
</body>
</html>
"""
    return html


def _render_footer(generated_at):
    return f"""
<div class="footer">
  <p>생성: {generated_at.strftime('%Y-%m-%d %H:%M:%S')} |
  제주도 강수량 및 지하수위 분석 대시보드 Build {config.BUILD_VERSION} |
  데이터 출처: 기상청 ASOS / 제주특별자치도 지하수정보관리시스템(water.jeju.go.kr)</p>
</div>
"""


# ==============================================================================
#  ■ 파일 저장
# ==============================================================================
def save_report_to_file(html: str, base_date) -> Path:
    report_dir = config.DATA_DIR / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"report_{base_date}_{timestamp}.html"
    out_path = report_dir / filename
    out_path.write_text(html, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    from src.analysis import period_calculator
    base = date.today()
    periods = period_calculator.compute_periods(base_date=base)
    html = build_report_html(base, periods)
    out = save_report_to_file(html, base)
    print(f"✅ 테스트 리포트 생성: {out}")

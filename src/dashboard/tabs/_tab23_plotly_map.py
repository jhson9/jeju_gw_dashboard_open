# ==============================================================================
#  파일명: src/dashboard/tabs/_tab23_plotly_map.py
#  ⑧-2 이용량 지도분석 — plotly choropleth_mapbox (folium 우회 대안)
#
#  설계 결정 (2026-05-20):
#    오류분석팀 1·3 진단 결과 — folium + streamlit-folium 의 use_container_width
#    + fragment 컨테이너 width=0 충돌로 폴리곤이 회색 빈 박스로만 렌더됨.
#    여러 단계 패치에도 사용자 환경에서 표시 불가.
#
#    plotly choropleth_mapbox 는:
#      - streamlit 의 st.plotly_chart 네이티브 통합 (iframe 충돌 없음)
#      - mapbox_style='open-street-map' 으로 토큰 없이 베이스맵
#      - GeoJSON 폴리곤 정상 렌더 (이미 ⑧-2 의 월별 차트가 plotly 잘 작동)
#      - 색상 스케일 + hover 정보 + 인터랙티브 줌·팬 모두 지원
#
#  ⑧ 탭 (squarify treemap) 과 차별점: 실제 행정구역 지리 경계 표시.
# ==============================================================================
from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.dashboard.figures._dual_zone_common.color import (
    DAILY_USAGE_COLORSCALE,
    DAILY_USAGE_VMAX,
    DAILY_USAGE_VMIN,
)
from src.dashboard.figures.admin_dual_zone.constants import ADMIN_AGRI_HA
from src.dashboard.tabs._tab23_helpers import (
    load_eup_geojson,
    load_ri_geojson,
)
# 2026-05-29 P3-1: _tab23_map.py 모듈 전체가 dead 였음(folium 폴리곤 choropleth
# 구현체 미사용). 본 plotly 모듈만 사용하므로 _bbox_center 헬퍼 3개를 인라인화
# 후 _tab23_map.py 는 _archive 로 이동.
def _ring_area(ring: list) -> float:
    """Shoelace 공식으로 ring 면적 절댓값 (deg² 기준 — 비교용)."""
    n = len(ring)
    if n < 3:
        return 0.0
    a = 0.0
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def _ring_centroid(ring: list) -> "tuple[float, float] | None":
    """ring 의 무게중심 (lon, lat). bbox 평균보다 모양에 충실."""
    n = len(ring)
    if n < 3:
        return None
    sx = sy = sa = 0.0
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        cross = x1 * y2 - x2 * y1
        sa += cross
        sx += (x1 + x2) * cross
        sy += (y1 + y2) * cross
    a = sa / 2.0
    if abs(a) < 1e-12:
        # 면적 0 — bbox 평균으로 폴백
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return (sum(xs) / len(xs), sum(ys) / len(ys))
    return (sx / (6.0 * a), sy / (6.0 * a))


def _bbox_center(geom: dict) -> "tuple[float, float] | None":
    """폴리곤 중심 (lat, lon). MultiPolygon 본영역(가장 큰 ring) 무게중심.
    부속도서가 중심을 끌어당기는 문제 회피 (검증팀3 Critical-3 fix).
    """
    rings_with_area: list = []
    if geom.get("type") == "Polygon":
        for ring in geom.get("coordinates", []):
            rings_with_area.append((_ring_area(ring), ring))
    elif geom.get("type") == "MultiPolygon":
        for poly in geom.get("coordinates", []):
            if poly:
                rings_with_area.append((_ring_area(poly[0]), poly[0]))
    if not rings_with_area:
        return None
    rings_with_area.sort(key=lambda x: x[0], reverse=True)
    biggest_ring = rings_with_area[0][1]
    c = _ring_centroid(biggest_ring)
    if c is None:
        return None
    lon, lat = c
    return (lat, lon)


# ⑧-2 의 NAME ↔ ⑧ 탭 cluster 키 (ADMIN_AGRI_HA 조회용)
_EUP_NAME_TO_CLUSTER: dict[str, str] = {
    "한경면": "제주시 한경면", "한림읍": "제주시 한림읍",
    "애월읍": "제주시 애월읍", "조천읍": "제주시 조천읍",
    "구좌읍": "제주시 구좌읍", "제주시 동지역": "제주시 동지역",
    "대정읍": "서귀포시 대정읍", "안덕면": "서귀포시 안덕면",
    "남원읍": "서귀포시 남원읍", "표선면": "서귀포시 표선면",
    "성산읍": "서귀포시 성산읍", "서귀포시 동지역": "서귀포시 동지역",
}


def _add_well_markers(
    fig, master_df, df_long, period_lo: int, period_hi: int, mode: str,
) -> None:
    """각 관정을 점으로 표시 (사용자 요청 2026-05-20).

    - 점 크기: 고정 (사용량 무관, 사용자 명시)
    - 점 색상: 관정의 분석기간 일사용량 (㎥/공·일) → DAILY_USAGE_COLORSCALE
              choropleth 컬러바와 동일 스케일 (cmin=0, cmax=1600)
    - hover: 관정번호 + well_id + 사용량
    """
    import pandas as pd

    if master_df is None or master_df.empty:
        return

    days = max(1, period_hi - period_lo + 1)  # 월 단위 — 정확한 일수는 별도 계산
    from src.dashboard.tabs._tab23_helpers import _days_in_period
    days = max(1, _days_in_period(period_lo, period_hi))

    # 각 관정의 분석기간 사용량 합 → 일사용량
    if df_long is not None and not df_long.empty:
        g = df_long.groupby("permit_no")["volume_m3"].sum()
    else:
        g = pd.Series(dtype=float)

    # master 의 lat/lon 가 있고 active 인 관정만
    mf = master_df[master_df["lat"].notna() & master_df["lon"].notna()].copy()
    mf["sum_m3"] = mf["permit_no"].astype(str).map(g).fillna(0.0)
    mf["per_well_day"] = mf["sum_m3"] / days

    # mode='per_well' 일 때만 색상 매핑 활성. 'abs' 모드에서도 일사용량 기반으로
    # 일관되게 표시 (사용자 요청: "옆 컬러바와 같은 색").
    if mode == "per_well":
        cmin_v, cmax_v = DAILY_USAGE_VMIN, DAILY_USAGE_VMAX
    else:
        cmin_v, cmax_v = DAILY_USAGE_VMIN, DAILY_USAGE_VMAX

    # 1) 외곽선 trace — 검정 큰 원이 색상 마커 아래에 깔려 1px 검정 테두리 효과.
    #    Scattermapbox 는 marker.line 미지원이라 2단 trace 겹치기로 구현.
    fig.add_trace(go.Scattermapbox(
        lat=mf["lat"].tolist(),
        lon=mf["lon"].tolist(),
        mode="markers",
        marker=dict(
            size=12,                              # 색상 trace 보다 2px 큼 → 양쪽 1px 외곽
            color="#000000",
            opacity=1.0,
        ),
        hoverinfo="skip",
        showlegend=False,
        name="",
    ))

    # 2) 색상 마커 trace — 8 → 10 (사용자 요청: 1단계 크게).
    fig.add_trace(go.Scattermapbox(
        lat=mf["lat"].tolist(),
        lon=mf["lon"].tolist(),
        mode="markers",
        marker=dict(
            size=10,                              # 8 → 10 (1단계 크게)
            color=mf["per_well_day"].tolist(),
            colorscale=DAILY_USAGE_COLORSCALE,
            cmin=cmin_v, cmax=cmax_v,
            opacity=1.0,                          # 외곽선이 색에 섞이지 않도록 불투명
            showscale=False,                      # choropleth 컬러바와 중복 회피
        ),
        text=[
            f"{w}<br>"
            f"기간 사용량: {s:,.0f} ㎥<br>"
            f"일사용량: {d:.1f} ㎥/일"
            for w, s, d in zip(
                mf["well_id"], mf["sum_m3"], mf["per_well_day"],
            )
        ],
        hovertemplate="%{text}<extra></extra>",
        name="관정 위치",
        showlegend=False,
    ))


def render_eup_plotly_choropleth(
    agg: dict, mode: str = "abs", height: int = 520,
    show_wells: bool = False,
    master_df=None, df_long=None,
    period_lo: int = 0, period_hi: int = 0,
) -> None:
    """plotly choropleth_mapbox — 12개 읍·면 폴리곤 (folium 우회).

    Parameters
    ----------
    agg : dict[NAME → {sum_m3, n_well, per_well_day, metric}]
    mode : 'abs' (총 사용량) | 'per_well' (관정당 일사용량)
    height : 지도 높이 px
    """
    gj = load_eup_geojson()
    if not agg or not gj.get("features"):
        st.warning("표시할 폴리곤·집계 데이터가 없습니다.")
        return

    # DataFrame 빌드 — choropleth_mapbox 가 locations 컬럼으로 GeoJSON 매칭
    rows = []
    for name, m in agg.items():
        rows.append({
            "NAME":         name,
            "metric":       float(m.get("metric", 0.0)),
            "n_well":       int(m.get("n_well", 0)),
            "sum_m3":       float(m.get("sum_m3", 0.0)),
            "per_well_day": float(m.get("per_well_day") or 0.0),
        })
    df = pd.DataFrame(rows)

    # 색상 스케일 + 범위 — mode 별 분기
    if mode == "per_well":
        colorscale = DAILY_USAGE_COLORSCALE
        range_color = (DAILY_USAGE_VMIN, DAILY_USAGE_VMAX)
        color_label = "관정당 일사용량 (㎥/공·일)"
    else:
        colorscale = "Blues"
        range_color = None
        color_label = "총 사용량 (㎥)"

    fig = px.choropleth_mapbox(
        df,
        geojson=gj,
        locations="NAME",
        featureidkey="properties.NAME",   # GeoJSON 의 properties.NAME 키로 매칭
        color="metric",
        color_continuous_scale=colorscale,
        range_color=range_color,
        # 2026-05-20 사용자 요청: 베이스맵 제거 (흰 배경) — 지명·도로 노이즈 차단
        mapbox_style="white-bg",
        zoom=10.2,
        center={"lat": 33.38, "lon": 126.55},
        opacity=0.95,                     # 베이스맵 없으니 폴리곤 fillOpacity ↑
        hover_name="NAME",
        hover_data={
            "n_well":       ":,",
            "sum_m3":       ":,.0f",
            "per_well_day": ":.1f",
            "NAME":         False,
            "metric":       False,
        },
        labels={
            "n_well":       "관정 수",
            "sum_m3":       "총 사용량(㎥)",
            "per_well_day": "관정당 일평균(㎥/공·일)",
            "metric":       color_label,
        },
        height=height,
    )

    # 라벨 (사용자 요청 2026-05-20): <b> 태그 제거 (mapbox text 미지원),
    # 폰트 2단계 ↑ (11→14), 'ha' 단위 삭제, '{시} 동지역' → '동지역' 단순화.
    label_lats, label_lons, label_texts = [], [], []
    for f in gj["features"]:
        name = f["properties"].get("NAME")
        if not name:
            continue
        c = _bbox_center(f["geometry"])
        if not c:
            continue
        m = agg.get(name, {})
        n_well = int(m.get("n_well", 0))
        per_w = m.get("per_well_day") or 0
        cluster = _EUP_NAME_TO_CLUSTER.get(name, "")
        area_ha = ADMIN_AGRI_HA.get(cluster, 0)
        # '제주시 동지역' / '서귀포시 동지역' → '동지역' (사용자 요청)
        display = "동지역" if name.endswith("동지역") else name
        text = (
            f"{display}<br>"
            f"{area_ha:,} ha · {n_well} 공<br>"   # 'ha' 다시 추가 (사용자 요청)
            f"{per_w:.1f} ㎥/공·일"
        )
        label_lats.append(c[0])
        label_lons.append(c[1])
        label_texts.append(text)

    fig.add_trace(go.Scattermapbox(
        lat=label_lats, lon=label_lons,
        mode="text",
        text=label_texts,
        textfont=dict(size=14, color="#1a1a18"),
        hoverinfo="skip",
        showlegend=False,
    ))

    # 관정 점 trace (toggle) — 사용자 요청 2026-05-20
    if show_wells:
        _add_well_markers(fig, master_df, df_long, period_lo, period_hi, mode)

    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        coloraxis_colorbar=dict(
            title=color_label, thickness=14, len=0.85,
        ),
    )

    st.plotly_chart(
        fig, use_container_width=True,
        config={"displayModeBar": True, "scrollZoom": True,
                "modeBarButtonsToRemove": ["lasso2d", "select2d"]},
    )


def render_ri_plotly_choropleth(
    agg: dict, mode: str = "abs", height: int = 560,
    show_wells: bool = False,
    master_df=None, df_long=None,
    period_lo: int = 0, period_hi: int = 0,
) -> None:
    """plotly choropleth_mapbox — 172개 리·동 폴리곤.

    동지역·자료없는 리는 옅은 회색 base layer 로 표시하고, 그 위에 agg 가
    있는 폴리곤만 색상 그라데이션으로 덮어씌움 (2-layer 패턴).

    Parameters
    ----------
    agg : dict[법정리명 → {sum_m3, n_well, per_well_day, metric}]
    mode : 'abs' (총 사용량) | 'per_well' (관정당 일사용량)
    """
    import plotly.graph_objects as go

    gj = load_ri_geojson()
    if not gj.get("features"):
        st.warning("리·동 GeoJSON 을 로드할 수 없습니다.")
        return

    # 2026-05-20 옵션 B (동명이리 분리): GeoJSON 의 properties.법정리이름
    # ('서귀포시수산리' 등) 으로 매칭. agg 의 ri_full_key 와 정확히 일치.
    all_full = [f["properties"].get("법정리이름") for f in gj["features"]]
    all_full = [n for n in all_full if n]

    # ── Layer 1: 전체 폴리곤 옅은 회색 base + 외곽선 강화 ──
    # 사용자 요청 2026-05-20: 자료 없는 폴리곤도 외곽선 명확히 + 0공 라벨 표시
    fig = go.Figure()
    fig.add_trace(go.Choroplethmapbox(
        geojson=gj,
        locations=all_full,
        z=[0] * len(all_full),
        featureidkey="properties.법정리이름",
        colorscale=[[0, "rgba(240,240,240,0.85)"], [1, "rgba(240,240,240,0.85)"]],
        showscale=False,
        hoverinfo="skip",
        marker=dict(
            line=dict(color="#777777", width=0.6),    # 외곽선 진하게 (#aaa→#777, 0.3→0.6)
        ),
        name="전체 리·동 (자료 없음/동지역)",
    ))

    # ── Layer 2: agg 가 있는 폴리곤만 색상 ──
    if agg:
        keys = list(agg.keys())
        z_vals      = [float(agg[k].get("metric", 0.0))      for k in keys]
        n_wells     = [int(agg[k].get("n_well", 0))          for k in keys]
        sum_m3s     = [float(agg[k].get("sum_m3", 0.0))      for k in keys]
        per_w_days  = [float(agg[k].get("per_well_day") or 0) for k in keys]
        # 2026-05-20 사용자 요청: hover 라벨에서 시·읍/면 prefix 제거 → ri_norm
        # 또는 well_eup(동지역) 만 표시. 동명이리는 폴리곤 분리로 시각 식별.
        short_labels = []
        for k in keys:
            v = agg[k]
            rn = v.get("ri_norm")
            if isinstance(rn, str) and rn:
                short_labels.append(rn)             # '수산리'
            else:
                eup = v.get("eup")
                if isinstance(eup, str) and eup:
                    short_labels.append(eup)        # '강정동' (동지역)
                else:
                    short_labels.append(k)
        # customdata: [short_label, n_well, sum_m3, per_well_day]
        custom = list(zip(short_labels, n_wells, sum_m3s, per_w_days))

        if mode == "per_well":
            colorscale = DAILY_USAGE_COLORSCALE
            zmin, zmax = DAILY_USAGE_VMIN, DAILY_USAGE_VMAX
            color_label = "관정당 일사용량 (㎥/공·일)"
        else:
            colorscale = "Blues"
            zmin = 0
            zmax = max(z_vals) if z_vals else 1.0
            color_label = "총 사용량 (㎥)"

        fig.add_trace(go.Choroplethmapbox(
            geojson=gj,
            locations=keys,
            z=z_vals,
            featureidkey="properties.법정리이름",
            colorscale=colorscale,
            zmin=zmin, zmax=zmax,
            marker=dict(
                opacity=0.95,                              # 베이스맵 없음 → 진하게
                line=dict(color="#444444", width=0.6),
            ),
            customdata=custom,
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"      # 짧은 이름만 ('수산리')
                "관정 수: %{customdata[1]:,} 공<br>"
                "총 사용량: %{customdata[2]:,.0f} ㎥<br>"
                "관정당 일평균: %{customdata[3]:.1f} ㎥/공·일"
                "<extra></extra>"
            ),
            colorbar=dict(
                title=color_label, thickness=14, len=0.85,
            ),
            name="이용량",
        ))

    # 2026-05-20 사용자 요청: 모든 폴리곤에 라벨 표시. 자료 없는 폴리곤은
    # "리명 0공" 표시 + 회색 폰트로 시각적 구분.
    agg_keys_set = set(agg.keys()) if agg else set()
    label_lats, label_lons, label_texts, label_colors = [], [], [], []
    for f in gj["features"]:
        full = f["properties"].get("법정리이름")
        short = f["properties"].get("법정리명")        # 짧은 리명
        if not short:
            continue
        c = _bbox_center(f["geometry"])
        if not c:
            continue
        v = agg.get(full) if agg else None
        if v:
            n_well = int(v.get("n_well", 0))
            rn = v.get("ri_norm")
            if isinstance(rn, str) and rn:
                disp = rn
            else:
                eup = v.get("eup")
                disp = eup if isinstance(eup, str) and eup else short
            label_color = "#1a1a18"
        else:
            disp = short
            n_well = 0
            label_color = "#888888"                     # 회색 (자료 없음)
        label_lats.append(c[0])
        label_lons.append(c[1])
        label_texts.append(f"{disp}<br>{n_well}공")
        label_colors.append(label_color)

    if label_texts:
        # plotly Scattermapbox 의 textfont.color 는 trace 전체 단일 색상.
        # 색상 구분 위해 두 trace 로 분리 (검은색·회색).
        for target_color, mark in [("#1a1a18", "active"), ("#888888", "empty")]:
            sub_lats = [a for a, c in zip(label_lats, label_colors) if c == target_color]
            sub_lons = [a for a, c in zip(label_lons, label_colors) if c == target_color]
            sub_texts = [t for t, c in zip(label_texts, label_colors) if c == target_color]
            if not sub_texts:
                continue
            fig.add_trace(go.Scattermapbox(
                lat=sub_lats, lon=sub_lons,
                mode="text",
                text=sub_texts,
                textfont=dict(size=11, color=target_color),
                hoverinfo="skip",
                showlegend=False,
            ))

    # 관정 점 trace (toggle) — 사용자 요청 2026-05-20
    if show_wells:
        _add_well_markers(fig, master_df, df_long, period_lo, period_hi, mode)

    fig.update_layout(
        # 2026-05-20 사용자 요청: 베이스맵 제거 (흰 배경)
        mapbox_style="white-bg",
        mapbox_zoom=10.2,
        mapbox_center={"lat": 33.38, "lon": 126.55},
        margin=dict(l=0, r=0, t=0, b=0),
        height=height,
        showlegend=False,
    )

    st.plotly_chart(
        fig, use_container_width=True,
        config={"displayModeBar": True, "scrollZoom": True,
                "modeBarButtonsToRemove": ["lasso2d", "select2d"]},
    )

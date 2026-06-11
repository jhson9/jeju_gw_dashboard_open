# ==============================================================================
#  파일명: src/dashboard/agri_stats_helpers.py  —  Build 1.1
#  농업통계(tab41~45) 공용 UI 헬퍼 — KPI 카드 · choropleth · 표 · 색상 · 출처
# ==============================================================================
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

import config
from src.dashboard import theme
from src.dashboard.map_helpers import make_map

AGRI_COLORS = {"population": "#185fa5", "household": "#548235",
               "farmland": "#C65911", "neutral": "#7F7F7F"}
_SEQ_RAMPS = {
    "population": ["#e3edf7", "#bcd2ea", "#8fb4d9", "#5d8ec3", "#2f6aa8", "#185fa5"],
    "household":  ["#eaf0e1", "#d2e0bf", "#b3cd93", "#8fb663", "#6c9a3e", "#548235"],
    "farmland":   ["#fbe9dd", "#f6cdb0", "#eea878", "#e07f43", "#cf6422", "#C65911"],
    "greenhouse": ["#e6f2ec", "#c5e0cf", "#8fc4a8", "#5aa583", "#3a8a64", "#2E8B57"],
}
_NO_DATA_COLOR = "#dfe3e6"


@lru_cache(maxsize=4)
def _read_geojson(path_str: str, mtime: float) -> dict:
    return json.loads(Path(path_str).read_text(encoding="utf-8"))


def load_eup_geojson() -> dict:
    p = Path(config.EUP_BOUNDARY_GEOJSON)
    return _read_geojson(str(p), p.stat().st_mtime)


def load_ri_geojson() -> dict:
    p = Path(config.RI_BOUNDARY_GEOJSON)
    return _read_geojson(str(p), p.stat().st_mtime)


def quantile_thresholds(values, n_bins=6):
    pos = [float(v) for v in values if v is not None and not pd.isna(v) and float(v) > 0]
    if len(pos) < 2:
        return None
    s = pd.Series(pos)
    qs = [s.quantile(q) for q in [i / n_bins for i in range(1, n_bins)]]
    out, last = [], float("-inf")
    for q in qs:
        if q <= last:
            q = last + 1e-9
        out.append(float(q)); last = q
    return out


def color_from_value(value, thresholds, ramp_key):
    ramp = _SEQ_RAMPS.get(ramp_key, _SEQ_RAMPS["population"])
    if value is None or pd.isna(value) or float(value) <= 0:
        return _NO_DATA_COLOR
    if not thresholds:
        return ramp[len(ramp) // 2]
    v = float(value)
    for i, t in enumerate(thresholds):
        if v <= t:
            return ramp[i]
    return ramp[-1]


def render_choropleth_eup(agg, ramp_key, value_label, value_fmt="{:,.0f}",
                          height=460, key="agri_eup_map", unit=""):
    gj_src = load_eup_geojson()
    thresholds = quantile_thresholds(list(agg.values()))
    feats = []
    for feat in gj_src.get("features", []):
        props = dict(feat.get("properties", {}))
        v = agg.get(props.get("NAME"))
        props["_val_text"] = (value_fmt.format(v) + ((" " + unit) if unit else "")) if v is not None else "-"
        feats.append({"type": "Feature", "geometry": feat.get("geometry"), "properties": props})
    gj = {"type": "FeatureCollection", "features": feats}
    fmap = make_map(center=(33.42, 126.55), zoom=10.5)

    def _style(feat):
        return {"fillColor": color_from_value(agg.get(feat["properties"].get("NAME")), thresholds, ramp_key),
                "color": "#333333", "weight": 1, "fillOpacity": 0.7}

    folium.GeoJson(
        gj, name="읍면동", style_function=_style,
        highlight_function=lambda x: {"weight": 3, "color": "#185fa5"},
        tooltip=folium.GeoJsonTooltip(
            fields=["NAME", "_val_text"], aliases=["읍·면·동", value_label],
            sticky=True, opacity=0.92, localize=False,
            style="background-color:white;color:#1a1a18;font-size:12px;padding:6px 10px;border-radius:4px;"),
    ).add_to(fmap)
    _render_legend(fmap, thresholds, ramp_key, value_label, value_fmt, unit)
    st_folium(fmap, key=key, height=height, use_container_width=True, returned_objects=[])


def render_choropleth_ri(agg, ramp_key, value_label, value_fmt="{:,.0f}",
                         height=460, key="agri_ri_map", unit=""):
    gj_src = load_ri_geojson()
    thresholds = quantile_thresholds(list(agg.values()))
    feats = []
    for feat in gj_src.get("features", []):
        props = dict(feat.get("properties", {}))
        v = agg.get(props.get("법정리명"))
        props["_val_text"] = (value_fmt.format(v) + ((" " + unit) if unit else "")) if v is not None else "-"
        feats.append({"type": "Feature", "geometry": feat.get("geometry"), "properties": props})
    gj = {"type": "FeatureCollection", "features": feats}
    fmap = make_map(center=(33.38, 126.55), zoom=10.5)

    def _style(feat):
        return {"fillColor": color_from_value(agg.get(feat["properties"].get("법정리명")), thresholds, ramp_key),
                "color": "#555555", "weight": 0.5, "fillOpacity": 0.7}

    folium.GeoJson(
        gj, name="법정리", style_function=_style,
        tooltip=folium.GeoJsonTooltip(
            fields=["법정리명", "_val_text"], aliases=["법정리", value_label],
            sticky=True, opacity=0.92, localize=False,
            style="background-color:white;color:#1a1a18;font-size:12px;padding:6px 10px;border-radius:4px;"),
    ).add_to(fmap)
    _render_legend(fmap, thresholds, ramp_key, value_label, value_fmt, unit)
    st_folium(fmap, key=key, height=height, use_container_width=True, returned_objects=[])


def _render_legend(fmap, thresholds, ramp_key, label, value_fmt, unit):
    ramp = _SEQ_RAMPS.get(ramp_key, _SEQ_RAMPS["population"])
    if not thresholds:
        return
    rows = []
    edges = [None] + list(thresholds) + [None]
    for i in range(len(ramp)):
        lo, hi = edges[i], edges[i + 1]
        if lo is None:
            txt = "≤ " + value_fmt.format(hi)
        elif hi is None:
            txt = "> " + value_fmt.format(lo)
        else:
            txt = value_fmt.format(lo) + " ~ " + value_fmt.format(hi)
        rows.append('<div style="display:flex;align-items:center;gap:6px;margin:1px 0;">'
                    '<span style="width:14px;height:12px;background:' + ramp[i] +
                    ';display:inline-block;border:0.5px solid #999;"></span>'
                    '<span style="font-size:11px;color:#1a1a18;">' + txt + '</span></div>')
    unit_txt = (" (" + unit + ")") if unit else ""
    html = ('<div style="position:fixed;bottom:24px;left:24px;z-index:9999;'
            'background:rgba(255,255,255,0.92);padding:8px 10px;border-radius:6px;'
            'border:0.5px solid #ccc;font-family:Pretendard,sans-serif;">'
            '<div style="font-size:12px;font-weight:700;margin-bottom:4px;color:#1a1a18;">'
            + label + unit_txt + '</div>' + "".join(rows) + "</div>")
    fmap.get_root().html.add_child(folium.Element(html))


def kpi_card(label, value, sub="", accent="#185fa5"):
    bg = theme.hex_alpha(accent, 0.07)
    return ('<div style="background:' + bg + ';border-radius:8px;padding:0.6rem 0.9rem;'
            'border-left:3px solid ' + accent + ';margin-bottom:8px;min-height:92px;">'
            '<div style="font-size:15px;color:var(--color-text-primary);font-weight:600;line-height:1.2;">'
            + label + '</div>'
            '<div style="font-size:24px;font-weight:700;color:' + accent + ';line-height:1.25;margin:3px 0 0;">'
            + value + '</div>'
            '<div style="font-size:13px;color:var(--color-text-secondary);font-weight:500;'
            'line-height:1.3;margin-top:2px;">' + sub + '</div></div>')


def kpi_row(cards):
    cols = st.columns(len(cards))
    for col, html in zip(cols, cards):
        with col:
            st.markdown(html, unsafe_allow_html=True)


def trend_arrow(delta, good_up=True, fmt="{:+,.0f}"):
    if delta is None:
        return '<span style="color:var(--color-text-secondary);">-</span>'
    up = delta > 0
    color = "#1d9e75" if (up == good_up) else "#C0392B"
    arrow = "▲" if up else ("▼" if delta < 0 else "—")
    return '<span style="color:' + color + ';font-weight:600;">' + arrow + " " + fmt.format(delta) + '</span>'


def html_table(df, headers=None, align="center", highlight_last_row=False):
    cols = list(df.columns)
    heads = headers if headers else cols
    TH = ("padding:6px 8px;text-align:center;font-weight:700;color:#000;"
          "border:0.5px solid rgba(0,0,0,0.18);font-size:14px;background:var(--color-bg-secondary);")
    TD = ("padding:5px 8px;text-align:" + align + ";border:0.5px solid rgba(0,0,0,0.15);"
          "font-size:14px;color:var(--color-text-primary);")
    head = ("<table style='width:100%;border-collapse:collapse;table-layout:auto;"
            "border:0.5px solid rgba(0,0,0,0.18);margin:4px 0 8px;'><thead><tr>"
            + "".join("<th style='" + TH + "'>" + str(h) + "</th>" for h in heads) + "</tr></thead><tbody>")
    body, n = [], len(df)
    for ri, (_, row) in enumerate(df.iterrows()):
        emph = (highlight_last_row and ri == n - 1)
        tr_bg = "background:#fafaf0;" if emph else ""
        fw = "font-weight:700;" if emph else ""
        cells = "".join("<td style='" + TD + fw + "'>" + ("" if pd.isna(row[c]) else str(row[c])) + "</td>" for c in cols)
        body.append("<tr style='" + tr_bg + "'>" + cells + "</tr>")
    return head + "".join(body) + "</tbody></table>"


def section_title(text, top=12):
    st.markdown('<p class="subsection-title" style="margin-top:' + str(top) + 'px;">' + text + '</p>',
                unsafe_allow_html=True)


def source_caption(text):
    st.markdown('<div style="font-size:12px;color:var(--color-text-secondary);margin:2px 0 10px;">※ '
                + text + '</div>', unsafe_allow_html=True)


AGRI_SOURCES = ("제65회 제주통계연보(2024년 기준) · "
                "2025 제주 주요행정통계 · "
                "제주특별자치도 농업용수 종합계획 수립 보고서")


def source_footer(extra=""):
    tail = ("<br>· " + extra) if extra else ""
    st.markdown('<div style="margin-top:14px;padding-top:8px;'
                'border-top:0.5px solid rgba(26,26,24,0.15);'
                'font-size:12px;color:var(--color-text-secondary);line-height:1.5;">'
                '<b>데이터 출처</b> &nbsp;|&nbsp; ' + AGRI_SOURCES + tail + '</div>',
                unsafe_allow_html=True)

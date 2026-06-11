"""'입체적 단어구조' — 청크 임베딩 UMAP 3D 지도 (Plotly).

전체 청크가 의미 공간에 점으로 떠 있고, 질문 시 검색된 청크(근거)가
강조되며 질문 위치(★)도 함께 투영된다.
"""
from __future__ import annotations

import pickle
from functools import lru_cache

import pandas as pd
import plotly.graph_objects as go

from ..config import COORDS_PARQUET, UMAP_REDUCER_PKL


@lru_cache(maxsize=1)
def load_coords() -> pd.DataFrame:
    return pd.read_parquet(COORDS_PARQUET)


@lru_cache(maxsize=1)
def _reducer():
    try:
        with open(UMAP_REDUCER_PKL, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def coords_available() -> bool:
    return COORDS_PARQUET.exists()


def project_question(q_embedding) -> tuple[float, float, float] | None:
    """질문 임베딩을 같은 3D 공간으로 투영."""
    red = _reducer()
    if red is None or q_embedding is None:
        return None
    try:
        xyz = red.transform([q_embedding])[0]
        return float(xyz[0]), float(xyz[1]), float(xyz[2])
    except Exception:
        return None


def make_figure(hit_ids: list[str] | None = None,
                q_embedding=None, height: int = 640) -> go.Figure:
    """전체 청크 3D 산점도. hit_ids는 강조, 질문은 ★로 표시."""
    df = load_coords()
    hit_ids = hit_ids or []
    fig = go.Figure()

    # 1) 전체 청크 — 문서별 색상
    for doc, g in df.groupby("doc_name"):
        is_hit = g["chunk_id"].isin(hit_ids)
        base = g[~is_hit]
        fig.add_trace(go.Scatter3d(
            x=base["x"], y=base["y"], z=base["z"],
            mode="markers", name=doc[:22],
            marker=dict(size=2.4, opacity=0.45),
            customdata=base[["doc_name", "article"]].values,
            hovertemplate="%{customdata[0]}<br>%{customdata[1]}<extra></extra>"))

    # 2) 검색된 근거 청크 강조
    hits = df[df["chunk_id"].isin(hit_ids)]
    if not hits.empty:
        fig.add_trace(go.Scatter3d(
            x=hits["x"], y=hits["y"], z=hits["z"],
            mode="markers+text", name="검색된 근거",
            text=[a.split("(")[0] for a in hits["article"]],
            textposition="top center", textfont=dict(size=10),
            marker=dict(size=7, color="#e4572e", symbol="diamond",
                        line=dict(width=1, color="#7a2207")),
            customdata=hits[["doc_name", "article"]].values,
            hovertemplate="근거: %{customdata[0]}<br>%{customdata[1]}<extra></extra>"))

    # 3) 질문 위치 (★)
    q_xyz = project_question(q_embedding)
    if q_xyz:
        fig.add_trace(go.Scatter3d(
            x=[q_xyz[0]], y=[q_xyz[1]], z=[q_xyz[2]],
            mode="markers+text", name="질문",
            text=["★ 질문"], textposition="top center",
            marker=dict(size=9, color="#f4b41a", symbol="circle",
                        line=dict(width=2, color="#8a6500")),
            hovertemplate="질문 위치<extra></extra>"))

    fig.update_layout(
        height=height, margin=dict(l=0, r=0, t=8, b=0),
        showlegend=True,
        # 범례: 그래프 하단 가로 배치 (사용자 요청 2026-06-11)
        legend=dict(orientation="h", font=dict(size=9), itemsizing="constant",
                    yanchor="top", y=-0.02, xanchor="left", x=0.0,
                    bgcolor="rgba(255,255,255,0.55)"),
        scene=dict(xaxis=dict(visible=False), yaxis=dict(visible=False),
                   zaxis=dict(visible=False), bgcolor="rgba(0,0,0,0)",
                   # 기본 줌 1단계 확대 (기본 eye 1.25 → 0.95)
                   camera=dict(eye=dict(x=0.95, y=0.95, z=0.95))))
    return fig

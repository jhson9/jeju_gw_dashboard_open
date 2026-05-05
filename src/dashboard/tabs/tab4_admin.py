# ==============================================================================
#  파일명: src/dashboard/tabs/tab4_admin.py
#  탭: 🧾 리포트 (외부 공개판 — 데이터 파이프라인 UI 제거, 리포트 기능만 유지)
# ------------------------------------------------------------------------------
#  【이 탭의 역할 — 외부 공개판】
#  PC(개발) 버전의 데이터 수집·파싱·집계 UI 는 외부 공개판에서 노출하지 않는다.
#  대신 리포트 생성 기능만 남겨, 사용자가 현재 기준일의 분석 결과를 한 장의
#  HTML 리포트로 내보낼 수 있게 한다.
#
#  PC 버전(별도 브랜치/내부 사본)에서는 본 파일을 데이터 파이프라인 포함
#  full version 으로 유지하면 됨.
# ==============================================================================

from __future__ import annotations

import base64
from datetime import datetime as _dt

import pandas as pd
import streamlit as st

import config
from src.dashboard import report_generator


def render(asos_df: pd.DataFrame, ws_data_all: dict, periods: dict,
           rainfall_table: pd.DataFrame = None,
           eff_table: pd.DataFrame = None,
           gw_summary_df: pd.DataFrame = None):
    """리포트 탭 렌더링 (외부 공개판)."""

    st.markdown(
        '<p style="font-size:10px;color:#5f5e5a;margin:0 0 12px;">'
        '현재 기준일의 분석 결과를 한 장의 HTML 리포트로 내보냅니다.'
        '</p>',
        unsafe_allow_html=True
    )

    # --------------------------------------------------------------------------
    #  분석 리포트 생성 (Build 0.7.2 기능 유지)
    # --------------------------------------------------------------------------
    st.markdown(
        '<p style="font-size:15px;font-weight:600;margin:0 0 6px;">'
        '🧾 분석 리포트 생성</p>',
        unsafe_allow_html=True
    )
    st.markdown(
        f"현재 기준일(**`{periods['base_date']}`**)의 분석 결과를 "
        f"한 장의 **정리된 HTML 리포트**로 내보냅니다."
    )

    rp_col1, rp_col2, rp_col3 = st.columns([1, 1, 2])
    with rp_col1:
        if st.button("🧾 리포트 생성", type="primary",
                     use_container_width=True,
                     key="tab4_generate_report"):
            st.session_state["report_requested"] = True

    with rp_col2:
        if st.session_state.get("report_requested", False):
            if st.button("✖️ 리포트 닫기", use_container_width=True,
                         key="tab4_close_report"):
                st.session_state["report_requested"] = False
                st.rerun()

    with rp_col3:
        st.caption(
            "💡 **리포트 생성** → 다운로드 / 새 탭 미리보기 가능. "
            "**리포트 닫기** 로 화면을 정리할 수 있습니다."
        )

    if st.session_state.get("report_requested", False):
        try:
            report_html = report_generator.build_report_html(
                base_date=periods["base_date"],
                periods=periods,
                asos_df=asos_df,
                ws_data_all=ws_data_all,
                rainfall_table=rainfall_table,
                effective_table=eff_table,
                gwlevel_table=gw_summary_df,
            )

            try:
                saved_path = report_generator.save_report_to_file(
                    report_html, periods["base_date"]
                )
                st.success(
                    f"✅ 리포트 생성 완료. 로컬 저장: "
                    f"`{saved_path.relative_to(config.PROJECT_ROOT)}`"
                )
            except Exception:
                st.success("✅ 리포트 생성 완료.")

            fname = f"jeju_report_{periods['base_date']}_{_dt.now().strftime('%H%M')}.html"

            dl_col, prev_col = st.columns([1, 1])
            with dl_col:
                st.download_button(
                    label="⬇️ HTML 리포트 다운로드",
                    data=report_html.encode("utf-8"),
                    file_name=fname,
                    mime="text/html",
                    use_container_width=True,
                    key="tab4_html_download",
                )
            with prev_col:
                # JavaScript Blob URL 방식 — base64 인코딩 후 새 탭에 열기.
                import streamlit.components.v1 as components
                b64 = base64.b64encode(report_html.encode("utf-8")).decode("ascii")
                preview_widget = f"""
<div style="width:100%;">
  <button id="open-report-newtab"
    style="width:100%;padding:0.45rem 0;border:0.5px solid rgba(26,26,24,0.15);
           border-radius:20px;background:#f5f5f3;color:#5f5e5a;
           font-size:12px;cursor:pointer;font-family:inherit;">
    📖 새 탭에서 리포트 열기
  </button>
  <div style="font-size:11px;color:#5f5e5a;margin-top:4px;text-align:center;">
    🔗 새 브라우저 탭에서 열림 (대시보드 영향 없음)
  </div>
  <script>
    (function() {{
      var btn = document.getElementById('open-report-newtab');
      if (!btn) return;
      btn.addEventListener('click', function() {{
        try {{
          var b64 = "{b64}";
          var bin = atob(b64);
          var bytes = new Uint8Array(bin.length);
          for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
          var blob = new Blob([bytes], {{type: 'text/html;charset=utf-8'}});
          var url = URL.createObjectURL(blob);
          var w = window.open(url, '_blank', 'noopener');
          if (!w) {{
            alert('팝업이 차단되었습니다. 브라우저 주소창의 팝업 차단 해제 후 다시 시도하세요.');
          }}
          setTimeout(function() {{ URL.revokeObjectURL(url); }}, 30000);
        }} catch (e) {{
          alert('새 탭 열기 실패: ' + e.message);
        }}
      }});
    }})();
  </script>
</div>
"""
                components.html(preview_widget, height=70)

        except Exception as e:
            st.error(f"❌ 리포트 생성 실패: {e}")
            st.exception(e)

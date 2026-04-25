# ==============================================================================
#  파일명: src/dashboard/tabs/tab_report.py
#  탭: 🧾 분석 리포트 (외부 배포 버전 — 데이터 관리 기능 없음)
# ------------------------------------------------------------------------------
#  【이 탭의 역할】
#  현재 기준일의 분석 결과를 한 장의 HTML 리포트로 내보냅니다.
#  tab4_admin.py 의 Section D(리포트 생성)를 분리해 외부 사용자에게도
#  안전하게 노출할 수 있도록 만든 탭입니다.
# ==============================================================================

import base64
from datetime import datetime as _dt

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd

import config


def render(asos_df: pd.DataFrame, ws_data_all: dict, periods: dict,
           rainfall_table: pd.DataFrame = None,
           eff_table: pd.DataFrame = None,
           gw_summary_df: pd.DataFrame = None):
    """리포트 생성 탭 렌더링."""

    st.markdown(
        '<p style="font-size:10px;color:#5f5e5a;margin:0 0 12px;">'
        '현재 기준일의 분석 결과를 한 장의 HTML 리포트로 내보냅니다.'
        '</p>',
        unsafe_allow_html=True
    )

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
                     key="tab_report_generate"):
            st.session_state["report_requested"] = True

    with rp_col2:
        if st.session_state.get("report_requested", False):
            if st.button("✖️ 리포트 닫기", use_container_width=True,
                         key="tab_report_close"):
                st.session_state["report_requested"] = False
                st.rerun()

    with rp_col3:
        st.caption(
            "💡 **리포트 생성** → 다운로드 / 새 탭 미리보기 가능. "
            "**리포트 닫기** 로 화면을 정리할 수 있습니다."
        )

    if st.session_state.get("report_requested", False):
        try:
            from src.dashboard import report_generator

            report_html = report_generator.build_report_html(
                base_date=periods["base_date"],
                periods=periods,
                asos_df=asos_df,
                ws_data_all=ws_data_all,
                rainfall_table=rainfall_table,
                effective_table=eff_table,
                gwlevel_table=gw_summary_df,
            )

            # 외부 배포 환경(Streamlit Cloud)에서는 파일 저장이 실패할 수 있으므로
            # 실패해도 다운로드/미리보기는 정상 동작하도록 try/except 로 감싼다.
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
                )
            with prev_col:
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

# ==============================================================================
#  파일명: src/dashboard/tabs/tab4_admin.py
#  탭: ⚙️ 데이터 관리
# ------------------------------------------------------------------------------
#  Build: 0.8
# ------------------------------------------------------------------------------
#  【이 탭의 역할】
#  데이터 수집/처리/시스템 상태 관리. 평소엔 안 보이고, 수집할 때만 접근.
#   - ASOS 수집 버튼 & 현황
#   - 지하수위 파이프라인 실행 버튼 & 현황
#   - 시스템 상태 체크리스트
#   - 분석 리포트 생성
# ==============================================================================

import streamlit as st
import pandas as pd
import plotly.express as px

import config
from src.collectors import asos_collector, gwlevel_parser
from src.analysis import watershed_mapper
from src.dashboard import theme


def render(asos_df: pd.DataFrame, ws_data_all: dict, periods: dict,
           rainfall_table: pd.DataFrame = None,
           eff_table: pd.DataFrame = None,
           gw_summary_df: pd.DataFrame = None):
    """데이터 관리 탭 렌더링."""

    st.markdown(
        '<p style="font-size:10px;color:#5f5e5a;margin:0 0 12px;">'
        '데이터 수집, 처리 파이프라인 실행, 시스템 상태 확인, 분석 리포트 생성을 할 수 있습니다.'
        '</p>',
        unsafe_allow_html=True
    )

    # --------------------------------------------------------------------------
    # Section A: ASOS 수집 현황 & 버튼
    # --------------------------------------------------------------------------
    st.markdown(
        '<p style="font-size:15px;font-weight:600;margin:0 0 6px;">'
        '📡 ASOS 기상 데이터</p>',
        unsafe_allow_html=True
    )

    with st.container():
        if asos_df.empty:
            st.warning("⚠️ 아직 ASOS 데이터가 수집되지 않았습니다.")
        else:
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.metric("총 레코드", f"{len(asos_df):,}개")
            with m2:
                st.metric("수집 지점", f"{asos_df['지점명'].nunique()}개")
            with m3:
                st.metric("시작일", str(asos_df["일시"].min().date()))
            with m4:
                st.metric("종료일", str(asos_df["일시"].max().date()))

            with st.expander("📅 지점별·연도별 수집 현황", expanded=False):
                summary = (
                    asos_df.assign(연도=asos_df["일시"].dt.year)
                           .groupby(["지점명", "연도"])
                           .size()
                           .unstack(fill_value=0)
                )
                st.dataframe(summary, use_container_width=True)

        # 안내
        st.info(
            "💡 **수집 실행 방법**: 터미널에서 다음 명령 중 하나를 실행하세요:\n\n"
            "```\n"
            "# 기본(Smart): M-2·M-1·M에 필요한 기간만\n"
            "python src/collectors/asos_collector.py\n\n"
            "# 최신: 어제 날짜까지 모두\n"
            "python src/collectors/asos_collector.py --mode latest\n"
            "```\n\n"
            "⚠️ 대시보드 내 버튼으로 실행하면 수집 중 화면이 멈출 수 있어, "
            "터미널에서 실행하시는 것을 권장합니다."
        )

    st.divider()

    # --------------------------------------------------------------------------
    # Section B: 지하수위 데이터 파이프라인
    # --------------------------------------------------------------------------
    st.markdown(
        '<p style="font-size:15px;font-weight:600;margin:0 0 6px;">'
        '💧 지하수위 데이터 파이프라인</p>',
        unsafe_allow_html=True
    )

    xls_files = (list(config.ROW_DATA_DIR.glob("JD*.xls"))
                 + list(config.ROW_DATA_DIR.glob("JD*.xlsx")))
    jd_network_file = config.find_jd_network_file()
    station_csvs = list(config.GW_STATION_DIR.glob("*.csv"))
    watershed_csvs = list(config.GW_WATERSHED_DIR.glob("*.csv"))

    g1, g2, g3, g4 = st.columns(4)
    with g1:
        st.metric("Row_Data xls", f"{len(xls_files)}개",
                  help="사용자가 투입한 JD 관측소 원본 파일")
    with g2:
        st.metric("파싱된 관측소", f"{len(station_csvs)}개",
                  help="S11 센서 추출 완료된 CSV 개수")
    with g3:
        st.metric("집계된 유역", f"{len(watershed_csvs)}개",
                  help="14개 중 실제 데이터가 있는 유역 수")
    with g4:
        jd_status = "✅" if jd_network_file else "❌"
        st.metric("JD관측망 정보", jd_status,
                  help="0_JD관측망_정보.xlsx 존재 여부")

    bc1, bc2 = st.columns([1, 3])
    with bc1:
        if st.button("🔄 xls 파싱 + 유역 집계 실행",
                     type="primary", use_container_width=True,
                     key="tab4_run_gw_pipeline"):
            if not xls_files:
                st.error("❌ data/Row_Data/ 에 JD*.xls 파일이 없습니다.")
            elif not jd_network_file:
                st.error("❌ 0_JD관측망_정보.xlsx 파일이 없습니다. "
                         "data/ 폴더에 배치하세요.")
            else:
                with st.spinner("파싱 중... (약 30초 소요)"):
                    try:
                        parse_result = gwlevel_parser.run_full_pipeline(verbose=False)
                        st.success(
                            f"✅ xls 파싱 완료: {parse_result['success_count']}개 관측소"
                        )
                        if parse_result["failed"]:
                            st.warning(
                                f"⚠️ {len(parse_result['failed'])}개 파일 파싱 실패 "
                                f"(터미널 로그 확인)"
                            )
                        ws_result = watershed_mapper.run_watershed_pipeline(verbose=False)
                        st.success(f"✅ 유역 집계 완료: {len(ws_result)}개 유역")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ 오류: {e}")

    with bc2:
        st.caption(
            "💡 이 버튼은 `python process_gwlevel.py` 와 동일한 작업입니다. \n"
            "💡 xls 파일은 원본 그대로 유지되며, S11 센서만 CSV로 추출됩니다."
        )

    st.divider()

    # --------------------------------------------------------------------------
    # Section C: 시스템 상태 체크리스트
    # --------------------------------------------------------------------------
    st.markdown(
        '<p style="font-size:15px;font-weight:600;margin:0 0 6px;">'
        '🔧 시스템 상태</p>',
        unsafe_allow_html=True
    )

    col_l, col_r = st.columns(2)

    with col_l:
        st.markdown("**설정 & API**")
        api_ok = bool(config.KMA_API_KEY)
        st.write(f"- 기상청 API 키: "
                 f"{'✅ 설정됨' if api_ok else '❌ 미설정 (.env 파일 확인)'}")

        csv_path = asos_collector.get_output_csv_path()
        st.write(f"- ASOS CSV 파일: "
                 f"{'✅ ' + csv_path.name if csv_path.exists() else '❌ 미생성'}")

        st.write(f"- JD관측망 정보 파일: "
                 f"{'✅ ' + jd_network_file.parent.name + '/' + jd_network_file.name if jd_network_file else '❌ 미탐지'}")

    with col_r:
        st.markdown("**폴더 구조**")
        config.ensure_directories()
        dirs_status = {
            "data/ASOS":                 config.ASOS_DIR.exists(),
            "data/GWlevel/by_station":   config.GW_STATION_DIR.exists(),
            "data/GWlevel/by_watershed": config.GW_WATERSHED_DIR.exists(),
            "data/Row_Data":             config.ROW_DATA_DIR.exists(),
            "data/reports":              (config.DATA_DIR / "reports").exists(),
        }
        for name, exists in dirs_status.items():
            st.write(f"- `{name}`: {'✅' if exists else '❌'}")

        st.write(f"- Row_Data JD 파일: **{len(xls_files)}개**")

    st.divider()

    # --------------------------------------------------------------------------
    # Section D: 분석 리포트 생성 (Build 0.7.2 기능 유지)
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
        # 리포트가 이미 생성된 상태에서만 닫기 버튼 활성화 표시
        if st.session_state.get("report_requested", False):
            if st.button("✖️ 리포트 닫기", use_container_width=True,
                         key="tab4_close_report"):
                st.session_state["report_requested"] = False
                # 다음 rerun 에서 리포트 블록이 사라지도록 즉시 rerun
                st.rerun()

    with rp_col3:
        st.caption(
            "💡 **리포트 생성** → 다운로드 / 새 탭 미리보기 가능. "
            "**리포트 닫기** 로 화면을 정리할 수 있습니다."
        )

    if st.session_state.get("report_requested", False):
        try:
            from src.dashboard import report_generator
            from datetime import datetime as _dt
            import base64

            # 새 리포트 빌더 시그니처 — asos_df / ws_data_all 포함
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
                )
            with prev_col:
                # JavaScript Blob URL 방식 — data: URL 의 "빈 탭" 문제 해결.
                #  · base64로 HTML을 인코딩해 JS 변수에 넣고
                #  · 버튼 클릭 시 Blob 으로 변환 → URL.createObjectURL → window.open
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
          // 메모리 누수 방지 — 30초 후 URL 해제
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

# ==============================================================================
#  파일명: src/dashboard/tabs/tab99_admin.py
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

from datetime import date  # 🆕 2026-06-01 통합 업데이트 카드의 신선도 계산용
from pathlib import Path

import streamlit as st
import pandas as pd
import plotly.express as px

import threading
import time

import config
# 🆕 (2026-06-03) gwlevel_parser, Counter, _collect_xls, _prefix_counts,
#   _latest_day_csv_date, _jd_network_df, _network_matching 모두 제거됨.
#   Section A/B/B'/B'' 제거로 사용처 0건. _confirm_destructive 는 Section E 유지.
from src.collectors import asos_collector, gwlevel_day_parser
from src.collectors import jeju_gwlevel_collector  # 🆕 2026-06-01 water.jeju.go.kr API 직접 수집
from src.analysis import watershed_mapper
from src.dashboard import theme, tile_cache
from src.drone.importer import DroneImporter, ImportProgress


# P4-2 (2026-05-29): destructive 동작 confirm 가드 헬퍼.
# 2단계 확인: 1) 사용자가 "실행" 클릭 → confirm 상태 set, 2) "예, 진행" 클릭 → 실행.
# 잘못 누르거나 더블 클릭으로 인한 비가역 동작(데이터 덮어쓰기·upsert·재다운로드) 방지.
def _confirm_destructive(key: str, label: str, warning: str) -> bool:
    """destructive 버튼의 2단계 confirm 가드. True 반환 시 실제 실행.

    Parameters
    ----------
    key : str
        session_state 키 (각 버튼별 고유).
    label : str
        '예, 진행' 옆에 표시할 동작 이름 (예: '타일 재다운로드').
    warning : str
        warning 메시지.

    Usage
    -----
        if st.button("🔄 실행"):
            st.session_state[f"_confirm_{key}"] = True
        if st.session_state.get(f"_confirm_{key}"):
            if _confirm_destructive(key, label, warning):
                # 실제 destructive 동작
                ...
    """
    confirm_key = f"_confirm_{key}"
    if not st.session_state.get(confirm_key):
        return False
    st.warning(f"⚠️ {warning}", icon="⚠️")
    c1, c2, _ = st.columns([1, 1, 4])
    with c1:
        if st.button(f"✅ 예, {label}", key=f"{key}_yes", type="primary"):
            st.session_state[confirm_key] = False   # 1회용 토큰
            return True
    with c2:
        if st.button("✖ 취소", key=f"{key}_no"):
            st.session_state[confirm_key] = False
            st.rerun()
    return False


@st.fragment  # 21차 Step4: 위젯 변경 시 다른 탭 튕김 방지 (AGENT_GUIDE §6)
def render(asos_df: pd.DataFrame, ws_data_all: dict, periods: dict,
           rainfall_table: pd.DataFrame = None,
           eff_table: pd.DataFrame = None,
           gw_summary_df: pd.DataFrame = None):
    """데이터 관리 탭 렌더링."""

    _t, _q = st.columns([10, 1])
    with _t:
        st.markdown(
            '<p style="font-size:14px;color:var(--color-text-secondary);margin:0 0 12px;">'
            '데이터 수집, 처리 파이프라인 실행, 시스템 상태 확인, 분석 리포트 생성을 할 수 있습니다.'
            '</p>',
            unsafe_allow_html=True
        )
    with _q:
        pass  # (2026-06-11) Quit 상단 그룹 메뉴 우측으로 통합 — 버튼 제거

    # --------------------------------------------------------------------------
    # Section 0: 🆕 (2026-06-01) 통합 업데이트 카드
    #   8개 개별 버튼 대신 "마지막 갱신일 + 한 번에 업데이트" 한 카드로.
    #   사용자 피드백: 상시 실행 대시보드가 아니고, 매일 사용도 안 함 →
    #   필요할 때만 한 번에 보충하는 흐름이 자연스러움.
    # --------------------------------------------------------------------------
    st.markdown(
        '<p class="section-title" style="margin:0 0 6px;font-size:18px;">'
        '🔄 한 번에 업데이트</p>',
        unsafe_allow_html=True
    )

    today = date.today()

    # 데이터별 마지막 일자·신선도 계산
    def _days_since(d) -> int | None:
        if d is None:
            return None
        try:
            # 🛡️ (2026-06-03 오류5팀) 미래 날짜는 0으로 보정 — 표시 혼란 방지
            return max(0, (today - d).days)
        except Exception:
            return None

    def _months_since(d) -> int | None:
        """🆕 (2026-06-03) 월 단위 차이. month CSV 의 'YYYY-MM-01' 행은 그 달
        평균이라 일 단위 비교(예: 33일 전)는 부정확. 월 단위가 의미적 정답.
        """
        if d is None:
            return None
        try:
            diff = (today.year * 12 + today.month) - (d.year * 12 + d.month)
            return max(0, diff)
        except Exception:
            return None

    def _freshness_label(value: int | None, threshold: int = 7,
                         unit: str = "일") -> str:
        """🆕 (2026-06-03 디자인2팀 권고) unit 인자 추가 — 일/월 모두 처리.
        """
        if value is None:
            return "❓ 데이터 없음"
        if value <= threshold:
            return f"✅ 최신 ({value}{unit} 전)"
        if value <= threshold * 3:
            return f"⚠ {value}{unit} 전"
        return f"🔴 {value}{unit} 전 (오래됨)"

    # ASOS 마지막
    asos_last = asos_df["일시"].max().date() if not asos_df.empty else None
    asos_days = _days_since(asos_last)

    # GWlevel day/month 마지막 — JW연동 기준 (대표값, 빠름)
    def _last_in_csv(p) -> "date | None":
        try:
            if not p.exists():
                return None
            d = pd.read_csv(p, encoding="utf-8-sig", usecols=["날짜"])
            return pd.to_datetime(d["날짜"], errors="coerce").max().date()
        except Exception:
            return None

    gw_day_last     = _last_in_csv(config.GW_STATION_DAY_DIR / "JW연동.csv")
    gw_month_last   = _last_in_csv(config.GW_STATION_MONTH_DIR / "JW연동.csv")
    gw_day_days     = _days_since(gw_day_last)
    # 🆕 (2026-06-03) GW월은 월 단위로 — "2026-05-01" 은 5월 평균이므로
    # 6월 3일과 비교 시 "1개월 전" 이 정확. 일 단위(33일 전)는 부정확.
    gw_month_months = _months_since(gw_month_last)

    s1, s2, s3 = st.columns(3)
    with s1:
        st.metric(
            "📡 강수량 (ASOS)",
            str(asos_last) if asos_last else "—",
            _freshness_label(asos_days, threshold=3, unit="일"),
            delta_color="off",  # 🛡️ 오류5팀: 색상 의미 역전 방지
        )
    with s2:
        st.metric(
            "💧 지하수위 일자료",
            str(gw_day_last) if gw_day_last else "—",
            _freshness_label(gw_day_days, threshold=3, unit="일"),
            delta_color="off",
        )
    with s3:
        st.metric(
            "💧 지하수위 월자료",
            str(gw_month_last) if gw_month_last else "—",
            _freshness_label(gw_month_months, threshold=1, unit="개월"),
            delta_color="off",
        )

    # 어떤 데이터가 갱신 필요한지 판단
    needs_update = []
    if asos_days is None or asos_days > 3:
        needs_update.append("강수량(ASOS)")
    if gw_day_days is None or gw_day_days > 3:
        needs_update.append("지하수위(일)")
    if gw_month_months is None or gw_month_months > 1:
        needs_update.append("지하수위(월)")

    if needs_update:
        st.info(
            f"📅 갱신 필요: **{', '.join(needs_update)}** — "
            "아래 버튼 한 번이면 모두 자동으로 부족분만 받아옵니다."
        )
    else:
        st.success("✅ 모든 데이터가 최신입니다.")

    if st.button(
        "🔄 지금 모두 업데이트 (강수량 + 지하수위 일/월)",
        type="primary",
        use_container_width=True,
        key="unified_update_all_btn",
        help="ASOS smart → GWlevel day → GWlevel month(직전달 재검증). "
             "각 단계 끝나면 parquet + by_watershed 자동 재생성. 약 8~12분.",
    ):
        # 🆕 (2026-06-04) 인터넷 연결 확인 — 오프라인이면 즉시 안내
        import socket as _sk
        def _ck_net(t=1.5):
            for h in [("8.8.8.8", 53), ("1.1.1.1", 53)]:
                try:
                    with _sk.socket(_sk.AF_INET, _sk.SOCK_STREAM) as s:
                        s.settimeout(t); s.connect(h); return True
                except Exception:
                    continue
            return False

        if not _ck_net():
            st.error("❌ 인터넷 연결 없음 — 자동 수집을 진행할 수 없습니다.\n\n"
                     "네트워크 연결 후 다시 시도하세요.")
        else:
            # 🛡️ st.status 로 단계별 진행 가시화
            with st.status("업데이트 시작...", expanded=True) as _status:
                # 1/3 ASOS
                _status.update(label="1/3 강수량 (ASOS) 수집 중...", state="running")
                try:
                    # 🆕 (2026-06-06) smart → latest — D-1 까지 보장 (tab03/04/05)
                    asos_collector.collect_asos_data(mode="latest")
                    try:
                        asos_collector.load_asos_data.clear()
                    except Exception:
                        pass
                    st.write("  ✓ ASOS 완료")
                except Exception as e:
                    st.write(f"  ⚠ ASOS 실패: {type(e).__name__}: {e}")
                # 2/3 GWlevel day (parquet 자동 재생성 포함)
                _status.update(label="2/3 지하수위 일자료 + parquet 재생성 중...",
                               state="running")
                try:
                    # 🆕 (2026-06-06 v3) 직전달 1일부터 force 재수집 — 서버 수정 반영
                    _this_first = date(today.year, today.month, 1)
                    _prev_last  = _this_first - __import__('datetime').timedelta(days=1)
                    _prev_first = _prev_last.replace(day=1)
                    jeju_gwlevel_collector.collect_all(
                        granularity="day",
                        force=True,
                        default_start=_prev_first.strftime("%Y-%m-%d"),
                    )
                    try:
                        jeju_gwlevel_collector.load_station_day_csv.clear()
                    except Exception:
                        pass
                    st.write("  ✓ 지하수위 일자료 + parquet 완료")
                except Exception as e:
                    st.write(f"  ⚠ 일자료 실패: {type(e).__name__}: {e}")
                # 3/3 GWlevel month — 🆕 직전달 재검증 모드
                _status.update(label="3/3 지하수위 월자료 (직전달 재검증) + 유역별 집계 중...",
                               state="running")
                try:
                    # 직전달 1일 계산
                    this_month_first = date(today.year, today.month, 1)
                    prev_month_last  = this_month_first - __import__('datetime').timedelta(days=1)
                    prev_month_first = prev_month_last.replace(day=1)
                    jeju_gwlevel_collector.collect_all(
                        granularity="month",
                        force=True,
                        default_start=prev_month_first.strftime("%Y-%m-%d"),
                    )
                    st.write(f"  ✓ 지하수위 월자료 완료 "
                             f"(직전달 {prev_month_first.strftime('%Y-%m')} 재검증 포함)")
                except Exception as e:
                    st.write(f"  ⚠ 월자료 실패: {type(e).__name__}: {e}")
                _status.update(label="✅ 모든 업데이트 완료 — 페이지 새로고침합니다",
                               state="complete", expanded=False)
            st.toast("✅ 모든 데이터 업데이트 완료", icon="✅")
            time.sleep(1.2)
            st.rerun()

    # 마지막 갱신 시각 (CSV mtime 기반) — 디자인2팀 권고
    try:
        from datetime import datetime as _dt
        _asos_p   = asos_collector.get_output_csv_path()
        _gw_day_p = config.GW_STATION_DAY_DIR / "JW연동.csv"
        _gw_mo_p  = config.GW_STATION_MONTH_DIR / "JW연동.csv"
        def _mtime(p):
            try:
                return _dt.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            except Exception:
                return "—"
        st.caption(
            f"📅 마지막 파일 갱신: "
            f"ASOS {_mtime(_asos_p)}  ·  "
            f"GWlevel 일 {_mtime(_gw_day_p)}  ·  "
            f"GWlevel 월 {_mtime(_gw_mo_p)}"
        )
    except Exception:
        pass

    st.caption(
        "💡 `Run_JejuDashboard.bat` 더블클릭 시에도 자동으로 신선도를 확인해 "
        "오래된 데이터만 부족분을 받아옵니다. 평소엔 위 버튼이나 .bat 실행만으로 충분합니다.\n\n"
        "📌 아래 옛 개별 수집 버튼들은 **참고용** — Section 0 통합 카드가 모든 기능을 "
        "한 번에 수행합니다 (parquet + 유역별 집계 자동 포함)."
    )

    # 🆕 (2026-06-06) 위험 작업 — 전체 자료 초기화 + 처음부터 재수집
    # 사용자 명시 클릭 + 2단계 confirm 가드. force 재수집 후 dedup 으로 안전.
    st.markdown(
        '<div style="margin:18px 0 6px;padding:8px 12px;'
        'background:rgba(220,80,80,0.06);border-left:3px solid rgba(220,80,80,0.5);'
        'border-radius:3px;">'
        '<p style="font-size:13px;color:var(--color-text-secondary);margin:0;">'
        '<b style="color:rgba(180,40,40,0.9);">⚠ 위험 작업</b> — '
        '서버 데이터 전면 재확인이 필요할 때만 사용 (예: 분기 검증, '
        '원본 데이터 의심 사례). 약 <b>30~90분</b> 소요.'
        '</p></div>',
        unsafe_allow_html=True
    )
    full1, full2 = st.columns([1, 3])
    with full1:
        if st.button("🔥 전체 초기화 + 재수집",
                     type="secondary", use_container_width=True,
                     key="full_reset_btn",
                     help="ASOS 2000~ + GWlevel 일·월 2015~ 모두 force 재수집. "
                          "기존 CSV는 dedup으로 안전 (덮어쓰기). 1회 확인 후 실행."):
            st.session_state["_confirm_full_reset"] = True
            st.rerun()
    with full2:
        st.caption(
            "💡 dedup 덕분에 기존 CSV가 손실되지는 않지만, 서버에서 직전 자료가 수정된 경우 "
            "그 수정값이 반영됩니다. ASOS는 4지점 × 26년, GWlevel은 177개소 × 11년치 "
            "전체 재호출이라 시간이 걸립니다."
        )

    # 2단계 confirm — 재실행 시 진행
    if _confirm_destructive(
        "full_reset",
        label="전체 초기화 + 재수집 실행",
        warning="ASOS + GWlevel 일/월 전체 force 재수집 (30~90분 소요). "
                "수집 중 페이지가 멈춥니다. 진짜 진행하시겠습니까?",
    ):
        with st.status("전체 재수집 중 (예상 30~90분)...", expanded=True) as _status:
            # 1) ASOS 전체 (force=True)
            _status.update(label="1/3 ASOS 전체 재수집 (4지점 × 2000~)...",
                           state="running")
            try:
                asos_collector.collect_asos_data(mode="latest", force_refresh=True)
                try:
                    asos_collector.load_asos_data.clear()
                except Exception:
                    pass
                st.write("  ✓ ASOS 완료")
            except TypeError:
                # force_refresh 인자 없으면 mode=latest 만으로 시도
                try:
                    asos_collector.collect_asos_data(mode="latest")
                    st.write("  ✓ ASOS 완료 (force_refresh 미지원)")
                except Exception as e:
                    st.write(f"  ⚠ ASOS 실패: {type(e).__name__}: {e}")
            except Exception as e:
                st.write(f"  ⚠ ASOS 실패: {type(e).__name__}: {e}")
            # 2) GWlevel 일 (force=True, 2015~)
            _status.update(label="2/3 GWlevel 일 force 재수집 (177개소 × 2015~)...",
                           state="running")
            try:
                jeju_gwlevel_collector.collect_all(
                    granularity="day", force=True,
                    default_start="2015-01-01",
                )
                try:
                    jeju_gwlevel_collector.load_station_day_csv.clear()
                except Exception:
                    pass
                st.write("  ✓ GWlevel 일 + parquet 완료")
            except Exception as e:
                st.write(f"  ⚠ GWlevel 일 실패: {type(e).__name__}: {e}")
            # 3) GWlevel 월 (force=True, 2015~)
            _status.update(label="3/3 GWlevel 월 force 재수집 (177개소 × 2015~)...",
                           state="running")
            try:
                jeju_gwlevel_collector.collect_all(
                    granularity="month", force=True,
                    default_start="2015-01-01",
                )
                st.write("  ✓ GWlevel 월 + 유역별 집계 완료")
            except Exception as e:
                st.write(f"  ⚠ GWlevel 월 실패: {type(e).__name__}: {e}")
            _status.update(label="✅ 전체 재수집 완료 — 페이지 새로고침",
                           state="complete", expanded=False)
        st.toast("✅ 전체 재수집 완료", icon="✅")
        time.sleep(1.5)
        st.rerun()

    st.divider()

    # ==========================================================================
    # 🆕 (2026-06-03) 옛 Section A/B/B'/B'' 모두 제거 — Section 0 통합 카드로 일원화.
    #   · Section A  (ASOS 4 metric + 2버튼)         → 통합 카드의 ASOS metric + 통합 버튼
    #   · Section B  (월자료 xls 파이프라인)         → API 자동수집 (collector 가 by_station/* 자동 갱신)
    #   · Section B' (일자료 xls 파이프라인 + parquet) → API 자동수집 (parquet 도 자동 재생성)
    #   · Section B'' (API 자동수집 3버튼)            → 통합 카드와 중복
    # ==========================================================================



    # --------------------------------------------------------------------------
    # Section C: 시스템 상태 체크리스트
    # --------------------------------------------------------------------------
    st.markdown(
        '<p class="section-title" style="margin:0 0 6px;">'
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

        # 🆕 (2026-06-03) JD관측망 xlsx 표시 제거 — config.find_jd_network_file()
        #   은 collector 가 내부적으로만 사용. UI 에 노출할 필요 없음.

    with col_r:
        st.markdown("**폴더 구조** (API 자동수집 산출물)")
        config.ensure_directories()
        # 🆕 (2026-06-03) Row_Data/Month, Row_Data/Day 항목 제거.
        #   xls 다운로드 흐름이 API 자동수집으로 대체되어 의미 없음.
        dirs_status = {
            "data/ASOS":                     config.ASOS_DIR.exists(),
            "data/GWlevel/by_station":       config.GW_STATION_DIR.exists(),
            "data/GWlevel/by_station_month": config.GW_STATION_MONTH_DIR.exists(),
            "data/GWlevel/by_station_day":   config.GW_STATION_DAY_DIR.exists(),
            "data/GWlevel/by_watershed":     config.GW_WATERSHED_DIR.exists(),
            "data/reports":                  (config.DATA_DIR / "reports").exists(),
        }
        for name, exists in dirs_status.items():
            st.write(f"- `{name}`: {'✅' if exists else '❌'}")

    st.divider()

    # --------------------------------------------------------------------------
    # Section D: 분석 리포트 생성 (Build 0.7.2 기능 유지)
    # --------------------------------------------------------------------------
    st.markdown(
        '<p class="section-title" style="margin:0 0 6px;">'
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
            except Exception as e:
                # 거짓 양성 제거 — 저장 실패는 사용자가 알아야 다운로드 버튼만
                # 사용. 다운로드 자체는 그대로 가능.
                st.warning(
                    f"⚠️ 리포트 생성됨(로컬 저장 실패 — 아래 다운로드는 정상 작동). "
                    f"원인: {type(e).__name__}"
                )

            fname = f"jeju_report_{periods['base_date']}_{_dt.now().strftime('%H%M')}.html"

            dl_col, prev_col = st.columns([1, 1])
            with dl_col:
                st.download_button(
                    label="⬇️ HTML 리포트 다운로드",
                    data=report_html.encode("utf-8"),
                    file_name=fname,
                    mime="text/html",
                    use_container_width=True,
                    # MediaFileStorageError 방지 — 위젯 ID 안정화 (호소 #7)
                    key="tab4_html_download",
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
           border-radius:20px;background:var(--color-bg-secondary);color:var(--color-text-secondary);
           font-size:16px;cursor:pointer;font-family:inherit;">
    📖 새 탭에서 리포트 열기
  </button>
  <div style="font-size:15px;color:var(--color-text-secondary);margin-top:4px;text-align:center;">
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

    st.divider()

    # --------------------------------------------------------------------------
    # Section E: 지도 타일 캐시 (2026-05-14)
    # - 제주도 bbox × zoom 10~14 의 V-World 일반/위성 타일을 로컬에 저장
    # - 지도 첫 진입 시 외부 CDN fetch 없이 즉시 표시 → 깜박임 처치
    # - "지도 오프라인 저장" 버튼 → tile_cache.download_jeju_tiles() 호출
    # --------------------------------------------------------------------------
    st.markdown(
        '<p class="section-title" style="margin:0 0 6px;">'
        '🗺️ 지도 타일 캐시</p>',
        unsafe_allow_html=True
    )
    st.markdown(
        "제주도 영역(zoom 10~14)의 V-World 타일 **이미지**와 지도 엔진"
        "(**Leaflet 라이브러리**)을 로컬에 저장합니다. 둘 다 받아 두면 "
        "**인터넷이 없어도** ④·⑪·⑫·⑬ 지도가 정상 표시됩니다. V-World 가 "
        "도로/건물을 갱신했거나 캐시가 손상됐을 때 아래 버튼으로 재다운로드하세요."
    )

    cache_summary = tile_cache.current_cache_summary()
    libs_summary = tile_cache.current_libs_summary()
    cache_cols = st.columns(4)
    with cache_cols[0]:
        st.metric("타일 파일 수", f"{cache_summary['total_files']:,} 장")
    with cache_cols[1]:
        st.metric("디스크 사용", f"{cache_summary['total_bytes'] / 1024 / 1024:.1f} MB")
    with cache_cols[2]:
        n_layers = sum(1 for v in cache_summary['layers'].values() if v['files'] > 0)
        st.metric("활성 레이어", f"{n_layers} / {len(tile_cache.LAYERS)}")
    with cache_cols[3]:
        st.metric(
            "지도 엔진(오프라인)",
            "준비됨 ✅" if libs_summary["ready"] else "미준비 ⚠️",
            help=(
                f"Leaflet 라이브러리 {libs_summary['files']}개 파일 / "
                f"{libs_summary['bytes'] / 1024:.0f} KB. "
                "미준비 상태면 인터넷이 없을 때 지도가 안 뜹니다 — "
                "인터넷 연결 후 아래 '지도 오프라인 저장'을 한 번 실행하세요."
            ),
        )

    with st.expander("레이어별 상세", expanded=False):
        for layer_name, info in cache_summary['layers'].items():
            st.markdown(
                f"- **{layer_name}**: {info['files']:,} 장 / "
                f"{info['bytes'] / 1024 / 1024:.1f} MB"
            )
        est = tile_cache.estimate_tiles()
        st.caption(
            f"예상 전체 (zoom {tile_cache.DEFAULT_ZOOM_RANGE}): "
            f"{est['total_all_layers']:,} 장 / "
            f"약 {est['est_disk_bytes'] / 1024 / 1024:.0f} MB"
        )

    tile_col1, tile_col2 = st.columns([1, 2])
    with tile_col1:
        do_download = st.button(
            "💾 지도 오프라인 저장",
            type="primary",
            use_container_width=True,
            key="tab4_tile_download",
            help="이미 받은 파일은 skip 하므로 매번 안전하게 실행 가능."
        )
    with tile_col2:
        force_refresh = st.checkbox(
            "강제 갱신 (기존 파일 덮어쓰기)",
            value=False,
            key="tab4_tile_force",
            help="V-World 가 도로/건물을 갱신한 경우 체크. 모든 타일 재다운로드."
        )

    st.caption(
        f"💡 지도 엔진(Leaflet) {libs_summary['n_assets']}개 파일은 수초 내 완료, "
        f"이어서 타일 약 {tile_cache.estimate_tiles()['total_all_layers']:,} 장은 "
        f"네트워크 속도에 따라 10~20분. 진행 중 다른 탭으로 이동하면 중단됩니다."
    )

    # P4-2: force_refresh=True 인 경우 confirm 가드 (skip 모드는 안전하므로 면제)
    if do_download:
        if force_refresh:
            st.session_state["_confirm_tile_force"] = True
            st.rerun()
        else:
            st.session_state["_do_tile_download_now"] = True
            st.rerun()

    _proceed_tiles = False
    if st.session_state.pop("_do_tile_download_now", False):
        _proceed_tiles = True
    elif _confirm_destructive(
        "tile_force",
        label="강제 갱신 다운로드",
        warning="기존 타일 파일을 모두 덮어씁니다. 10~20분 소요, 진행 중 취소 불가.",
    ):
        _proceed_tiles = True

    if _proceed_tiles:
        progress = st.progress(0.0)
        status = st.empty()

        def _ui_progress(p: dict) -> None:
            ratio = p["done_total"] / max(p["target_total"], 1)
            progress.progress(min(ratio, 1.0))
            # 50장마다 상태 업데이트 (너무 잦은 UI 업데이트는 streamlit 부담)
            if p["done_total"] % 50 == 0 or p["done_total"] == p["target_total"]:
                status.text(
                    f"진행: {p['done_total']:,}/{p['target_total']:,} | "
                    f"새로 받음 {p['new']} · skip {p['skipped']} · 실패 {p['failed']} | "
                    f"{p['layer']} z={p['z']}"
                )

        # ① 지도 엔진(Leaflet 라이브러리) 먼저 — 적고 빠름(수십 KB), 오프라인의 핵심.
        with st.spinner("지도 엔진(Leaflet 라이브러리) 저장 중..."):
            def _ui_progress_libs(p: dict) -> None:
                ratio = p["done_total"] / max(p["target_total"], 1)
                progress.progress(min(ratio, 1.0))
                status.text(
                    f"지도 엔진: {p['done_total']}/{p['target_total']} | "
                    f"{p['name']}"
                )
            libs_result = tile_cache.download_map_libs(
                progress_cb=_ui_progress_libs,
                force=force_refresh,
            )
        progress.progress(0.0)

        # ② V-World 타일 이미지 (10~20분 소요 가능)
        with st.spinner("V-World 타일 다운로드 중... (10~20분 소요 가능)"):
            result = tile_cache.download_jeju_tiles(
                progress_cb=_ui_progress,
                force=force_refresh,
            )
        progress.empty()
        status.empty()

        # 지도 엔진 결과 안내
        if libs_result["failed"]:
            st.warning(
                f"⚠️ 지도 엔진 {libs_result['failed']}건 실패 "
                f"(새로 받음 {libs_result['new']}·skip {libs_result['skipped']}). "
                "인터넷 연결을 확인 후 다시 실행하세요. "
                "이 파일이 없으면 오프라인에서 지도가 안 뜹니다."
            )
            with st.expander("지도 엔진 실패 목록"):
                for f in libs_result['failure_list']:
                    st.text(str(f))
        else:
            st.success(
                f"✅ 지도 엔진 준비 완료 — 새로 받음 {libs_result['new']}개 / "
                f"{libs_result['bytes']/1024:.0f} KB, skip {libs_result['skipped']}개. "
                "이제 인터넷 없이도 지도가 뜹니다."
            )

        # 타일 결과 안내
        if "error" in result:
            st.error(f"❌ 타일: {result['error']}")
        else:
            st.success(
                f"✅ 타일 완료. 새로 받음 {result['new']:,}장 / "
                f"{result['bytes']/1024/1024:.1f} MB, "
                f"skip {result['skipped']:,}장, 실패 {result['failed']}건. "
                f"소요 {result['elapsed_sec']/60:.1f}분."
            )
            if result['failed']:
                st.warning(
                    f"⚠️ {result['failed']}건 실패. 재실행하면 실패한 타일만 자동 재시도."
                )
                with st.expander("실패 목록 (처음 50건)"):
                    for f in result['failure_list'][:50]:
                        st.text(str(f))

    # ======================================================================
    #  drone data import (DJI Terra -> dashboard)
    # ======================================================================
    st.divider()
    st.subheader("드론 데이터 가져오기 (DJI Terra -> 대시보드)")
    st.caption(
        "DJI Terra 결과물 폴더를 지정하면, 대시보드 data/04_drone 에 자동으로 복사 및 등록합니다."
    )

    # 1. source folder — 네이티브 폴더 탐색 창 (tkinter, 로컬 PC 전용)
    def _open_folder_dialog(initial: str = "") -> str:
        """Windows 네이티브 폴더 선택 대화상자를 열고 선택된 경로를 반환."""
        try:
            import tkinter as tk
            from tkinter import filedialog
            _root = tk.Tk()
            _root.withdraw()
            _root.wm_attributes("-topmost", 1)
            _folder = filedialog.askdirectory(
                title="Terra 작업 결과폴더 찾기",
                initialdir=initial if initial and Path(initial).exists() else "/",
            )
            _root.destroy()
            return str(Path(_folder)) if _folder else ""
        except Exception:
            return ""

    default_src = str(config.DRONE_SOURCE_DIR) if config.DRONE_SOURCE_DIR else ""
    src_folder = st.session_state.get("drone_src_folder", default_src)

    # 현재 선택된 경로 표시
    if src_folder:
        st.markdown(
            f"📂 **선택된 폴더:** `{src_folder}`",
        )
    else:
        st.markdown("📂 **선택된 폴더:** *(없음 — 아래 버튼으로 선택해 주세요)*")

    col_browse, col_scan, col_reset = st.columns([2, 2, 1])
    with col_browse:
        if st.button("📂 폴더 찾아보기", use_container_width=True,
                     help="Windows 탐색기 창이 열립니다. Jeju_Drone 루트 폴더를 선택하세요."):
            _picked = _open_folder_dialog(src_folder)
            if _picked:
                st.session_state["drone_src_folder"] = _picked
                # 새 폴더 선택 시 이전 스캔 결과 초기화
                st.session_state.pop("drone_scan_results", None)
                st.session_state.pop("drone_import_done", None)
            st.rerun()
    with col_scan:
        do_scan = st.button("🔍 폴더 스캔", use_container_width=True,
                            disabled=not src_folder)
    with col_reset:
        if st.button("초기화", use_container_width=True):
            for k in ("drone_scan_results", "drone_import_running",
                      "drone_import_progress", "drone_import_done",
                      "drone_user_meta", "drone_src_folder"):
                st.session_state.pop(k, None)
            st.rerun()

    # 2. scan
    if do_scan:
        src_folder = st.session_state.get("drone_src_folder", "")
        _scan_path = Path(src_folder) if src_folder else None

        if not src_folder or not (_scan_path and _scan_path.exists()):
            st.error("폴더가 선택되지 않았거나 존재하지 않습니다. 📂 폴더 찾아보기 버튼으로 먼저 선택해 주세요.")
        else:
            # 혹시 미션 하위폴더를 선택한 경우 자동으로 부모 폴더로 조정
            _has_terra = any(
                (_scan_path / sub).exists() for sub in ("map", "models", "AT")
            )
            _has_missions = any(
                d.is_dir() and any((d / sub).exists() for sub in ("map", "models", "AT"))
                for d in _scan_path.iterdir()
            ) if _scan_path.is_dir() else False
            if _has_terra and not _has_missions:
                st.info(
                    f"선택한 폴더가 미션 폴더인 것 같습니다. "
                    f"상위 폴더({_scan_path.parent.name})를 루트로 사용합니다."
                )
                _scan_path = _scan_path.parent
                st.session_state["drone_src_folder"] = str(_scan_path)
                src_folder = str(_scan_path)
            with st.spinner("폴더 스캔 중..."):
                _importer = DroneImporter(
                    source_root=_scan_path,
                    dst_root=config.DRONE_DATA_ROOT,
                )
                _scan_results = _importer.scan()
            st.session_state["drone_scan_results"] = _scan_results
            st.session_state.pop("drone_import_done", None)

    # 3. show scan results
    scan_results = st.session_state.get("drone_scan_results")
    if scan_results is not None:
        if not scan_results:
            st.warning("인식된 Terra 미션 폴더가 없습니다. 폴더 구조를 확인해 주세요.")
        else:
            _rows = []
            for _r in scan_results:
                _sl = {"new": "신규", "exists": "이미 있음", "partial": "일부만"}.get(_r.status, _r.status)
                _tm = _r.terra_meta
                _rows.append({
                    "폴더명":    _r.folder_name,
                    "상태":      _sl,
                    # Arrow 직렬화 안전: 숫자+"-" 혼합 컬럼 방지 → 전부 문자열.
                    "RTK":       str(_tm.get("rtk_mode") or "-"),
                    "이미지":    ("-" if _tm.get("image_count") is None else str(_tm["image_count"])),
                    "RMSE(m)":   ("-" if _tm.get("rmse_m") is None else str(_tm["rmse_m"])),
                    "GSD(cm)":   ("-" if _tm.get("gsd_cm") is None else str(_tm["gsd_cm"])),
                    "2D타일":    "O" if _r.has_xyz_tiles else "-",
                    "3D Tiles":  "O" if _r.has_3d else "-",
                    "PLY":       "O" if _r.has_ply else "-",
                })
            st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True)

            new_or_partial = [_r for _r in scan_results if _r.status in ("new", "partial")]

            if not new_or_partial:
                st.success("모든 미션이 이미 대시보드에 등록되어 있습니다.")
            else:
                st.info(f"가져올 미션: {len(new_or_partial)}건 (신규 및 일부 완료 포함)")

                # 미션 1개 선택
                st.markdown("#### 처리할 미션 선택")
                _mission_names = [r.folder_name for r in new_or_partial]
                _selected_name = st.selectbox(
                    "미션 1개를 선택하세요 (한 번에 1개씩 처리 권장)",
                    options=_mission_names,
                    key="drone_mission_select",
                )
                new_or_partial = [r for r in new_or_partial if r.folder_name == _selected_name]

                # 4. meta input per mission
                st.markdown("#### 미션 정보 입력")
                st.caption("Terra 에서 자동으로 읽지 못한 항목을 직접 입력해 주세요.")

                _user_meta_map = st.session_state.get("drone_user_meta", {})

                for _r in new_or_partial:
                    _tm = _r.terra_meta
                    _mid = _r.folder_name
                    _prev = _user_meta_map.get(_mid, {})

                    with st.expander(f"{_mid}", expanded=(_r.status == "new")):
                        _cols = st.columns(2)
                        with _cols[0]:
                            _name_val = st.text_input(
                                "표시 이름 (name)",
                                value=_prev.get("name", _mid),
                                key=f"drone_meta_name_{_mid}",
                            )
                            _sid_val = st.text_input(
                                "site_id",
                                value=_prev.get("site_id", _mid.split("_")[0] if "_" in _mid else _mid),
                                key=f"drone_meta_siteid_{_mid}",
                            )
                            _stype_val = st.selectbox(
                                "시설 유형",
                                DroneImporter.SITE_TYPES,
                                index=(
                                    DroneImporter.SITE_TYPES.index(_prev.get("site_type", "저수지"))
                                    if _prev.get("site_type") in DroneImporter.SITE_TYPES else 0
                                ),
                                key=f"drone_meta_sitetype_{_mid}",
                            )
                        with _cols[1]:
                            _eup_val = st.text_input(
                                "읍면동",
                                value=_prev.get("eup_myeon_dong", ""),
                                key=f"drone_meta_eup_{_mid}",
                                placeholder="예: 구좌읍 송당리",
                            )
                            _fdate_val = st.text_input(
                                "촬영 연월",
                                value=_prev.get("flight_date", _tm.get("flight_date", "")),
                                key=f"drone_meta_date_{_mid}",
                                placeholder="예: 2026-05 (YYYY-MM 형식)",
                                help="YYYY-MM 형식만 허용 (예: 2026-05). 잘못된 형식은 import 차단.",
                            )
                            # P-fix I5 (2026-05-29): 형식 검증 — 잘못된 값은 즉시 경고.
                            import re as _re
                            if _fdate_val and not _re.fullmatch(r"\d{4}-\d{2}", _fdate_val.strip()):
                                st.caption(f"⚠️ '{_fdate_val}' — YYYY-MM 형식이 아닙니다.")
                            _memo_val = st.text_input(
                                "메모 (선택)",
                                value=_prev.get("memo", ""),
                                key=f"drone_meta_memo_{_mid}",
                            )
                        _user_meta_map[_mid] = {
                            "name":           _name_val,
                            "site_id":        _sid_val,
                            "site_type":      _stype_val,
                            "eup_myeon_dong": _eup_val,
                            "flight_date":    _fdate_val,
                            "memo":           _memo_val,
                        }

                st.session_state["drone_user_meta"] = _user_meta_map

                # 5. import button
                st.markdown("---")
                # P-fix I5 (2026-05-29): import 전 메타 검증 — 모든 미션의
                # flight_date 가 YYYY-MM 형식이고 eup_myeon_dong 비어있지 않아야
                # 활성화. 빈 값/오타가 그대로 meta.json·registry·csv 에 기록되어
                # 향후 검색/그룹화 깨지는 회귀를 사전 차단.
                import re as _re_v
                _meta_invalid_reasons = []
                for _mid_v, _um_v in _user_meta_map.items():
                    _fd = (_um_v.get("flight_date") or "").strip()
                    _eu = (_um_v.get("eup_myeon_dong") or "").strip()
                    _nm = (_um_v.get("name") or "").strip()
                    if not _nm:
                        _meta_invalid_reasons.append(f"{_mid_v}: 이름 비어있음")
                    if not _eu:
                        _meta_invalid_reasons.append(f"{_mid_v}: 읍면동 비어있음")
                    if not _fd or not _re_v.fullmatch(r"\d{4}-\d{2}", _fd):
                        _meta_invalid_reasons.append(f"{_mid_v}: 촬영 연월 형식 오류")
                _meta_valid = len(_meta_invalid_reasons) == 0
                if not _meta_valid:
                    st.warning(
                        "⚠️ 메타 검증 실패 — 다음 항목을 수정해야 import 가능:\n"
                        + "\n".join(f"  - {r}" for r in _meta_invalid_reasons[:5])
                        + ("\n  ..." if len(_meta_invalid_reasons) > 5 else "")
                    )
                _col_imp, _ = st.columns([1, 4])
                with _col_imp:
                    do_import = st.button(
                        "가져오기 시작",
                        use_container_width=True,
                        disabled=(
                            st.session_state.get("drone_import_running", False)
                            or not _meta_valid
                        ),
                    )

                if do_import and not st.session_state.get("drone_import_running", False):
                    # 진행 상태 dict — 메인 스레드와 백그라운드 스레드가 공유하는
                    # 단순 Python dict (session_state에 참조로 저장).
                    # 스레드는 이 dict만 수정하고, st.session_state에는 절대 접근하지 않음.
                    _prog = {
                        "running":         True,
                        "done":            False,
                        "current_mission": "",
                        "phase":           "",
                        "files_done":      0,
                        "bytes_done":      0,
                        "completed_count": 0,
                        "done_missions":   [],
                        "failed_missions": [],
                        "total_missions":  len(new_or_partial),
                    }
                    st.session_state["drone_import_progress"] = _prog
                    st.session_state["drone_import_running"] = True
                    st.session_state.pop("drone_import_done", None)

                    # user_meta를 스레드 시작 전에 캡처 (스레드 내 session_state 접근 금지)
                    _captured_meta = dict(st.session_state.get("drone_user_meta", {}))
                    _captured_src  = st.session_state.get("drone_src_folder", "")

                    def _run_import(
                        _p=_prog,
                        _src_folder=_captured_src,
                        _missions=new_or_partial,
                        _user_meta=_captured_meta,
                    ):
                        """백그라운드 복사 스레드.
                        st.session_state 접근 금지 — _p dict만 수정.

                        P-fix C4 (2026-05-29): _ImportLock 으로 cross-session 직렬화.
                        다른 브라우저 탭/세션에서 동시 import 시도 시 ImportLockError
                        → _p['lock_error'] 기록 후 즉시 종료 (들여쓰기 변경 최소화 위해
                        with 블록 대신 명시 acquire/release).
                        """
                        from src.drone.importer import _ImportLock, ImportLockError
                        _lock_path = config.DRONE_DATA_ROOT / ".import.lock"
                        _lock = _ImportLock(_lock_path)
                        try:
                            _lock.__enter__()
                        except ImportLockError as _e:
                            _p["lock_error"] = str(_e)
                            _p["done"] = True
                            _p["failed_missions"] = [m.folder_name for m in _missions]
                            return
                        try:
                            _imp = DroneImporter(
                                source_root=Path(_src_folder),
                                dst_root=config.DRONE_DATA_ROOT,
                            )

                            for _sr in _missions:
                                _mid = _sr.folder_name
                                _um  = _user_meta.get(_mid, {})
                                _p["current_mission"] = _mid

                                _progress = ImportProgress(mission_id=_mid)

                                def _cb(_pg, __p=_p):
                                    __p["phase"]      = _pg.phase
                                    __p["files_done"] = _pg.files_done
                                    __p["bytes_done"] = _pg.bytes_done

                                _ok = _imp.copy_mission(_sr, _progress, cb=_cb)

                                if _ok:
                                    try:
                                        _imp.write_meta_json(
                                            dst_dir=_sr.dst_dir,
                                            mission_id=_mid,
                                            name=_um.get("name", _mid),
                                            terra_meta=_sr.terra_meta,
                                            user_meta=_um,
                                        )
                                    except Exception:
                                        pass
                                    try:
                                        _imp.register_to_registry(
                                            mission_id=_mid,
                                            name=_um.get("name", _mid),
                                            site_id=_um.get("site_id", _mid),
                                            site_type=_um.get("site_type", "기타"),
                                            site_category=_um.get("site_type", "기타"),
                                            eup_myeon_dong=_um.get("eup_myeon_dong", ""),
                                            flight_date=_um.get("flight_date", ""),
                                            terra_meta=_sr.terra_meta,
                                        )
                                    except Exception:
                                        pass
                                    try:
                                        _imp.register_to_csv(
                                            mission_id=_mid,
                                            name=_um.get("name", _mid),
                                            site_type=_um.get("site_type", "기타"),
                                            eup_myeon_dong=_um.get("eup_myeon_dong", ""),
                                            flight_date=_um.get("flight_date", ""),
                                            terra_meta=_sr.terra_meta,
                                        )
                                    except Exception:
                                        pass
                                    _p["done_missions"].append(_mid)
                                else:
                                    _p["failed_missions"].append(_mid)
                                _p["completed_count"] += 1

                        except Exception as _ex:
                            _p["failed_missions"].append(f"오류: {_ex}")
                        finally:
                            # P-fix C4: 작업 종료 시 락 해제 (정상·예외 무관).
                            try:
                                _lock.__exit__(None, None, None)
                            except Exception:
                                pass
                            # 완료 신호 — session_state 대신 dict 플래그만 사용
                            _p["running"] = False
                            _p["done"]    = True

                    threading.Thread(target=_run_import, daemon=True).start()
                    st.rerun()

        # 진행 상태 표시 (폴링) — _prog dict의 "running" 플래그로 판단
        _p_now = st.session_state.get("drone_import_progress", {})
        if _p_now.get("running"):
            _cur   = _p_now.get("current_mission", "?")
            _done  = _p_now.get("completed_count", 0)
            _total = _p_now.get("total_missions", 1)
            _phase = _p_now.get("phase", "")
            _mb    = _p_now.get("bytes_done", 0) / 1024 / 1024
            _files = _p_now.get("files_done", 0)
            st.progress(_done / _total if _total else 0)
            st.info(
                f"[{_done}/{_total}] {_cur} - {_phase} | "
                f"{_files:,} 파일 | {_mb:.1f} MB"
            )
            time.sleep(1)
            st.rerun()

        # 완료 감지 — _prog["done"] True -> session_state 플래그 기록 후 rerun
        if _p_now.get("done") and not st.session_state.get("drone_import_done"):
            st.session_state["drone_import_running"] = False
            st.session_state["drone_import_done"]    = True
            st.rerun()

        # 완료 결과 표시
        if st.session_state.get("drone_import_done"):
            _p_fin  = st.session_state.get("drone_import_progress", {})
            _ok_lst = _p_fin.get("done_missions", [])
            _fl_lst = _p_fin.get("failed_missions", [])
            _lock_err = _p_fin.get("lock_error")
            # P-fix C4: 락 에러는 별도로 강조 표시
            if _lock_err:
                st.error(
                    f"🔒 다중 import 차단 (C4 락): {_lock_err}\n"
                    "다른 브라우저 탭/세션에서 import 가 진행 중입니다. "
                    "완료를 기다리거나 lock 파일을 수동 삭제하세요."
                )
            if _ok_lst:
                st.success("완료: " + ", ".join(_ok_lst))
            if _fl_lst:
                st.error("실패:")
                for _f in _fl_lst:
                    st.text(f"  {_f}")
            st.info("대시보드를 재시작하면 새 미션이 드론 탭에 나타납니다.")

    # ── [Build 0.9 — 2026-05-30] 토지피복(시설재배지) 빌드 현황 ──────────
    # render() 본문 4-space level — 위 expander 블록 밖에서 호출.
    _render_landcover_section()


# ============================================================================
#  Section L: 토지피복(시설재배지) 빌드 현황 — Build 0.9 (2026-05-30)
#  scripts/build_greenhouse_stats.py 가 생성한 CSV 의 메타·검증현황만 표시.
#  빌드 자체는 PC 명령으로 안내 (Streamlit 안 장시간 subprocess 회피).
# ============================================================================
def _render_landcover_section() -> None:
    from src.analysis import landcover_loader as LCL  # 지역 import (지연 로드)

    st.markdown(
        '<p class="section-title" style="margin:24px 0 6px;font-size:18px;'
        'font-weight:600;">🌱 토지피복 — 시설재배지 빌드 현황</p>',
        unsafe_allow_html=True,
    )

    df = LCL.load_greenhouse_yearly()
    yearly_csv = config.LANDCOVER_GREENHOUSE_YEARLY
    raw_dir    = config.LANDCOVER_RAW_DIR

    if df.empty:
        st.warning(
            "빌드된 CSV가 없습니다. 아래 명령으로 PC에서 1회 실행하세요."
        )
    else:
        n_year = int(df["연도"].nunique())
        ha_min = float(df["면적_ha"].min())
        ha_max = float(df["면적_ha"].max())
        flags = df["검증"].fillna("ok").value_counts().to_dict()
        n_ok     = int(flags.get("ok", 0))
        n_susp   = int(flags.get("suspect", 0))
        n_interp = int(flags.get("interp", 0))
        mtime = (
            pd.Timestamp(yearly_csv.stat().st_mtime, unit="s").strftime("%Y-%m-%d %H:%M")
            if Path(yearly_csv).exists() else "—"
        )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("연도 수", f"{n_year}")
        c2.metric("면적 범위 (ha)", f"{ha_min:,.0f} ~ {ha_max:,.0f}")
        c3.metric("ok / suspect / interp", f"{n_ok} / {n_susp} / {n_interp}")
        c4.metric("마지막 빌드", mtime)

    cA, cB = st.columns([1, 1])
    with cA:
        if st.button("🔄 데이터 새로고침(캐시 리셋)",
                     key="btn_landcover_clear_cache",
                     use_container_width=True):
            LCL.clear_caches()
            st.success("로더 캐시를 비웠습니다. 페이지를 새로고침하세요.")
    with cB:
        total_b = 0; n_files = 0
        if Path(raw_dir).exists():
            for p in Path(raw_dir).glob("*"):
                if p.is_file():
                    total_b += p.stat().st_size
                    n_files += 1
        st.caption(
            f"raw 캐시: {n_files} 파일 · {total_b/1024/1024:.1f} MB "
            f"({raw_dir})"
        )

    st.markdown("**PC 빌드 명령** (시설재배 데이터 갱신 — 잠자기 전 권장)")
    # 21차 사용자 요청 1: --ri 추가 (tab43 리 단위 분석 누락 방지)
    st.code("python scripts\\build_greenhouse_stats.py --all --region --ri",
            language="bat")
    st.caption(
        "옵션: `--discover-years` 만 주면 WFS 가용 연도만 점검합니다. "
        "신규 연도(2026, 2027 …)는 WFS에 등재되면 `--all` 실행 시 자동 포함. "
        "신규 연도만 빠르게 추가하려면 `--year 2026 --region --ri` 권장 (raw 캐시 보존, 5분 이내)."
    )

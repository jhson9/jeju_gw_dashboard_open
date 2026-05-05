# ==============================================================================
#  제주도 지하수위·강수량 분석 대시보드
#  파일명: process_gwlevel.py (프로젝트 루트)
#  모듈: 지하수위 데이터 통합 처리 진입점
# ------------------------------------------------------------------------------
#  Build: 0.6
#  최종 수정일: 2026-04-22
# ------------------------------------------------------------------------------
#  Changelog:
#  - v0.6 (2026-04-22): 최초 생성.
#                       xls 파서 + 수역 매핑 집계를 한 번에 실행하는
#                       편의 스크립트. 초보자는 이 하나만 실행하면 됨.
# ------------------------------------------------------------------------------
#  【실행 방법】
#      python process_gwlevel.py
#
#  【수행 작업】
#   1) data/Row_Data/JD*.xls 전체 파싱 (S11 센서)
#   2) data/GWlevel/by_station/ 에 관측소별 CSV 저장
#   3) 0_JD관측망_정보.xlsx 로 수역 매핑
#   4) data/GWlevel/by_watershed/ 에 수역별 월별 평균 CSV 저장
# ==============================================================================

from src.collectors import gwlevel_parser
from src.analysis import watershed_mapper


def main():
    print()
    print("#" * 70)
    print("#  제주도 지하수위 데이터 통합 처리 파이프라인 (Build 0.6)")
    print("#" * 70)

    # Step 1: xls 파싱
    print("\n[1/2] xls → CSV 파싱\n")
    parse_result = gwlevel_parser.run_full_pipeline(verbose=True)

    if parse_result["success_count"] == 0:
        print("\n❌ 파싱 실패. 다음을 확인하세요:")
        print("   - data/Row_Data/ 에 JD*.xls 파일이 있는지")
        print("   - 파일에 'S11' 시트가 포함되어 있는지")
        return

    # Step 2: 수역 집계
    print("\n\n[2/2] 수역별 집계\n")
    try:
        watershed_mapper.run_watershed_pipeline(verbose=True)
    except FileNotFoundError as e:
        print(f"\n⚠️ {e}")
        print("   0_JD관측망_정보.xlsx 를 프로젝트 루트에 배치 후 다시 실행하세요.")
        return

    print()
    print("#" * 70)
    print("#  ✅ 모든 지하수위 처리 완료")
    print("#" * 70)
    print("   대시보드 새로고침 시 반영됩니다.")
    print("      streamlit run src/dashboard/app.py")


if __name__ == "__main__":
    main()

# 34/35 탭 — DoD 시계열 분석 (2D + 3D) 개발 기록

> **2026-06-06 통합 완료**: 실험적 tab36/37 (DoD) 의 안정 검증 후 tab34/35 로 승격·통합.
> 원본 tab34/35 (DoD 없음) 는 `src/dashboard/tabs/_archive/` 에 보관 (rollback 가능).

작성일: 2026-06-04 (Build 1.8.1) · 통합일: 2026-06-06
최종 Build: **1.8.1** (안정, 사용자 시각 검증 완료) + 통합
관련 메모리 토큰: `[[project-drone-dod-consolidated-34-35]]` (2026-06-06 신규),
                   `[[project-drone-dod-build-1.8.1-stable]]`

## 개요

DJI Terra 의 DSM (Digital Surface Model) 두 시점 차분으로 표고 변화를 시각화하는 실험적 탭. 원본 34/35 탭은 그대로 보존하며 사본으로 36 (2D + DoD) / 37 (3D + DoD) 신규 생성.

- **36탭** (`tab36_drone_diff_dod.py`): 2D 정사영상 좌·우 동기화 + DoD 색상 overlay
- **37탭** (`tab37_drone_diff_dod_3d.py`): 3D Cesium 메쉬 좌·우 동기화 + DoD 표면 안착

## 기술 스택

| 구성 | 도구 |
|---|---|
| 2D 좌·우 동기화 | Leaflet 1.9.4 + leaflet.sync |
| 3D 메쉬 렌더링 | CesiumJS 1.141 (오프라인 번들) |
| DSM 차분 계산 | rasterio + numpy + pyproj |
| 색상 매핑 | RdBu_r 5-stop LUT (matplotlib 의존성 회피) |
| Edge 노이즈 완화 | scipy.ndimage.median_filter (3x3) |
| 정적 서빙 | pdf_server :8766 (same-origin) |
| Streamlit 통신 | iframe + URL hash + postMessage |

## 핵심 산출물 위치

```
src/drone/diff.py                                  # DsmDiffAnalyzer.compute_diff()
src/dashboard/tabs/_dod_helpers.py                 # compute_dod, dod_bounds_str, ...
src/dashboard/tabs/_drone_helpers.py               # url_for_diff_viewer_dod[_3d]()
src/dashboard/tabs/tab36_drone_diff_dod.py         # 2D + DoD 탭
src/dashboard/tabs/tab37_drone_diff_dod_3d.py      # 3D + DoD 탭
src/dashboard/static/drone_viewer/
    ├── diff_viewer_dod.html                       # 2D viewer
    └── diff_viewer_dod_3d.html                    # 3D viewer (Build 1.8)
data/04_drone/<after_mission>/derived/dod_cache/   # PNG/JSON 캐시
```

## Build 1.0 → 1.8 변경 요약

| Build | 핵심 변경 | 사용자 제보 / 진단 |
|---|---|---|
| 1.0 | `viewer.imageryLayers` + globe (WGS84 ellipsoid) | DoD 가 메쉬 수백 m 아래 분리 표시 |
| 1.1 | mesh translucency 추가 (메쉬 반투명화) | globe DoD 가 메쉬에 가려져 안 보임 |
| 1.2 | Rectangle Entity at boundingSphere.center + altOffset | 메쉬 평면 1장이라 굴곡 못 따라감 |
| 1.3 | `tileset.imageryLayers.add()` (Cesium 1.130+ API) | DJI Terra b3dm 호환성 미달 — silent fail |
| 1.4 | 3중 안전망 (tileset drape + Rectangle + globe) | globe 이 메쉬 아래로 또 보임 |
| 1.5 | globe 제거 + altOffset 기본 -3m | 여전히 메쉬 위 3m 떠 있음 |
| 1.6 | `scene.sampleHeight()` 중심 1점 자동 보정 | 1점은 식생/돌출물에 영향 받음 |
| 1.7 | **9점 sampling (중심+4모서리+4변중점) + 지면 MIN + 0.1m** | ✅ 메쉬 표면 정확 안착 |
| 1.8 | **flyTo 버튼 + master 좌↔우 swap** | UX 향상 |
| 1.8.1 | **TDZ fix + master swap UI 제거** | `masterViewer` const 선언 위치를 leftViewer/rightViewer 직후로 이동 (Build 1.8 의 L917 → L392). 좌/우 swap 라디오 제거 — 우측 master 고정 |

## Build 1.8 사용자 컨트롤 (37탭)

### 5컬럼 슬라이더 한 행

| 1. 🎨 DoD 표시 | 2. 🌫️ DoD 불투명도 | 3. 🪜 DoD 높이 (지면 +m) | 4. 🎯 임계치 ±m | 5. 🔍 3D 디테일 (SSE) |
|---|---|---|---|---|
| 토글 | 0~1 (기본 0.75) | -5~+10m (기본 0.1m) | 0~1m (시설물별 권장) | 4~16 (기본 4) |

### 추가 UI

- **🎮 조작 위치 (좌/우)** — radio 토글, master/slave 동적 swap
- **🔴 최대 증가 / 🔵 최대 감소** 버튼 — viewer 안 좌·우 panel 모두 4개, 클릭 시 양쪽 카메라가 그 지점으로 flyTo (1.2초 부드러운 이동)
- **🪟 메쉬 투명도 (= 1.0 고정)** — Build 1.6 이후 불필요, UI 에 노출 안 됨

## 알고리즘 핵심

### compute_diff() — Phase 1

```python
1. rasterio open: 두 DSM (target_crs = after CRS, EPSG:32652 일반적)
2. transform_bounds → projected 교집합
3. 공통 grid: gsd = max(GSD_before, GSD_after, 0.05m), MAX_DIM 4000 (이상 시 다운샘플)
4. reproject bilinear → 동일 grid
5. dz = z_after − z_before
6. RTK 절대편향 보정: dz -= median(dz)  # 안정 영역 다수 가정
7. 3×3 median filter (scipy) — 가장자리 halo 완화
8. argmax / argmin → projected (x,y) → WGS84 (lat,lon) → stats
9. RdBu_r colormap LUT → RGBA PNG 저장
10. JSON 사이드카: png_bbox_wgs84, stats 전체
```

### scene.sampleHeight 9점 보정 — Build 1.7

```javascript
// DoD bbox 안의 9개 지점에서 메쉬 표면 고도 sampling
중심 + 4모서리 + 4변중점 → viewer.scene.sampleHeight() 각자 호출
유효 결과만 모음 → MIN = 지면, MAX = 꼭대기
DoD 평면 height = groundAlt + altOffset (사용자 슬라이더, 기본 +0.1m)
타일 로드 대기 후 최대 6회 재시도 (0.8s 간격)
status bar: "🎨 DoD @ 240.6m (지면 240.5, 꼭대기 244.8, 9점)"
```

## 발견·해결한 회귀 위험

| # | 문제 | 4팀 진단 | 해결 |
|---|---|---|---|
| 1 | hash 변경되면 iframe reload 안 됨 → 슬라이더 무반응 | path+query 동일하면 브라우저 reload 차단. 2026-05-25 hashchange listener 제거가 잘못 | hashchange listener 복구 + postMessage 위임 |
| 2 | SSE 슬라이더 거의 차이 없음 | `scene.maximumScreenSpaceError` (globe용) 잘못 설정. 3D Tileset LOD 는 `tileset.maximumScreenSpaceError` 가 결정 | tileset 단위 직접 설정 + `let SSE_STATIC` (변수 자체 갱신) |
| 3 | 탱크 가장자리 ±수m halo (실제 변화 없음) | DSM 은 수직 표고만 측정, 벽면(수직면) 정보 없음. sub-pixel 수평 시프트로 oscillation | 3×3 median filter + 사용자 안내 expander |
| 4 | 차량처럼 작은 가변 구조물 검출 약함 | 2025-01 RTK Single (RMSE 0.93m) ↔ 2026-05 RTK Fix (RMSE 0.42m). 수평 오차 ~1m가 차량 너비와 비슷 → 신호 cancel out | 사용자 안내. Phase 2 (M3C2) 권장 |
| 5 | 2D 좌·우 ghost (이중 이미지) | PNG fallback ImageOverlay + HD tile XYZ 가 georeferencing 미세 차이로 가장자리 ghost | PNG fallback 기본 비활성 (Layer control 에서 수동 토글) |

## 시각 검증 결과 (2026-06-04, Build 1.8.1)

사용자 스크린샷 4매로 최종 시각 검증 완료. 모든 핵심 기능 정상 작동.

### 검증 케이스 1 — 구좌 종달 저수조 (jongdal_reservoir)

| 항목 | 좌측 (2025-01) | 우측 (2026-05) |
|---|---|---|
| 계절 | 겨울 (마른 갈색 풀밭) | 봄 (녹색 식생) |
| 카메라 view | 동일 (master-slave 동기화 ✅) | 동일 |
| DoD 표시 | 거의 없음 (변화 없음 = 흰색) | 빨강 patches (도로 옆 식생 성장·퇴적), 파랑 patches (식생 감소·침식) |
| 메쉬 정합성 | ✅ DoD 가 메쉬 표면에 자연스럽게 입혀짐 | ✅ |
| flyTo 버튼 | 🔴 최대 증가 / 🔵 최대 감소 양쪽 panel 정상 표시 | ✅ |

### 검증 케이스 2 — 구좌 덕천 저수조 (deokcheon_reservoir)

| 항목 | 좌측 (2025-05) | 우측 (2026-05) |
|---|---|---|
| 시점 차이 | 1년 (같은 봄) | 같은 5월 |
| 검출 사례 | **빨간 사각형** = 새 자재/구조물 (붉은 흙더미 + 검정 차량) 명확히 검출 | 흰 곤포 사일리지 더미가 메쉬 표면에 정확히 표현 (DSM 에 포함됨) |
| 파랑 분포 | 도로 옆 식생 제거·굴착 영역 | 거의 없음 (이미 메쉬에 silage 통합) |
| TDZ 에러 | ✅ 사라짐 — 좌·우 양쪽 정상 렌더링 | ✅ |

### 작동 확인 매트릭스 (Build 1.8.1)

| 슬라이더 / 기능 | 상태 | 비고 |
|---|---|---|
| 🎨 DoD 표시 토글 | ✅ 정상 | postMessage 즉시 반영 |
| 🌫️ DoD 불투명도 | ✅ 정상 | hashchange listener 복구 후 작동 |
| 🪜 DoD 높이 (지면 +m) | ✅ 정상 | 기본 +0.1m, 9점 sampling 기반 지면 자동 계산 |
| 🎯 임계치 ±m | ✅ 정상 | PNG 자체 재생성 (별도 메커니즘) |
| 🔍 3D 디테일 (SSE) 4~16 | ✅ 정상 | tileset.maximumScreenSpaceError 직접 설정 |
| 🔴 최대 증가 flyTo | ✅ 정상 | argmax 좌표로 1.2초 부드러운 이동 |
| 🔵 최대 감소 flyTo | ✅ 정상 | argmin 좌표로 1.2초 부드러운 이동 |
| master-slave 동기화 | ✅ 정상 | 우측 조작 → 좌측 자동 추종 |
| TDZ 초기화 에러 | ✅ 해결됨 | masterViewer const 선언 위치 수정 |

### 본질적 한계 재확인 (DSM 차분의 특성)

스크린샷에서 명확히 관찰된 현상들:

| 관찰 | 원인 (변경 불가) |
|---|---|
| 종달 저수조 식생 영역 광범위 빨강·파랑 | 계절 변화 (겨울 마른 풀 ↔ 봄 녹색 식생) — DSM 변화 정상 검출 |
| 덕천 저수조 흰 곤포 더미 위에 DoD 색 거의 없음 | 사일리지 더미가 양쪽 미션 DSM 에 모두 포함되어 차이 없음 (둘 다 동시점에 가까움) |
| 가장자리 noise 있음 | 메쉬 경계에서 sub-pixel 시프트 (median filter 후 잔량) |
| 평지에 빨강 patches | 식생 성장/퇴적 — 진짜 변화 |

→ **본질적 한계는 Phase 2 (점군 M3C2) 에서 해결**

## 추가 권장 작업 (이번 세션 범위 밖)

### 데이터 품질 — 가장 큰 변화 가능

| 작업 | 효과 | 비용 |
|---|---|---|
| 2025-01 미션 재촬영 (RTK Fix) | 차량·작은 구조물 검출 가능 | 드론 비행 1회 |
| DJI Terra 재 export (zoom 23, LOD +1) | 더 정밀한 2D 타일 + 3D 메쉬 | 컴퓨팅 + ~+10GB |
| 점군 LAS export | Phase 2 M3C2 (벽면 변화) | DJI Terra 옵션 + LAS 처리 |

### 코드 확장 (UX)

- **2D ↔ 3D 동기화 view** (36탭 ↔ 37탭 카메라 연동) — 큰 비용, 사용자 보류
- DoD 변화 영역 자동 클러스터링 + "다음 변화 지점" 순차 탐색
- threshold 자동 추천 (시설물 타입 + 미션 RTK 모드 기반)

### Phase 2 (점군 M3C2)

`src/drone/diff.py` 의 DsmDiffAnalyzer 골격 옆에 별도 Phase2Analyzer 추가:
- Open3D ICP 정렬
- py4dgeo M3C2 distance per-point
- 벽면/측면 변화 (DSM 차분 한계 극복)
- 차량 등 가변 구조물 검출 정확도 향상

## 통합 결정 — 2026-06-06 옵션 B (승격) 선택 완료

사용자 결정: **옵션 B (36/37 → 34/35 승격)** 적용.

### 통합 작업 (5팀 에이전트 합의)

| 단계 | 작업 | 위치 |
|---|---|---|
| 1 | 회귀 14팀: 원본 백업 | `_archive/tab34_drone_diff_pre_dod_consolidation.py` + `tab35_…` |
| 2 | Python 5팀: tab36 컨텐츠 → tab34 (위젯 키 `tab36_*` → `tab34_*`), tab37 → tab35 동일 | `tab34_drone_diff.py`, `tab35_drone_diff_3d.py` |
| 3 | 라우팅 18팀: `app.py` tab_names 에서 "36/37" 제거, tabs[15/16] 블록 삭제, downstream −2 shift | `app.py` |
| 4 | CSS nth-child 인덱스: 18→16 (농업통계), 21→19 (관리) | `app.py` |
| 5 | sessionStorage KEY: v7 → v8 (옛 인덱스 폐기) | `app.py` |
| 6 | tab36/37 파일: 권한 문제로 미삭제 → deprecated stub 으로 교체 (해롭지 않음) | `tab36_drone_diff_dod.py`, `tab37_drone_diff_dod_3d.py` |

### 통합 후 상태

- **탭 수**: 21 → **19** (36/37 제거)
- **34탭**: 시계열 분석(2D) — DoD 색상 overlay 포함 (이전 tab36 의 안정 버전)
- **35탭**: 시계열 분석(3D) — DoD 메쉬 표면 안착 포함 (이전 tab37 의 Build 1.8.1)
- **🧪 실험적 표식 제거**: 일반 탭과 동일한 외관
- **컴파일**: 모든 파일 `py_compile` OK
- **롤백 가능**: `_archive/` 백업본 + tab36/37 stub 모두 보존

### 변경 파일 목록 (2026-06-06)

```
src/dashboard/tabs/
  tab34_drone_diff.py                            ← 신규 (tab36 컨텐츠 + 키 변경)
  tab35_drone_diff_3d.py                         ← 신규 (tab37 컨텐츠 + 키 변경)
  tab36_drone_diff_dod.py                        ← deprecated stub
  tab37_drone_diff_dod_3d.py                     ← deprecated stub
  _archive/
    tab34_drone_diff_pre_dod_consolidation.py    ← 원본 백업
    tab35_drone_diff_3d_pre_dod_consolidation.py ← 원본 백업

src/dashboard/app.py
  - tab_names: "36.시계열+DoD(2D)", "37.시계열+DoD(3D)" 제거
  - tabs[15]/[16] 블록 삭제, tabs[17~20] → [15~18] shift
  - CSS nth-child: 18→16, 21→19
  - sessionStorage KEY: v7 → v8
```

## 메모리 토큰

```
[[project-drone-dod-experimental-36-37]]
  → 36/37 탭 실험 컨텍스트 (원본 34/35 보존)

[[project-drone-dod-build-1.8.1-stable]]
  → Build 1.8.1 안정 상태 (사용자 시각 검증 완료):
    - 9점 sampling + 지면 +0.1m (Build 1.7)
    - flyTo 버튼 (🔴 최대 증가 / 🔵 최대 감소) (Build 1.8)
    - hashchange listener 복구 + SSE tileset 타겟
    - TDZ fix: const masterViewer 선언 위치 leftViewer 직후로 이동
    - master swap UI 제거 (우측 master 고정)
    - 사용자 스크린샷 4매 시각 검증 완료 (종달·덕천 저수조)

[[project-drone-dual-viewer-sync]]
  → master-slave 단방향 sync + LOD 5종 OFF 패턴 (Build 1.0 ~ 유지)
```

# 📌 다음 작업 메모

> **마지막 업데이트**: 2026-05-06 (1시간 휴식 후 복귀 예정)
> **이 파일의 용도**: 다음 작업 시작 시점에 빠르게 맥락 복구

---

## 🚦 즉시 복귀용 체크포인트 (2026-05-06)

### 직전 작업: 태블릿 반응형 회귀 8단계 추적 → Build 2.8 로 해결
- 커밋: `60a3d67` "feat: 태블릿 가로 반응형 + 한글 클리핑 해소 (Build 2.2 → 2.8)"
- **Local 커밋만 완료, push 는 안 함** (사용자 인터넷 불안정 → 1시간 뒤 직접 push)
- working tree: clean

### ✅ 1시간 뒤 첫 작업 (이어서 할 것)
1. **`git push origin main`** — Streamlit Cloud 자동 배포 트리거
2. 배포 완료 후 (1~2분) Tab S10+ 와 Chrome 양쪽에서 실사용 검증
3. Samsung Internet 사용 시 **하드 리프레시** 필수 (캐시 공격적)
4. 검증 통과 시 → 다음 단계 (B 또는 C 선택)
   - B. PC 본판 (`C:\python\jeju_groundwater_dashboard`) 으로 동일 변경 역이전
   - C. 새 기능 / TODO 미완료 항목

### 📚 새로 추가된 문서·스킬·메모리 (다음 세션부터 자동 활용됨)
- `docs/development_workflow.md` — PC → OPEN → 태블릿 3단계 개발 워크플로
- `docs/design_review_tab_s10.md` — 디자인 에이전트의 Tab S10+ 분석 보고서
- `.claude/skills/responsive-development/` — 반응형 작업 시 자동 로드 스킬 (gitignored)
- 메모리 5건 (project / feedback) — Chrome 우선, 3팀 검증, Streamlit 셀렉터 등

### 🌐 새로 적용된 정책
- 휴대폰(<600px): 공식 비지원
- 태블릿 가로(1025–1499.99px): 2차 타깃, 1280px 컨테이너
- PC 데스크톱(≥1500px): 1차 타깃, 940px 디자인 보존
- **브라우저 우선순위: Chrome 1차 > Samsung Internet 2차**

---

## ✅ 지금까지 완료한 것

### 외부 배포 v1.0 (2026-04-25 완료)
- **공개 URL**: https://jeju-gw.streamlit.app
- **GitHub**: https://github.com/jhson9/jeju_gw_dashboard_open (Public)
- **호스팅**: Streamlit Community Cloud (무료)
- **시크릿**: KMA_API_KEY는 Streamlit Cloud Secrets에 등록됨

### 공개 버전 코드 차이 (PC 본판 대비)
- Quit 버튼 제거 ([src/dashboard/app.py](../src/dashboard/app.py))
- Admin 탭(⚙️ 데이터 및 리포트) 제거
- 🧾 분석 리포트 탭은 별도 파일로 분리해서 유지 ([src/dashboard/tabs/tab_report.py](../src/dashboard/tabs/tab_report.py))
- `.gitignore` 데이터 제외 규칙 주석 처리
- `config.py` API 키 읽기를 `.env` + `st.secrets` 양쪽 호환

### 가이드 문서
- [docs/외부배포_운영_가이드.md](외부배포_운영_가이드.md) — AI 없이 혼자 배포·업데이트·트러블슈팅 할 수 있는 자체 매뉴얼

---

## ✅ 다음 작업: 모바일 반응형 대응

### 배경
PC 환경에서는 잘 보이지만, **삼성 태블릿 S10+ / 갤럭시 S23 휴대폰에서는 가독성이 떨어짐**. 외부 사용자가 다양한 디바이스로 접근하므로 모바일 대응이 필요.

### 완료된 작업 (Path A — CSS 반응형)
1. **헤더 행 반응형**: 날짜 입력 3개(연/월/일) + 분석 버튼 → 폰에선 세로 stack ✅
2. **탭 라벨 줄임**: "📋 대시보드 요약" → 폰에선 "📋" 아이콘만 ✅
3. **차트 자동 크기**: 모든 Plotly 차트에 `use_container_width=True` 점검 ✅ (모두 설정됨)
4. **표 가로 스크롤**: 14수역 표는 `overflow-x: auto` 컨테이너로 감쌈 ✅
5. **폰트·여백 축소**: 모바일에서 패딩/마진 절반으로 ✅
6. **viewport meta 태그**: 모바일 브라우저가 스케일 안 하게 ✅

### 테스트 결과
- Streamlit 앱 실행 확인 (포트 8502)
- CSS @media 쿼리로 max-width: 960px 이하에서 적용
- 태블릿(S10+)은 데스크톱 수준으로 개선, 휴대폰(S23)도 차트 보이고 표 스크롤 가능

### 다음 단계
- 실제 모바일 디바이스에서 테스트 필요
- 추가 개선사항이 있으면 Path B/C 고려

---

## ❓ Claude에게 답해야 할 질문 3가지

작업 시작 전에 정해야 할 것들:

1. **모바일에서 가장 중요한 탭은?**
   - 📋 대시보드 요약 / ① 유역별 현황 / ② 강수량 / ③ 지하수위 / 🧾 리포트
   - 우선순위 정해서 그 탭부터 다듬으면 효과 큼

2. **휴대폰에서도 14개 수역 모두 비교해야 하나?**
   - 모두: 가로 스크롤 표
   - 1~3개만 골라보면 OK: 드롭다운으로 단순화

3. **작업 방식**
   - 자동 일괄: Claude가 다 알아서 수정
   - 단계별: 한 단계씩 보면서 확인

---

## 🔄 다음 작업 시작 방법

1. VSCode에서 `C:\python\jeju_gw_dashboard_open` 폴더 열기
2. Claude Code 패널 열기
3. **첫 메시지로 다음 중 하나 입력**:

### 옵션 A — 이전 대화 이어가기
이전 대화가 히스토리에 보이면 클릭해서 그대로 이어감.

### 옵션 B — 새 대화에서 메모리·이 파일로 맥락 복구
```
이 프로젝트 모바일 반응형 작업 이어서 하려고 해.
docs/TODO_다음작업.md 읽어보고 시작해줘.
```

이 한 줄로 Claude가:
- 어제 저장한 메모리 4개 자동 로드
- 이 파일 읽고 현재 상태·다음 작업·결정사항 파악
- 위 3가지 질문 다시 제시

답하시면 바로 코드 수정 시작.

---

## 📚 함께 보면 좋은 파일

- [README.md](../README.md) — 프로젝트 개요
- [docs/외부배포_운영_가이드.md](외부배포_운영_가이드.md) — 배포·운영 매뉴얼
- [docs/CHANGELOG.md](CHANGELOG.md) — 버전 변경 이력
- 메모리 파일 4개 (Claude가 자동 로드): `C:\Users\jhson\.claude\projects\c--python-jeju-gw-dashboard-open\memory\`

---

> 📝 작업 진행되면 이 파일도 업데이트하거나, 완료되면 삭제하세요.

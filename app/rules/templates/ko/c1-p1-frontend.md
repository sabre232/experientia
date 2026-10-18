---
id: c1-p1-frontend
name: 프론트엔드 엔지니어링
category: c1
priority: p1
layer: structure
trigger_default: always
tags: engineering; architecture
keywords: 프론트엔드; 컴포넌트
description: 컴포넌트 경계 + 상태 관리 + 접근성
source: built-in
from: eng-frontend
---

프론트엔드 개발 시 준수:

컴포넌트:
- 컴포넌트는 단일 책임을 유지한다. 스크린 높이를 넘거나 책임이 섞이면 분리한다.
- 제어 컴포넌트와 비제어 컴포넌트를 섞지 않는다. props 명명은 기존 컴포넌트 라이브러리와 일치시킨다.

상태:
- 로컬로 둘 수 있으면 글로벌 상태를 쓰지 않는다. '이 상태가 몇 개 컴포넌트를 넘는가'를 먼저 묻고, 답이 ≤2면 props/로컬 state.
- 파생 데이터는 useMemo/계산으로 구한다. 같은 소스의 상태를 두 개 저장해 수동 동기화하는 것은 NEVER.

접근성과 품질:
- 조작 요소는 키보드 도달을 보장한다(div로 버튼을 위장하지 않는다). 폼 컨트롤은 label이 있다.
- UI를 고친 뒤 console에 새 에러/경고가 없는지 확인하고 납품한다.

NEVER: 컴포넌트 안에 환경 의존 URL을 하드코딩하는 것은 NEVER. 한 줄 아끼려고 글로벌 CSS 오염을 들여오는 것은 NEVER.

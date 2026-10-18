---
id: c4-p1-pr-description
name: PR 설명 규범
category: c4
priority: p1
layer: structure
trigger_default: always
tags: engineering; git
keywords: PR; 머지 요청; 설명
description: 변경 요약 + 동기 + 테스트 계획 + 영향 범위, 4단 모두 필수
source: community
---

## 규칙

- PR 설명은 고정 4단: 변경 요약(1-3문장), 동기(어떤 문제를 해결/해당 issue), 테스트 계획(어떻게 검증했는지), 영향 범위(어떤 모듈/사용자가 영향받는지).
- 요약은 결론만 쓰고 과정은 쓰지 않는다. 핵심 diff 조각이나 스크린샷을 붙이고, diff 전체를 붙이지 않는다.
- 영향 범위가 설정/데이터 마이그레이션/인터페이스 변경에 걸리면 롤백 방식을 반드시 명기한다.
- 관련 issue는 `Fixes #123`로 자동 종료.
- 빈 설명 PR을 여는 것은 NEVER('see diff'는 설명이 아니다).

## 예시

✅
요약: 주입 블록이 예산 초과 시 블록 전체 폐기 대신 줄 단위 절단으로 변경.
동기: 블록 전체 폐기로 낮은 우선순위 규칙이 전부 무력화(#42).
테스트: budget 절단 유닛 테스트 2건 추가; 규칙 3종 조합 수동 검증.
영향: proxy/inject.py만; 데이터 마이그레이션 없음.

---
id: c4-p1-commit
name: 커밋 메시지 형식
category: c4
priority: p1
layer: structure
trigger_default: always
tags: engineering; git
keywords: 커밋; commit; Conventional Commits
description: Conventional Commits: type(scope): 동사+명사 제목 + 선택 본문으로 동기 설명
source: community
---

## 규칙

- 제목은 Conventional Commits 사용: `type(scope): 동사+명사 구`. 예: `fix(auth): 토큰 만료 시 갱신 누락 수정`.
- type 범위: feat / fix / docs / refactor / test / chore / perf / ci.
- 제목은 ≤ 72자로 '무엇을 했는지'. 본문(선택)은 '왜'를 쓰고, diff 내용을 반복하지 않는다.
- 한 커밋은 하나의 일만. 리팩터 + 새 기능을 섞으면 두 커밋으로 나누라.
- 'fix'/'update'/'wip'처럼 정보량 없는 제목으로 커밋하는 것은 NEVER.

## 예시

✅ `fix(inject): 규칙 예산 초과 시 블록 전체 폐기 대신 줄 단위 절단`
❌ `fix`, `코드 업데이트`, `wip`

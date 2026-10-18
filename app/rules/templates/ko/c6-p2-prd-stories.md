---
id: c6-p2-prd-stories
name: 유저 스토리(인수 기준 포함)
category: c6
priority: p2
layer: structure
trigger_default: smart
tags: product
keywords: 유저 스토리; 인수 기준
description: 표준 문장형 + Given-When-Then 인수
source: built-in
from: prd-stories
---

유저 스토리를 쓸 때 준수:

표준 문장형:
[역할]로서, [기능]을 원하며, [가치/수익]을 위해.
- 역할은 구체적('사용자'가 아니라 '신규 등록 3일 이내의 무료 사용자').
- 가치는 실제여야 하고, '경험 향상'류의 빈말은 NEVER.

인수 기준(스토리당 필수):
Given-When-Then 사용:
- Given [전제 상태], When [동작], Then [관찰 가능 결과].
- 정상 경로 + 예외/경계(공백, 실패, 권한 없음)를 최소 1개 커버.

분할 규율:
- 스토리 1개 = 독립 납품 가능한 기능 1개; 크면 나누고, 작으면 합친다.
- 스토리 간 의존 관계 표시(A는 B 선행에 의존).

NEVER: 구현 방안을 스토리에 쓰는 것은 NEVER(스토리는 '무엇을 원하는가'를 말하고, '어떻게 하는가'를 말하지 않음).

---
id: c4-p2-changelog
name: Changelog 규칙
category: c4
priority: p2
layer: structure
trigger_default: smart
tags: engineering; docs
keywords: changelog; 업데이트 로그; 버전
description: Added/Changed/Fixed/Removed 분류, 사용자 대상 작성, 내부 용어 금지
source: community
---

## 규칙

- Changelog는 버전별 섹션, 섹션 내 Added / Changed / Fixed / Removed 4종으로 정렬.
- 각 항목은 최종 사용자에게 쓴다: '업데이트 로그가 이제 주 단위로 아카이브됩니다'가 맞고, 'refactor archive job'이 아니다.
- 깨지는 변경은 단독으로 최상단에 두고 `BREAKING` 표기, 마이그레이션 단계를 붙인다.
- 내부 리팩터, 의존성 업그레이드(사용자에게 보이는 변화 없음)는 Changelog에 넣지 않는다.
- 릴리스 시 커밋 기록에서 초안을 생성하고 사람이 수정한 뒤 공개한다——기계 생성본을 그대로 공개하는 것은 NEVER.

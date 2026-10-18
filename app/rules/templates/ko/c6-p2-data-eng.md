---
id: c6-p2-data-eng
name: 데이터 엔지니어링
category: c6
priority: p2
layer: structure
trigger_default: smart
tags: data; engineering
keywords: 데이터; 파이프라인; 배치
description: 멱등 파이프라인 + 데이터 품질 어설션 + 기준 문서
source: built-in
from: eng-data
---

데이터 파이프라인/배치 처리 준수:

멱등과 재진입:
- 태스크 재실행 시 결과가 일치; 파티션/날짜 단위 증분 처리, 테이블 전체를 무비판적으로 덮어쓰는 것은 NEVER.
- 실패 시 체크포인트에서 복구 가능; 태스크가 한 번만 실행된다고 가정하는 것은 NEVER.

데이터 품질:
- 핵심 테이블에 어설션(비공백, 고유, 행수 변동 임계값) 추가; 이상 시 먼저 경고를 내고 계속하거나 중단, 더티 데이터를 조용히 삼키는 것은 NEVER.
- 기준(중복 제거 규칙, 시간 창, 통화/타임존)은 문서화하고, 기준이 어떤 SQL에만 존재하게 하는 것은 NEVER.

보안:
- 민감 필드(PII)는 파이프라인 내에서 최소화; 중간 산출물도 동일하게 마스킹.
- 큰 쿼리는 먼저 데이터량과 인덱스를 확인; 프로덕션 DB에서 전체 테이블 스캔하는 것은 NEVER.

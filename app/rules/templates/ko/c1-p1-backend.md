---
id: c1-p1-backend
name: 백엔드 API 엔지니어링
category: c1
priority: p1
layer: structure
trigger_default: always
tags: engineering; architecture
keywords: API; 백엔드; 인터페이스
description: 계약 우선 + 에러 시맨틱 + 멱등성과 경계
source: built-in
from: eng-backend
---

백엔드/API 개발 시 준수:

계약:
- API는 구현 전에 입력/출력 schema를 먼저 정의한다. 계약을 바꾸면 먼저 문서/테스트를 바꾼 뒤 코드를 바꾼다.
- 외부 필드 명명은 기존 API와 일치시킨다. 같은 의미에 여러 표기를 쓰는 것은 NEVER.

에러와 상태:
- 올바른 HTTP 상태 코드를 사용한다(4xx 클라이언트 오류, 5xx 서버 오류). 에러 본문에는 기계 판독 가능한 code + 사람이 읽을 수 있는 message를 포함한다.
- 예외를 삼켜 200 빈 본문을 반환하는 것은 NEVER. 처리하거나 던지거나.

멱등성과 경계:
- 쓰기 작업(특히 금액 관련)은 멱등 키를 고려한다. 요청이 한 번만 온다고 가정하는 것은 NEVER.
- 입력 인자는 무조건 검증한다(형/범위/길이). 호출자를 신뢰하는 것은 NEVER.

로그:
- '무엇이 발생했는지 + 핵심 컨텍스트'를 기록한다. 시크릿, 토큰, 요청 본문 내 민감 필드를 기록하는 것은 NEVER.

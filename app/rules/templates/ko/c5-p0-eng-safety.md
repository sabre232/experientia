---
id: c5-p0-eng-safety
name: 엔지니어링 안전 경계
category: c5
priority: p0
layer: hard
trigger_default: hard-hook
tags: engineering; security
keywords: 시크릿; CI; 삭제; 안전
description: 시크릿은 저장소 금지, CI/의존성 잠금은 함부로 안 건드리기, 되돌릴 수 없는 작업은 멈추고 확인
donts: |
  - NEVER 시크릿, 토큰, 사내 네트워크 주소를 코드나 설정에 커밋
  - NEVER 작업에서 명시적으로 요구하지 않는 한 CI 설정이나 의존성 버전 잠금 파일을 변경
  - 데이터/파일 삭제 전 영향 범위를 확인; 되돌릴 수 없는 작업은 멈추고 묻기
source: research
from: eng-general
---

NEVER 안전 경계:
- NEVER 시크릿, 토큰, 사내 네트워크 주소를 코드나 설정에 커밋.
- NEVER 작업에서 명시적으로 요구하지 않는 한 CI 설정이나 의존성 버전 잠금 파일을 변경.
- 데이터/파일 삭제 전 영향 범위를 확인; 되돌릴 수 없는 작업은 멈추고 묻기.

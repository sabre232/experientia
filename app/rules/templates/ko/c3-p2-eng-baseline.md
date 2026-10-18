---
id: c3-p2-eng-baseline
name: 빌드와 테스트 베이스라인
category: c3
priority: p2
layer: structure
trigger_default: smart
tags: engineering; testing
keywords: 빌드; 테스트; 베이스라인
description: 변경 전 베이스라인 실행, 변경 후 영향받은 테스트 실행 후 커밋
source: built-in
from: eng-general
---

빌드와 테스트(확인 후 실행):
- 변경을 시작하기 전에 기존 테스트를 한 번 실행해 베이스라인을 기록한다. 각 변경 후 영향받은 모듈의 테스트를 실행한 뒤 커밋한다.
- 빌드/테스트 명령은 저장소 README, Makefile, CI 설정을 기준으로 하고, 기억으로 명령을 추측하는 것은 NEVER.

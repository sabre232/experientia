---
id: c4-p3-readme
name: README 유지
category: c4
priority: p3
layer: structure
trigger_default: smart
tags: engineering; docs
keywords: README; 문서; 동기화
description: README와 코드 동기: 설치/실행/테스트 3개 명령은 언제나 복사-실행 가능
source: built-in
---

## 규칙

- README는 필수 3블록: 설치, 실행, 테스트. 3블록 안의 명령은 저장소 실제와 일치해야 한다(CI 설정이 사실 출처).
- 명령/인자/디렉터리 구조를 고쳤다면, 같은 커밋에서 README를 업데이트한다——명령과 문서를 따로 커밋하면 미완료로 간주.
- 신입 시야로 점검: README만 보고 10분 안에 로컬 환경을 띄울 수 있는가; 아니면 빠진 단계를 채운다.
- 낡은 섹션은 그냥 삭제하고 '업데이트 예정' 플레이스홀더를 남기지 않는다.

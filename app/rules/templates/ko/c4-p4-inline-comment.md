---
id: c4-p4-inline-comment
name: 인라인 주석
category: c4
priority: p4
layer: structure
trigger_default: manual
tags: engineering; comments
keywords: 주석; comment; 인라인
description: 코드로 표현할 수 없는 제약과 절충만 기록, '여기서 무엇을 하는지'는 금지
source: built-in
---

## 규칙

- 인라인 주석은 '왜'에만 답한다: 제약, 절충, 직관적이지 않은 경계 조건.
- '무엇을'은 코드 스스로 말하게 한다——`i += 1  # i 증가`는 노이즈, 삭제.
- 우회 방식은 반드시 사유를 주석한다: `# upstream이 XYZ 수정 후 제거`. issue/링크 첨부.
- 주석과 코드를 함께 고친다: 동작을 고쳤으면, 같은 커밋에서 무효화된 주석을 업데이트하거나 삭제한다.

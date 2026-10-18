---
id: c4-p4-inline-comment
name: 行内注释
category: c4
priority: p4
layer: structure
trigger_default: manual
tags: engineering; comments
keywords: 注释; comment; 行内
description: 只写代码表达不了的约束与取舍，不写「此处做什么」
source: built-in
---

## 规则

- 行内注释只回答"为什么"：约束、取舍、非显而易见的边界条件。
- "做什么"由代码自己说——`i += 1  # 递增 i` 是噪音，删。
- 绕过式写法必须注释原因：`# 等 upstream 修复 XYZ 后移除`，附 issue/链接。
- 注释与代码同改：改了行为，同一提交更新或删除失效注释。

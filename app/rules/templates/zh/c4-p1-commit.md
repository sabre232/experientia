---
id: c4-p1-commit
name: 提交信息格式
category: c4
priority: p1
layer: structure
trigger_default: always
tags: engineering; git
keywords: 提交; commit; Conventional Commits
description: Conventional Commits：type(scope): 动宾标题 + 可选正文说明动机
source: community
---

## 规则

- 标题用 Conventional Commits：`type(scope): 动宾短语`，如 `fix(auth): 修复 token 过期未刷新`。
- type 限定：feat / fix / docs / refactor / test / chore / perf / ci。
- 标题 ≤ 72 字符，说"做了什么"；正文（可选）说"为什么"，不重复 diff 内容。
- 一个提交只做一件事；混合"重构 + 新功能"拆成两个提交。
- NEVER 提交 "fix" / "update" / "wip" 这类无信息量标题。

## 示例

✅ `fix(inject): 规则预算超限时按行截断而非丢弃整块`
❌ `fix`、`更新代码`、`wip`

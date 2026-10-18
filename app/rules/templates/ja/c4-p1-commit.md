---
id: c4-p1-commit
name: コミットメッセージ形式
category: c4
priority: p1
layer: structure
trigger_default: always
tags: engineering; git
keywords: コミット; commit; Conventional Commits
description: Conventional Commits：type(scope): 動詞+名詞の見出し + 任意の本文で動機を説明
source: community
---

## ルール

- 見出しは Conventional Commits を使う：`type(scope): 動詞+名詞の短句`。例：`fix(auth): token 期限切れ時の再取得漏れを修正`。
- type の範囲：feat / fix / docs / refactor / test / chore / perf / ci。
- 見出しは 72 文字以内で「何をしたか」を書く。本文（任意）は「なぜか」を書く。diff の内容を繰り返さない。
- 1 コミットは 1 件事。リファクタ + 新機能を混ぜたら 2 つのコミットに分割する。
- 「fix」/「update」/「wip」のような情報量ゼロの見出しのコミットは NEVER。

## 例

✅ `fix(inject): ルール予算超過時にブロックごと破棄せず行単位で切り詰める`
❌ `fix`、`コード更新`、`wip`

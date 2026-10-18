---
id: c3-p2-eng-baseline
name: ビルドとテストのベースライン
category: c3
priority: p2
layer: structure
trigger_default: smart
tags: engineering; testing
keywords: ビルド; テスト; ベースライン
description: 変更前にベースラインを実行、変更後に影響したテストを実行してからコミット
source: built-in
from: eng-general
---

ビルドとテスト（先に確認してから実行）：
- 変更を始める前に既存テストを一度実行してベースラインを記録する。各変更の後、影響を受けたモジュールのテストを実行してからコミットする。
- ビルド/テストコマンドはリポジトリの README、Makefile、CI 設定を正とし、記憶でコマンドを当てるのは NEVER。

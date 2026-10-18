---
id: c5-p0-eng-safety
name: エンジニアリングの安全境界
category: c5
priority: p0
layer: hard
trigger_default: hard-hook
tags: engineering; security
keywords: シークレット; CI; 削除; 安全
description: シークレットはリポジトリに入れない、CI/依存ロックは勝手に触らない、取り消せない操作は止めて問う
donts: |
  - NEVER シークレット、token、社内ネットワークアドレスをコードや設定にコミット
  - NEVER CI 設定や依存バージョンロックファイルを、タスクが明示的に要求しない限り変更
  - データ/ファイルの削除前に影響範囲を確認。取り消せない操作は止めて問い、勝手に続行しない
source: research
from: eng-general
---

NEVER 安全境界：
- NEVER シークレット、token、社内ネットワークアドレスをコードや設定にコミット。
- NEVER CI 設定や依存バージョンロックファイルを、タスクが明示的に要求しない限り変更。
- データ/ファイルの削除前に影響範囲を確認。取り消せない操作は止めて問い、勝手に続行しない。

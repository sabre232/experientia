---
id: c4-p3-readme
name: README 維持
category: c4
priority: p3
layer: structure
trigger_default: smart
tags: engineering; docs
keywords: README; ドキュメント; 同期
description: README とコードは同期：インストール/実行/テストの 3 コマンドは常にコピペ実行可能
source: built-in
---

## ルール

- README は必ず 3 ブロックを含む：インストール、実行、テスト。3 ブロック内のコマンドはリポジトリの実態と一致しなければならない（CI 設定が事実ソース）。
- コマンド/引数/ディレクトリ構造を変えた時は、同じコミットで README を更新する——コマンドとドキュメントを別コミットにすると未完成と見なす。
- 新人の目線で確認：README だけ読んで 10 分でローカル環境を起動できるか。できなければ欠けている手順を補う。
- 古い章はそのまま削除する。「更新予定」プレースホルダは残さない。

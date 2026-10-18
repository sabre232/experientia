---
id: c4-p2-changelog
name: Changelog ルール
category: c4
priority: p2
layer: structure
trigger_default: smart
tags: engineering; docs
keywords: changelog; 更新履歴; バージョン
description: Added/Changed/Fixed/Removed で分類。ユーザー向けに書く。内部用語は使わない
source: community
---

## ルール

- Changelog はバージョンごとに節分け、節内は Added / Changed / Fixed / Removed の 4 分類で並べる。
- 各項目は最終ユーザー向けに書く。「更新履歴が今週次アーカイブになった」が正解、「refactor archive job」ではない。
- 破壊的変更は単独で最上位に置き `BREAKING` を付し、移行手順を添える。
- 内部リファクタ、依存アップデート（ユーザーに見える変化なし）は Changelog に入れない。
- リリース時にコミット履歴から初稿を生成し、人が修正してから公開する——機械生成のものをそのまま公開するのは NEVER。

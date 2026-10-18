---
id: c4-p4-inline-comment
name: 行内コメント
category: c4
priority: p4
layer: structure
trigger_default: manual
tags: engineering; comments
keywords: コメント; comment; 行内
description: コードでは表現できない制約と妥協だけを書く。「ここで何をするか」は書かない
source: built-in
---

## ルール

- 行内コメントは「なぜ」にだけ答える：制約、妥協、自明でない境界条件。
- 「何を」はコード自身に語らせる——`i += 1  # i を増やす` はノイズ。削除。
- バイパス的な書き方には必ず理由をコメントする：`# upstream が XYZ を修正したら削除`。issue/リンクを添える。
- コメントはコードと同時に変更：動作を変えたなら、同じコミットで無効化したコメントを更新または削除する。

---
id: c2-p2-eng-style
name: コードスタイル（リポジトリに従う）
category: c2
priority: p2
layer: structure
trigger_default: smart
tags: engineering
keywords: コードスタイル; 命名; コメント
description: リポジトリの既存スタイルに従う。コメントはコードでは表現できない制約だけを書く
source: built-in
from: eng-general
---

コードスタイル：
- リポジトリの既存スタイル（インデント、命名、import の並び）に従い、新規コードは隣接コードと一貫させる。無関係なファイルに手を出して書式変更するのは NEVER。
- コメントはコード自体では表現できない制約だけを書く。「ここで X を呼び出し」系の余計な言葉は書かない。

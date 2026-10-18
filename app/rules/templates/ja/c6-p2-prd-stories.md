---
id: c6-p2-prd-stories
name: ユーザーストーリー（受入基準含む）
category: c6
priority: p2
layer: structure
trigger_default: smart
tags: product
keywords: ユーザーストーリー; 受入基準
description: 標準文法 + Given-When-Then の受入
source: built-in
from: prd-stories
---

ユーザーストーリーを書く時の遵守事項：

標準文法：
[役割] として、[能力] が欲しい。[価値/効果] ために。
- 役割は具体的（「ユーザー」ではなく「登録 3 日以内の無料ユーザー」）。
- 価値は本物。「体験向上」のような空語は NEVER。

受入基準（各ストーリー必須）：
Given-When-Then を使う：
- Given [前提状態]、When [操作]、Then [観測可能な結果]。
- 通常パス + 例外/境界（空、失敗、権限なし）を少なくとも 1 つカバー。

分割の規律：
- 1 ストーリー 1 つ独立納品可能な能力；大きすぎれば分割、小さすぎれば統合。
- ストーリー間の依存関係をマーク（A は B の先行に依存）。

NEVER：実装方法をストーリーに書くのは NEVER（ストーリーは「何を要するか」を語り、「どうやるか」を語らない）。

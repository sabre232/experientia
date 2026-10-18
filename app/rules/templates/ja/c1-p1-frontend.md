---
id: c1-p1-frontend
name: フロントエンドエンジニアリング
category: c1
priority: p1
layer: structure
trigger_default: always
tags: engineering; architecture
keywords: フロントエンド; コンポーネント
description: コンポーネント境界 + 状態管理 + アクセシビリティ
source: built-in
from: eng-frontend
---

フロントエンド開発で遵守すること：

コンポーネント：
- コンポーネントは単一責任を維持する。1 スクリーン高を超えるか責任が混在したら分割する。
- 制御コンポーネントと非制御コンポーネントの混用はしない。props の命名は既存のコンポーネントライブラリと一貫させる。

状態：
- 局所化できるならグローバル状態にしない。「この状態はいくつのコンポーネントをまたぐか」をまず問い、答えが ≤2 なら props/ローカル state。
- 派生データは useMemo/計算で求める。同一ソースの状態を二つ保存して手動同期するのは NEVER。

アクセシビリティと品質：
- 操作要素はキーボードで到達可能にする（div でボタンを偽装しない）。フォーム制御は label を持つ。
- UI を変更した後は、console に新しいエラー/警告がないことを確認して納品する。

NEVER：コンポーネント内で環境依存 URL をハードコードするのは NEVER。1 行省くためにグローバル CSS 汚染を持ち込むのは NEVER。

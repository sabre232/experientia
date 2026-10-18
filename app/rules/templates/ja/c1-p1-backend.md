---
id: c1-p1-backend
name: バックエンド API エンジニアリング
category: c1
priority: p1
layer: structure
trigger_default: always
tags: engineering; architecture
keywords: API; バックエンド; インターフェース
description: 契約優先 + エラーセマンティクス + べき等性と境界
source: built-in
from: eng-backend
---

バックエンド/API 開発で遵守すること：

契約：
- API は実装を書く前に入出力の schema を決める。契約を変える場合はまずドキュメント/テストを変え、それからコードを変える。
- 対外フィールドの命名は既存 API と一貫させる。同じ意味に複数綴りを使うのは NEVER。

エラーと状態：
- 正しい HTTP ステータスコードを使う（4xx はクライアントエラー、5xx はサーバーエラー）。エラー体には機械可読の code と人間可読の message を入れる。
- 例外を握りつぶして 200 の空ボディを返すのは NEVER。処理するか、throw するか。

べき等性と境界：
- 書き込み操作（特に金額が関わるもの）はべき等キーを考慮する。リクエストが一度だけ来る前提で設計するのは NEVER。
- 入力引数はすべて検証する（型/範囲/長さ）。呼び出し側を信頼するのは NEVER。

ログ：
- 「何が起きたか + 重要な文脈」を記録する。シークレット、token、リクエストボディ内の機密フィールドを記録するのは NEVER。

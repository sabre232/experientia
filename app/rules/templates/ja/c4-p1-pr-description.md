---
id: c4-p1-pr-description
name: PR 説明の規範
category: c4
priority: p1
layer: structure
trigger_default: always
tags: engineering; git
keywords: PR; マージリクエスト; 説明
description: 変更サマリ + 動機 + テスト計画 + 影響範囲、4 部すべて必須
source: community
---

## ルール

- PR 説明は固定 4 部：変更サマリ（1-3 文）、動機（どの問題を解決するか/対応 issue）、テスト計画（どう検証したか）、影響範囲（どのモジュール/ユーザーが影響を受けるか）。
- サマリは結論を書く。過程は書かない。重要な diff フラグメントやスクショを貼る。diff 全体を貼らない。
- 影響範囲が設定/データ移行/API 変更に関わる場合、ロールバック方法を必ず明記する。
- 関連 issue は `Fixes #123` で自動クローズ。
- 空説明の PR を作ることは NEVER（「see diff」は説明ではない）。

## 例

✅
サマリ：注入ブロックが予算超過時に、ブロックごと破棄せず行単位で切り詰めるように変更。
動機：ブロックごと破棄すると低優先度ルールが全部無効化（#42）。
テスト：budget 切り詰め単テスト 2 件追加。ルール 3 種組み合わせを手動検証。
影響：proxy/inject.py のみ。データ移行なし。

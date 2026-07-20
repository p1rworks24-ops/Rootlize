# Capixe v0.1.0-preview

## Prototype Preview

Capixe の最初の公開候補ビルドです。正式版ではありません。機能・UI・保存仕様は今後変わる可能性があります。

## 主な機能（このプレビューで使えるもの）

- Region / Full Screen Capture
- Capture Panel
- Root Folder / 保存フォルダ管理
- Images（画像閲覧）
- Tags
- Organize（整理ツール）
- Settings（ショートカット・通知・ウィンドウサイズなど）
- ローカル設定（`%APPDATA%\Capixe`）

※ ナビの AI はプレースホルダのみ（AI機能は未実装）

## ダウンロード

添付の ZIP:

`Capixe-v0.1.0-preview-win64.zip`

## 起動方法

1. ZIP を任意の場所へ完全に展開する
2. `Capixe\Capixe.exe` を起動する
3. `Capixe.exe` だけを取り出さない（`_internal` が必要）

インストーラーはありません（ポータブル onedir）。

## 保存場所

- 設定 / タグ: `%APPDATA%\Capixe`
- 既定の画像 Root: `%USERPROFILE%\Pictures\Capixe`
- Settings で Root Folder を変更済みなら、そのパスを使用

## 既知の制限

- Prototype Preview
- コード署名なし / 自動アップデートなし / インストーラーなし
- AI 機能未実装
- Windows 以外は未対応
- 予期しない不具合の可能性

## 未署名についての注意

Windows SmartScreen や Defender が警告することがあります。配布元（この GitHub Release）とファイルを確認したうえで、実行するかどうかを判断してください。警告を無条件に無視する必要はありません。

## フィードバック

リポジトリ公開後は GitHub Issues（Bug / Feature フォーム）を利用してください。

パスワード・APIキー・個人メール・私的な絶対パスは貼らないでください。

リポジトリ URL: （公開時に `app/repo_links.py` の owner/repo を設定）

## ライセンス

Capixe は現時点で Private かつ Proprietary です。
Copyright © 2026 Capixe. All rights reserved.

Public なソース公開前に、正式な公開ライセンスを改めて決定します。
詳細は同梱またはリポジトリの `LICENSE` を参照してください。

## 注意

- ユーザー設定や画像は ZIP に含まれません
- 既存の `%APPDATA%\Capixe` 設定がある場合は共有されます（開発版と同じ）

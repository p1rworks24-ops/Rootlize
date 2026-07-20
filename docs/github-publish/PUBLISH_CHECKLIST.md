# Capixe GitHub 公開前チェックリスト

Prototype Preview `v0.1.0-preview` 向け。

## リポジトリ安全

- [ ] Git管理対象に秘密情報なし
- [ ] APIキー / トークン / パスワードなし
- [ ] 個人メールなし
- [ ] 個人の絶対パスなし（開発者ホームパスのハードコードなし）
- [ ] `config.json` / `tags.json` が追跡されていない
- [ ] `screenshots/` / `Capture/` / ユーザー画像が追跡されていない
- [ ] `.env` / credentials なし
- [ ] `build/` / `dist/` / `release/` が Git に入っていない
- [ ] `.gitignore` が公開向けに整っている

## ドキュメント

- [ ] `README.md` 完成
- [ ] ZIP 用 `packaging/README.txt` 完成
- [ ] Release 文面確認（`docs/github-publish/RELEASE_NOTES_v0.1.0-preview.md`）
- [x] ライセンス決定（Proprietary / All Rights Reserved — ルート `LICENSE`）
- [ ] `app/repo_links.py` の `GITHUB_OWNER` / `GITHUB_REPO` 設定
- [ ] リポジトリ公開範囲（Private / Public）確認

## バージョン・ブランド

- [ ] バージョン統一（`app/branding.py` = `0.1.0-preview` / 表示 `v0.1.0-preview`）
- [ ] README / ZIP名 / Release名が一致
- [ ] About にバージョン表示
- [ ] ウィンドウタイトルが Capixe
- [ ] アプリアイコン反映

## ビルド・配布

- [ ] `python -m PyInstaller Capixe.spec --clean --noconfirm` 成功
- [ ] `release/Capixe-v0.1.0-preview-win64.zip` 生成
- [ ] ZIP 内に config / tags / screenshots / Capture / ユーザーPNG / ログなし
- [ ] ZIP 展開後に `Capixe.exe` + `_internal` + `README.txt` がある
- [ ] ZIP から起動成功
- [ ] 起動時に展開フォルダへ config 等が生成されない
- [ ] 起動時の自動 Capture 再発なし

## 手動動作確認

- [ ] Capture 成功
- [ ] PNG 保存成功
- [ ] Images 反映成功
- [ ] Settings 変更成功
- [ ] 通常終了成功
- [ ] 再起動成功
- [ ] Root Folder 維持
- [ ] dist / ZIP 内へユーザーデータ混入なし

## GitHub 公開操作（別タスク・明示指示後）

- [ ] Git commit
- [ ] remote 設定
- [ ] push
- [ ] タグ作成（例: `v0.1.0-preview`）
- [ ] GitHub Release 作成と ZIP 添付
- [ ] Public 化の最終承認

## 今回の公開準備では行わない

- push / tag push / Release 公開 / Public 変更 / force push / 履歴書き換え

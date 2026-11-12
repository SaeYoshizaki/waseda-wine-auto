# wine-auto-renew

早稲田大学図書館 WINE で借りている本を、返却期限の前日・当日に自動で延長する自分用ツール。
GitHub Actions で毎朝 7:17 (JST) に動く。

## しくみ

- WINE (Ex Libris Primo VE) に Waseda メール + パスワードでログインし、My Library の貸出一覧を取得する
- 期限が明日以内の本だけ延長する
  - 延長後の期限は「延長した日 + 貸出期間」で計算されるので、早めに延長しても得をしない
  - 延長は返却期限の3日後までできるので、1日実行が抜けても間に合う
- 次の場合はジョブを失敗させ、GitHub から通知メールが届くようにする
  - 予約が入っている・最大延長日に達したなど、延長できない本の期限が3日以内になった
  - 期限を過ぎてから延長した (実行が抜けた日があった)
  - ログインに失敗した

結果は Actions の各実行ページ (Summary) に一覧で出る。

## セットアップ

1. このリポジトリを **Private** で GitHub に置く
2. Settings → Secrets and variables → Actions に次の2つを登録する
   - `WASEDA_EMAIL`: Waseda メールアドレス
   - `WASEDA_PASSWORD`: MyWaseda のパスワード
3. Actions タブ → 「WINE 自動延長」→ Run workflow (dry_run にチェック) で、延長せずに動作確認する

パスワードを変えたら `WASEDA_PASSWORD` も更新すること。

## 手元で試す

```sh
pip install -r requirements.txt
python -m playwright install chromium

# ブラウザが開くので自分でログインする。延長はしない
python renew.py --headed --dry-run
```

`--days-before N` で「期限の何日前から延長するか」を変えられる (既定 1)。

# waseda-wine-auto

早稲田大学図書館の WINE で借りている本を、GitHub Actions で毎朝自動延長するツールです。

## できること

- 毎朝 7:17 (JST) に WINE にログインし、返却期限まで5日以内の本を延長する
- 次のときは GitHub から通知メールが届く (ジョブを失敗させて知らせる)
  - 予約が入っている・最大延長日に達したなど、延長できない本の期限が近づいた
  - 延長やログインに失敗した
- 結果は Actions の各実行ページ (Summary) に一覧で出る

## 使い方

1. このページ右上の Use this template → Create a new repository で自分用のリポジトリを作る
   - **Visibility は必ず Private にしてください。** Public だと実行ログに借りている本のタイトルが公開されます
2. 作ったリポジトリの Settings → Secrets and variables → Actions → New repository secret で次の2つを登録する
   - `WASEDA_EMAIL`: Waseda メールアドレス
   - `WASEDA_PASSWORD`: MyWaseda のパスワード
3. Actions タブ → WINE 自動延長 → Run workflow を、dry_run にチェックを入れたまま実行する
   - 延長はせずに確認だけします。Summary に借りている本の一覧が出れば準備完了です
4. あとは自動で動きます

- MyWaseda のパスワードを変えたら `WASEDA_PASSWORD` も更新してください
- 何日前から延長するかは、同じ画面の Variables タブで `DAYS_BEFORE` (例: `3`) を作ると変えられます
- 卒業・修了で WINE にログインできなくなったら、Actions タブのワークフロー画面から Disable workflow で止めてください

## しくみ
- WINE は Ex Libris 社の Primo VE で動いています。Playwright (ヘッドレス Chromium) で Microsoft のサインイン画面を通ってログインし、My Library の画面が内部で使っている API で貸出一覧の取得と延長を行います
  - `GET /primaws/rest/priv/myaccount/loans` … 貸出一覧 (返却期限・最大延長日・延長可否)
  - `POST /primaws/rest/priv/myaccount/renew_loans` … 1冊ずつ延長
- 図書館の延長ルール ([貸出](https://www.waseda.jp/library/services/borrowing/) / [WINE ヘルプ](https://waseda-jp.libguides.com/c.php?g=920138&p=6636298))
  - 新しい返却期限は「延長した日 + 貸出期間」
  - 延長は1日1回まで、回数の上限なし、返却期限の3日後まで可能
  - 最大延長日を超えては延長できない (それ以上は貸出カウンターで再貸出)
- 期限の5日前から延長するのは、失敗しても期限まで毎朝再挑戦できるようにするためです。最大延長日は決まっているので、早めに延長しても借りられる期間の合計は変わりません


## 手元で試す

```sh
pip install -r requirements.txt
python -m playwright install chromium

# ブラウザが開くので自分でログインする。延長はしない
python renew.py --headed --dry-run
```

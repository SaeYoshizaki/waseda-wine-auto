# waseda-wine-auto

早稲田大学図書館の WINE で借りている本を、GitHub Actions で毎朝自動延長する自分用ツールです。

> [!NOTE]
> 早稲田大学・早稲田大学図書館とは関係のない非公式ツールです。

## できること

- 毎朝 7:17 (JST) に WINE にログインし、**返却期限まで5日以内の本を延長**する
- 次のときは GitHub から通知メールが届く (ジョブを失敗させて知らせる)
  - 予約が入っている・最大延長日に達したなど、延長できない本の期限が近づいた
  - 延長やログインに失敗した
- 結果は Actions の各実行ページ (Summary) に一覧で出る

```
WINE 自動延長 2026-11-22
✅ 延長: 〇〇〇〇 … 2026/11/27 → 2026/12/06
・ そのまま: △△△△ … 期限 2026/12/10 (期限まで18日)
⚠️ 要対応: □□□□ … 期限 2026/11/25: 延長できません(予約が入っている等)。期限までに返却してください
```

## しくみ

- WINE は Ex Libris 社の Primo VE で動いています。Playwright (ヘッドレス Chromium) で Microsoft のサインイン画面を通ってログインし、My Library の画面が内部で使っている API で貸出一覧の取得と延長を行います
  - `GET /primaws/rest/priv/myaccount/loans` … 貸出一覧 (返却期限・最大延長日・延長可否)
  - `POST /primaws/rest/priv/myaccount/renew_loans` … 1冊ずつ延長
- 図書館の延長ルール ([貸出](https://www.waseda.jp/library/services/borrowing/) / [WINE ヘルプ](https://waseda-jp.libguides.com/c.php?g=920138&p=6636298))
  - 新しい返却期限は「延長した日 + 貸出期間」
  - 延長は1日1回まで、回数の上限なし、返却期限の3日後まで可能
  - 最大延長日を超えては延長できない (それ以上は貸出カウンターで再貸出)
- 期限の5日前から延長するのは、失敗しても期限まで毎朝再挑戦できるようにするためです。最大延長日は決まっているので、早めに延長しても借りられる期間の合計は変わりません

## 設定

- Actions の Secrets に `WASEDA_EMAIL` (Waseda メールアドレス) と `WASEDA_PASSWORD` (MyWaseda のパスワード) を登録する
- 何日前から延長するかは、Actions の Variables に `DAYS_BEFORE` を作ると変えられる (既定 5)
- 動作確認は Actions タブの Run workflow で dry_run にチェックを入れて実行する (延長はしない)
- MyWaseda のパスワードを変えたら `WASEDA_PASSWORD` も更新する。二段階認証を求められるアカウントでは動かない

## 手元で試す

```sh
pip install -r requirements.txt
python -m playwright install chromium

# ブラウザが開くので自分でログインする。延長はしない
python renew.py --headed --dry-run
```

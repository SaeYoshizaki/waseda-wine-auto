"""早稲田大学 WINE (Ex Libris Primo VE) の貸出を、返却期限が近いものだけ自動延長する。

延長後の返却期限は「延長した日 + 貸出期間」で再計算されるため、期限ぎりぎりで延長する。
延長できない本(予約あり・最大延長日到達など)があれば終了コード 1 で知らせる。

終了コード: 0 = 問題なし / 1 = 要対応の本あり / 2 = ログイン失敗などのエラー
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import time
from urllib.parse import quote
from zoneinfo import ZoneInfo

BASE = "https://waseda.primo.exlibrisgroup.com"
VID = "81SOKEI_WUNI:WINE"
ACCOUNT_URL = f"{BASE}/discovery/account?vid={VID}&section=loans&lang=ja"
LOGIN_URL = (
    f"{BASE}/primaws/suprimaExtLogin?institution=81SOKEI_WUNI&lang=ja"
    f"&target-url={quote(ACCOUNT_URL, safe='')}"
    "&authenticationProfile=SAML&idpCode=SAML&auth=SAML"
    f"&view={quote(VID, safe='')}&isSilent=false"
)
LOANS_API = f"{BASE}/primaws/rest/priv/myaccount/loans?bulk=100&lang=ja&offset=1&type=active"
RENEW_API = f"{BASE}/primaws/rest/priv/myaccount/renew_loans?lang=ja"
MS_HOST = "https://login.microsoftonline.com"
JST = ZoneInfo("Asia/Tokyo")
GRACE_DAYS = 3  # 返却期限後3日目までは延長できる
WARN_DAYS = 3  # 延長できない本は期限の何日前から知らせるか
DEBUG_DIR = pathlib.Path("debug")


class LoginError(Exception):
    pass


def parse_date(s):
    return dt.datetime.strptime(s, "%Y%m%d").date()


# ---------------------------------------------------------------- ログイン


def login(page, email, password, timeout_s):
    """Microsoft Entra 経由の SAML でログインし、Primo API 用の Authorization ヘッダを返す。

    email が空なら画面での手動ログインを待つ(--headed でのローカル確認用)。
    """
    is_loans = lambda r: "/primaws/rest/priv/myaccount/loans" in r.url
    with page.expect_request(is_loans, timeout=timeout_s * 1000) as req_info:
        page.goto(LOGIN_URL)
        if email:
            _sign_in_microsoft(page, email, password, timeout_s)
    auth = req_info.value.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise LoginError("Primo の認証トークンを取得できませんでした")
    return auth


def _sign_in_microsoft(page, email, password, timeout_s):
    page.locator('input[name="loginfmt"]').fill(email, timeout=30_000)
    page.locator("#idSIButton9").click()
    passwd = page.locator('input[name="passwd"]')
    passwd.wait_for(state="visible", timeout=30_000)
    passwd.fill(password)
    page.locator("#idSIButton9").click()

    # パスワード送信後は Microsoft → 大学 IdP → WINE と自動で遷移する。
    # 途中で出うる画面だけ処理し、Microsoft から抜けるまで待つ。
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not page.url.startswith(MS_HOST):
            return
        for sel in ("#passwordError", "#usernameError"):
            if page.locator(sel).is_visible():
                raise LoginError("Microsoft: " + page.locator(sel).inner_text().strip())
        if page.locator("#KmsiCheckboxField").is_visible():  # サインインの状態を維持しますか?
            page.locator("#idBtn_Back").click()
        page.wait_for_timeout(500)
    raise LoginError(f"Microsoft のサインイン画面から先に進めませんでした (画面: {page.title()})")


# ---------------------------------------------------------------- API


def check_reply(resp, what):
    if not resp.ok:
        raise RuntimeError(f"{what}: HTTP {resp.status}")
    return resp.json()


def fetch_loans(api, auth):
    data = check_reply(api.get(LOANS_API, headers={"Authorization": auth}), "貸出一覧")
    if data.get("status") != "ok":
        raise RuntimeError(f"貸出一覧: {data.get('reply-text')}")
    block = (data.get("data") or {}).get("loans") or {}
    if "Y" in (block.get("showmore") or []):
        print("警告: 貸出が100件を超えているため、一部しか確認できていません", file=sys.stderr)
    return block.get("loan") or []


def renew_loan(api, auth, loan_id):
    data = check_reply(
        api.post(RENEW_API, headers={"Authorization": auth}, data={"id": loan_id}), "延長"
    )
    print("renew_loans 応答:", json.dumps(data, ensure_ascii=False), file=sys.stderr)
    result = (((data.get("data") or {}).get("loans") or {}).get("loan") or [{}])[0]
    ok = data.get("status") == "ok" and result.get("renewed") == "Y"
    return ok, result


# ---------------------------------------------------------------- 判定


def plan(loan, today, days_before):
    """(action, 理由) を返す。action は skip / renew / attention。"""
    due = parse_date(loan["duedate"])
    left = (due - today).days
    if left < -GRACE_DAYS:
        return "attention", f"期限を{-left}日過ぎていて延長できません。返却してください"
    max_renew = loan.get("maxrenewdate")
    if max_renew and due >= parse_date(max_renew):
        blocked = "最大延長日に達しています。期限までに返却してください"
    elif loan.get("renew") != "Y":
        blocked = "延長できません(予約が入っている等)。期限までに返却してください"
    else:
        blocked = None
    if blocked and left <= WARN_DAYS:
        return "attention", blocked
    if left > days_before or blocked:
        return "skip", f"期限まで{left}日"
    if loan.get("loandate") == today.strftime("%Y%m%d"):
        return "skip", "今日借りた本は明日から延長できます"
    return "renew", f"期限まで{left}日"


def fmt(d):
    return f"{d[:4]}/{d[4:6]}/{d[6:]}"


def process(loans, today, days_before, renew_fn):
    """各貸出を判定して延長する。(レポート行, 要対応があるか) を返す。"""
    lines, attention = [], False
    for loan in sorted(loans, key=lambda x: x["duedate"]):
        title = loan.get("title", "(タイトル不明)")
        action, reason = plan(loan, today, days_before)
        due = fmt(loan["duedate"])
        if action == "renew":
            ok, result = renew_fn(loan["loanid"])
            if ok:
                new_due = fmt(result["duedate"]) if result.get("duedate") else "(dry-runのため未実行)"
                lines.append(f"✅ 延長: {title} … {due} → {new_due}")
                if parse_date(loan["duedate"]) < today:  # 実行が抜けた日があったということなので知らせる
                    attention = True
                    lines.append("   ⚠️ 期限を過ぎてからの延長でした。延滞扱いになっていないかWINEで確認してください")
                continue
            status = result.get("loanstatus") or "理由不明"
            if "既に更新済み" in status:
                lines.append(f"・ 延長済み: {title} … 期限 {due}")
                continue
            action, reason = "attention", f"延長に失敗しました({status})。期限までに返却してください"
        if action == "attention":
            attention = True
            lines.append(f"⚠️ 要対応: {title} … 期限 {due}: {reason}")
        else:
            lines.append(f"・ そのまま: {title} … 期限 {due} ({reason})")
    if not loans:
        lines.append("借りている本はありません")
    return lines, attention


# ---------------------------------------------------------------- main


def report(lines, header):
    text = "\n".join([header, ""] + lines)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"### {header}\n\n" + "\n".join(f"- {l}" for l in lines) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days-before", type=int, default=1, help="期限の何日前から延長するか (既定: 1)")
    ap.add_argument("--dry-run", action="store_true", help="延長せず、何をするかだけ表示する")
    ap.add_argument("--headed", action="store_true", help="ブラウザを表示する(認証情報が無ければ手動ログイン)")
    ap.add_argument("--from-json", help="ログインせず、保存した貸出一覧JSONで判定だけ試す")
    ap.add_argument("--today", help="判定に使う日付 YYYY-MM-DD (テスト用)")
    args = ap.parse_args()

    today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(JST).date()
    dry = lambda loan_id: (True, {})
    mode = "(dry-run) " if args.dry_run or args.from_json else ""
    header = f"WINE 自動延長 {mode}{today:%Y-%m-%d}"

    if args.from_json:
        data = json.loads(pathlib.Path(args.from_json).read_text(encoding="utf-8"))
        loans = data["data"]["loans"].get("loan") or []
        lines, attention = process(loans, today, args.days_before, dry)
        report(lines, header)
        return 1 if attention else 0

    # Secrets に貼り付けたときに紛れ込む末尾の改行を落とす
    email = os.environ.get("WASEDA_EMAIL", "").strip()
    password = os.environ.get("WASEDA_PASSWORD", "").strip("\r\n")
    if not (email and password) and not args.headed:
        print("WASEDA_EMAIL と WASEDA_PASSWORD を設定してください", file=sys.stderr)
        return 2

    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        page = browser.new_page(locale="ja-JP", timezone_id="Asia/Tokyo")
        try:
            auth = login(page, email, password, timeout_s=300 if not email else 90)
            loans = fetch_loans(page.request, auth)
            renew_fn = dry if args.dry_run else (lambda loan_id: renew_loan(page.request, auth, loan_id))
            lines, attention = process(loans, today, args.days_before, renew_fn)
        except (LoginError, PlaywrightError, RuntimeError) as e:
            DEBUG_DIR.mkdir(exist_ok=True)
            try:
                page.screenshot(path=str(DEBUG_DIR / "failure.png"))
            except PlaywrightError:
                pass
            report([f"❌ エラー: {e}", f"最後に開いていた画面: {page.url.split('?')[0]}"], header)
            return 2
        finally:
            browser.close()

    report(lines, header)
    return 1 if attention else 0


if __name__ == "__main__":
    sys.exit(main())

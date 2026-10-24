"""ファイル読込と種類の自動判別。ファイル名ではなく列名で判別する。"""
import io

import pandas as pd

KENCOM_KINDS = {
    "user_summary": "ユーザーサマリ（歩活参加・ポイント等）",
    "launch_active": "アクティブフラグ",
    "launch_monthly": "月次起動回数",
    "article_views": "記事閲覧ログ",
    "lifelog_daily": "日次ライフログ（歩数・体重・睡眠・血圧等）",
}
SIRUTASU_KINDS = {
    "sirutasu_attr": "ユーザー属性（年齢・性別・世帯・店舗）",
    "sirutasu_nutr": "栄養素・売場の購買量",
}


def read_table(name: str, data: bytes) -> pd.DataFrame:
    """UTF-16(タブ区切り) / UTF-8 / CP932 の CSV・TSV を読む。"""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = data.decode("utf-16")
    else:
        for enc in ("utf-8-sig", "cp932"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError(f"{name}: 文字コードを判別できません")
    head = text.split("\n", 1)[0]
    sep = "\t" if head.count("\t") > head.count(",") else ","
    return pd.read_csv(io.StringIO(text), sep=sep, low_memory=False)


def detect(df: pd.DataFrame):
    """(アプリ, 種類) を返す。判別できなければ (None, None)。"""
    cols = set(df.columns)
    if "個人ID" in cols:
        if "article_id" in cols:
            return "kencom", "article_views"
        if {"active_month", "launch_count"} <= cols:
            return "kencom", "launch_monthly"
        if "active_flag" in cols:
            return "kencom", "launch_active"
        if {"日付", "歩数"} <= cols:
            return "kencom", "lifelog_daily"
        if any(c.startswith("歩活参加") for c in cols) or "都市OS連携フラグ" in cols:
            return "kencom", "user_summary"
    if "Id" in cols:
        if "User Sirutasu Id" in cols:
            return "sirutasu", "sirutasu_attr"
        if any(c.endswith("Sufficiency Rate") or c.startswith("Display Category") for c in cols):
            return "sirutasu", "sirutasu_nutr"
    return None, None


def load_files(files):
    """files: [(name, bytes)] → {"sirutasu": [(name, kind, df)], "kencom": {kind: df}}, ログ"""
    out = {"sirutasu": [], "kencom": {}}
    log = []
    for name, data in files:
        try:
            df = read_table(name, data)
        except Exception as e:  # noqa: BLE001
            log.append({"ファイル": name, "判別": "読込エラー", "行数": 0, "メモ": str(e)})
            continue
        app, kind = detect(df)
        if app == "sirutasu":
            out["sirutasu"].append((name, kind, df))
            label = "シルタス：" + SIRUTASU_KINDS[kind]
        elif app == "kencom":
            if kind in out["kencom"]:
                out["kencom"][kind] = pd.concat([out["kencom"][kind], df], ignore_index=True).drop_duplicates()
            else:
                out["kencom"][kind] = df
            label = "ケンコム：" + KENCOM_KINDS[kind]
        else:
            label = "判別できません（列名が想定と違います）"
        log.append({"ファイル": name, "判別": label, "行数": len(df), "列数": df.shape[1]})
    return out, pd.DataFrame(log)

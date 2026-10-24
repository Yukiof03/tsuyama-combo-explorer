"""アプリごとのファイルを1つに統合し、「1ユーザー＝1行」の分析用テーブルと変数定義を作る。

指標の考え方（津山プロジェクトの分析と同じ）
- シルタス: 購買量は人によって違うため、栄養は「栄養バランス指数＝栄養素の充足率÷エネルギー充足率×100」、
  売場は「食品重量（飲料・酒を除く）に占める構成比」で比べる。
- ケンコム: 歩数は100〜50,000歩の日のみ有効。体重変化は最初30日平均→最後30日平均（観察90日以上・4回以上）。
"""
import re

import numpy as np
import pandas as pd

from .labels import SIRUTASU_LABELS

K_MIN = 10


def _snake(c):
    return c.strip().lower().replace(" ", "_")


def _jp(c):
    s = SIRUTASU_LABELS.get(_snake(c), c)
    for t in ["[充足率]", "[摂取量]", " [g]", "[g]", " [mg]", " [μg]", " [kcal]"]:
        s = s.replace(t, "")
    s = s.strip()
    if _snake(c) == "sodium_chloride_equivalent_sufficiency_rate":
        s = "食塩"
    if _snake(c) == "display_category_seasoning_amount_g":
        s = "調味料"
    return s


def age_bin(a):
    return pd.cut(a, [0, 29, 39, 49, 59, 64, 74, 200],
                  labels=["〜29", "30代", "40代", "50代", "60-64", "65-74", "75+"]).astype(str).replace("nan", np.nan)


# ---------------------------------------------------------------- 単位
UNITS = {
    "年齢": "歳", "世帯人数": "人", "買い物比率": "%", "購買月数": "か月", "エネルギー充足率": "%",
    "歩活参加回数": "回", "独自ポイント": "pt", "kencomコイン": "コイン", "お知らせ既読件数": "件",
    "起動回数": "回", "起動月数": "か月", "記事閲覧数": "本", "閲覧記事数（ユニーク）": "本",
    "歩数（日平均）": "歩/日", "歩数の記録日数": "日", "週末−平日の歩数差": "歩/日",
    "体重（平均）": "kg", "体重変化率": "%", "体重の記録頻度": "回/週", "睡眠時間（平均）": "時間",
    "最高血圧（平均）": "mmHg", "最低血圧（平均）": "mmHg", "体温・朝（平均）": "℃",
    "行動メニュー達成率": "%", "行動メニュー設定数（1日あたり）": "個/日", "Na/K比": "",
}


def unit_of(col):
    """(単位, 補足)。指数は単位を持たないので「100＝カロリー相応」を補足として返す。"""
    if col.endswith(" 指数"):
        return "", "100＝カロリー相応"
    if col.endswith("構成比") or col.endswith("構成比（全体）") or col.endswith("エネルギー比") or col.endswith("記事の割合"):
        return "%", ""
    if col == "Na/K比":
        return "", "食塩指数÷カリウム指数"
    return UNITS.get(col, ""), ""


def add_units(V):
    for v in V:
        if v["kind"] == "num":
            v["unit"], v["unit_note"] = unit_of(v["col"])
    return V


def _var(col, label, kind, group, desc="", src=None):
    """src: 元になったデータ。src が重なる2変数は定義上つながるため、既定で検定から外す。"""
    return {"col": col, "label": label, "kind": kind, "group": group, "desc": desc, "src": set(src or [col])}


# ================================================================ シルタス
def merge_sirutasu(frames):
    """Sheet 2/3/4 などを Id で結合 → 1行＝ユーザー×月。"""
    if not frames:
        return None
    merged = None
    for _, _, df in frames:
        df = df.copy()
        df["Id"] = df["Id"].astype("int64").astype(str)
        if merged is None:
            merged = df
        else:
            new = [c for c in df.columns if c not in merged.columns or c == "Id"]
            merged = merged.merge(df[new], on="Id", how="outer")
    merged["年月"] = merged["Id"].str[:4] + "-" + merged["Id"].str[4:6]
    if "User Sirutasu Id" not in merged.columns:
        merged["User Sirutasu Id"] = merged["Id"].str[6:].astype(int)
    if "User Cityos Id" in merged.columns:
        merged["User Cityos Id"] = merged["User Cityos Id"].map(lambda x: str(int(x)) if pd.notna(x) else np.nan)
    return merged.sort_values(["User Sirutasu Id", "年月"]).reset_index(drop=True)


def sirutasu_users(m: pd.DataFrame, min_months=3, min_erate=10):
    """ユーザー別テーブルと変数定義。"""
    uid = "User Sirutasu Id"
    RATE = [c for c in m.columns if c.endswith("Sufficiency Rate")]
    NUTR = [c for c in RATE if not c.startswith("Energy")]
    CAT_ALL = [c for c in m.columns if c.startswith("Display Category") and m[c].fillna(0).abs().sum() > 0]
    CAT_FOOD = [c for c in CAT_ALL if "Drink" not in c and "Alcoholic" not in c]
    last_month = m["年月"].max()
    new_from = (pd.Period(last_month, "M") - 3).strftime("%Y-%m")  # データ最終月を含む直近4か月の登録＝新規

    b = m[m["Energy Amount Kcal"] > 0] if "Energy Amount Kcal" in m.columns else m
    g = b.groupby(uid)
    last = b.groupby(uid).last()
    u = pd.DataFrame(index=g.size().index)
    V = []
    if "User Gender" in m.columns:
        u["性別"] = last["User Gender"].map({"male": "男性", "female": "女性"})
        V.append(_var("性別", "性別", "cat", "属性"))
    if "User Age" in m.columns:
        u["年齢"] = last["User Age"]
        u["年代"] = age_bin(u["年齢"])
        V += [_var("年齢", "年齢", "num", "属性", src=["age"]), _var("年代", "年代", "cat", "属性", src=["age"])]
    if "User Family Num" in m.columns:
        u["世帯人数"] = last["User Family Num"]
        u["世帯"] = np.where(u["世帯人数"] == 1, "単身", "2人以上")
        V += [_var("世帯人数", "世帯人数", "num", "属性", "未入力の初期値が1の可能性あり", src=["family"]),
              _var("世帯", "世帯（単身/2人以上）", "cat", "属性", "未入力の初期値が1の可能性あり", src=["family"])]
    if "User Main Store" in m.columns:
        st = last["User Main Store"]
        cnt = st.value_counts()
        u["代表店舗"] = st.where(st.isin(cnt[cnt >= 30].index))  # 30人未満の店舗は比較から外す
        V.append(_var("代表店舗", "代表店舗", "cat", "属性", "利用者30人以上の店舗のみ"))
    if "User Purchase Rate" in m.columns:
        u["買い物比率"] = last["User Purchase Rate"]
        V.append(_var("買い物比率", "買い物比率（自己申告%）", "num", "属性", "60%は未入力の初期値の可能性あり"))
    u["登録時期"] = np.where(m.groupby(uid)["年月"].min().reindex(u.index) >= new_from, "直近4か月の新規", "既存")
    V.append(_var("登録時期", "登録時期（直近4か月の新規/既存）", "cat", "属性", src=["tenure"]))
    u["購買月数"] = g.size()
    u["エネルギー充足率"] = g["Energy Sufficiency Rate"].median()
    V += [_var("購買月数", "購買あり月数", "num", "購買量", src=["tenure"]),
          _var("エネルギー充足率", "エネルギー充足率（月中央値）", "num", "購買量", "マルイでの購買量の目安")]

    sums = g[RATE + CAT_ALL].sum()
    for c in NUTR:
        col = f"{_jp(c)} 指数"
        u[col] = sums[c] / sums["Energy Sufficiency Rate"] * 100
        V.append(_var(col, col, "num", "栄養バランス", "充足率÷エネルギー充足率×100（100＝カロリー相応）", src=[_jp(c)]))
    food_tot = sums[CAT_FOOD].sum(axis=1).replace(0, np.nan)
    for c in CAT_FOOD:
        col = f"{_jp(c)} 構成比"
        u[col] = sums[c] / food_tot * 100
        V.append(_var(col, col, "num", "売場構成", "食品重量（飲料・酒を除く）に占める%"))
    all_tot = sums[CAT_ALL].sum(axis=1).replace(0, np.nan)
    for c in CAT_ALL:
        if "Drink" in c or "Alcoholic" in c:
            col = f"{_jp(c)} 構成比（全体）"
            u[col] = sums[c] / all_tot * 100
            V.append(_var(col, col, "num", "売場構成", "飲料・酒を含む全重量に占める%"))
    amt = {k: [c for c in m.columns if c.startswith(k) and c.endswith("Amount G")] for k in ["Protein", "Fat", "Carbohydrate"]}
    if all(amt.values()):
        s2 = g[[amt["Protein"][0], amt["Fat"][0], amt["Carbohydrate"][0]]].sum()
        tot = s2.iloc[:, 0] * 4 + s2.iloc[:, 1] * 9 + s2.iloc[:, 2] * 4
        for i, (lab, kcal) in enumerate([("たんぱく質", 4), ("脂質", 9), ("炭水化物", 4)]):
            col = f"{lab} エネルギー比"
            u[col] = s2.iloc[:, i] * kcal / tot * 100
            V.append(_var(col, col + "（%）", "num", "PFC", src=["pfc", "たんぱく質", "脂質", "炭水化物"]))
    if "食塩 指数" in u and "カリウム 指数" in u:
        u["Na/K比"] = u["食塩 指数"] / u["カリウム 指数"]
        V.append(_var("Na/K比", "Na/K比（食塩指数÷カリウム指数）", "num", "栄養バランス", src=["食塩", "カリウム"]))
    u["_cityos"] = m.groupby(uid)["User Cityos Id"].agg(lambda s: s.dropna().iloc[-1] if s.notna().any() else np.nan) \
        if "User Cityos Id" in m.columns else np.nan
    u.index.name = "シルタスユーザID"
    full = u.copy()
    u = u[(u["購買月数"] >= min_months) & (u["エネルギー充足率"] >= min_erate)]
    return u, full, add_units(V)


def sirutasu_wide(m: pd.DataFrame):
    """ユーザー×（指標_年月）の横持ち（ダウンロード用）。"""
    uid = "User Sirutasu Id"
    metrics = [c for c in m.columns if c.endswith("Sufficiency Rate") or c.endswith("Amount G") or c.endswith("Amount Mg")
               or c.endswith("Amount Mcg") or c.endswith("Amount Kcal")]
    w = m.pivot_table(index=uid, columns="年月", values=metrics, aggfunc="first")
    w.columns = [f"{_jp(a)}（{a}）_{b}" for a, b in w.columns]
    return w.reset_index()


# ================================================================ ケンコム
THEMES = [
    ("認知症・脳", r"認知症|MCI|パーキンソン|脳の|脳を|脳は|脳に"),
    ("歩行・運動", r"歩|ウォーキング|ランニング|マラソン|運動|筋トレ|トレーニング|ストレッチ|体操|たいそう|スクワット|筋肉|ヨガ|エクササイズ|ポーズ|プランク|体幹|引き締め"),
    ("睡眠", r"睡眠|眠|寝"),
    ("血圧・循環器", r"血圧|脳卒中|脳梗塞|心筋|心臓|動脈|血管|不整脈|脈"),
    ("血糖・糖尿病", r"血糖|糖尿"),
    ("禁煙・飲酒", r"たばこ|タバコ|禁煙|喫煙|お酒|二日酔い|飲酒|アルコール"),
    ("体重・ダイエット", r"ダイエット|太り|やせ|痩|体重|肥満|脂肪|メタボ|くびれ"),
    ("食事・栄養・レシピ", r"レシピ|食材|管理栄養士|栄養|食べ|食事|料理|朝食|野菜|缶|ご飯|ごはん|味噌|みそ|スープ|お茶|果物|副菜|おかず|コーヒー|油|ビタミン|調理"),
    ("メンタル・自律神経", r"ストレス|イライラ|メンタル|自律神経|うつ|不安|緊張|呼吸法|心の|心を|思考|心理|精神科|孤独"),
    ("痛み・からだの不調", r"腰|膝|肩|首|背中|股関節|痛|こり|むくみ|頭痛|めまい|冷え|疲れ|疲労|だる|ツボ|不調|咳"),
]


def _theme(t):
    for name, pat in THEMES:
        if re.search(pat, str(t)):
            return name
    return "その他"


def kencom_users(k: dict):
    uid = "個人ID"
    V = []
    ids = set()
    for df in k.values():
        ids |= set(df[uid].dropna())
    u = pd.DataFrame(index=sorted(ids))
    u.index.name = "ケンコム個人ID"

    us = k.get("user_summary")
    if us is not None:
        us = us.set_index(uid)
        walk = [c for c in us.columns if c.startswith("歩活参加")]
        for c in walk:
            u[c] = us[c].map({1: "参加", 0: "不参加"})
            V.append(_var(c, c, "cat", "歩活"))
        if walk:
            u["歩活参加回数"] = us[walk].sum(axis=1)
            V.append(_var("歩活参加回数", "歩活参加回数", "num", "歩活", src=walk + ["歩活参加回数"]))
        for c, lab in [("独自ポイント保有数", "独自ポイント"), ("kencomコイン保有数", "kencomコイン"), ("お知らせ既読件数", "お知らせ既読件数")]:
            if c in us:
                u[lab] = us[c]
                V.append(_var(lab, lab, "num", "利用", "抽出時点の累計値"))
        for c in us.columns:
            if c.endswith("フラグ") or c.endswith("利用有無"):
                if set(us[c].dropna().unique()) <= {0, 1}:
                    u[c] = us[c].map({1: "あり", 0: "なし"})
                    V.append(_var(c, c, "cat", "利用"))
        if "都市OSID平文" in us:
            u["_cityos"] = us["都市OSID平文"].map(lambda x: str(int(x)) if pd.notna(x) else np.nan)

    mon = k.get("launch_monthly")
    if mon is not None:
        mon = mon.copy()
        mon["ym"] = mon["active_month"].astype(str).str[:7]
        last = mon["ym"].max()
        recent = (pd.Period(last, "M") - 2).strftime("%Y-%m")
        u["起動回数"] = mon.groupby(uid).launch_count.sum()
        u["起動月数"] = mon.groupby(uid).ym.nunique()
        u[["起動回数", "起動月数"]] = u[["起動回数", "起動月数"]].fillna(0)
        u["直近3か月の起動"] = np.where(u.index.isin(mon.loc[mon.ym >= recent, uid]), "あり", "なし")
        V += [_var("起動回数", "アプリ起動回数（合計）", "num", "利用", src=["launch"]), _var("起動月数", "起動した月数", "num", "利用", src=["launch"]),
              _var("直近3か月の起動", "直近3か月の起動（継続）", "cat", "利用", src=["launch"])]

    art = k.get("article_views")
    if art is not None:
        art = art.copy()
        u["記事閲覧数"] = art.groupby(uid).size().reindex(u.index).fillna(0)
        u["閲覧記事数（ユニーク）"] = art.groupby(uid).article_id.nunique().reindex(u.index).fillna(0)
        V += [_var("記事閲覧数", "記事閲覧数", "num", "記事", src=["article"]), _var("閲覧記事数（ユニーク）", "閲覧記事数（ユニーク）", "num", "記事", src=["article"])]
        if "article_title" in art:
            th = art.drop_duplicates("article_id").set_index("article_id").article_title.map(_theme)
            art["theme"] = art.article_id.map(th)
            top = art.groupby(uid).theme.agg(lambda s: s.value_counts().index[0])
            enough = art.groupby(uid).size() >= 10
            u["よく読む記事テーマ"] = top.where(enough)
            V.append(_var("よく読む記事テーマ", "よく読む記事テーマ（10本以上閲覧者）", "cat", "記事", "タイトルのキーワードで自動分類", src=["theme"]))
            for tname in ["歩行・運動", "食事・栄養・レシピ"]:
                sh = art.assign(t=art.theme == tname).groupby(uid).t.mean() * 100
                u[f"{tname} 記事の割合"] = sh.where(enough)
                V.append(_var(f"{tname} 記事の割合", f"{tname} 記事の割合（%）", "num", "記事", src=["theme"]))

    life = k.get("lifelog_daily")
    if life is not None:
        life = life.copy()
        life["日付"] = pd.to_datetime(life["日付"], errors="coerce")
        life["steps"] = life["歩数"].where(life["歩数"].between(100, 50000))
        g = life.groupby(uid)
        u["歩数（日平均）"] = g.steps.mean()
        u["歩数の記録日数"] = g.steps.count()
        V += [_var("歩数（日平均）", "歩数（日平均）", "num", "歩数", src=["steps"]), _var("歩数の記録日数", "歩数の記録日数", "num", "歩数")]
        life["wkend"] = life["日付"].dt.dayofweek >= 5
        wk = life.groupby([uid, "wkend"]).steps.mean().unstack()
        if {True, False} <= set(wk.columns):
            u["週末−平日の歩数差"] = wk[True] - wk[False]
            V.append(_var("週末−平日の歩数差", "週末−平日の歩数差", "num", "歩数", src=["steps"]))
        if "体重" in life:
            wt = life[life["体重"].between(25, 200)]
            u["体重（平均）"] = wt.groupby(uid)["体重"].mean()
            def chg(x):
                x = x.sort_values("日付")
                span = (x["日付"].iloc[-1] - x["日付"].iloc[0]).days
                if span < 90 or len(x) < 4:
                    return pd.Series({"pct": np.nan, "freq": np.nan})
                f = x[x["日付"] <= x["日付"].iloc[0] + pd.Timedelta(days=30)]["体重"].mean()
                l = x[x["日付"] >= x["日付"].iloc[-1] - pd.Timedelta(days=30)]["体重"].mean()
                return pd.Series({"pct": (l - f) / f * 100, "freq": len(x) / (span + 1) * 7})
            wc = wt.groupby(uid)[["日付", "体重"]].apply(chg)
            u["体重変化率"] = wc["pct"]
            u["体重の記録頻度"] = wc["freq"]
            V += [_var("体重（平均）", "体重（平均, kg）", "num", "体重"),
                  _var("体重変化率", "体重変化率（%）", "num", "体重", "最初30日平均→最後30日平均（観察90日以上）"),
                  _var("体重の記録頻度", "体重の記録頻度（回/週）", "num", "体重")]
        if "睡眠時間(分)" in life:
            sl = life["睡眠時間(分)"].where(life["睡眠時間(分)"].between(180, 900)) / 60
            cnt = sl.groupby(life[uid]).count()
            u["睡眠時間（平均）"] = sl.groupby(life[uid]).mean().where(cnt >= 30)
            V.append(_var("睡眠時間（平均）", "睡眠時間（平均, 時間）", "num", "睡眠", "30日以上記録した人"))
        hi = [c for c in life.columns if c.startswith("血圧(最高)")]
        lo = [c for c in life.columns if c.startswith("血圧(最低)")]
        if hi:
            sbp = life[hi].where(life[hi].apply(lambda s: s.between(70, 250))).mean(axis=1)
            dbp = life[lo].where(life[lo].apply(lambda s: s.between(40, 150))).mean(axis=1)
            cnt = sbp.groupby(life[uid]).count()
            u["最高血圧（平均）"] = sbp.groupby(life[uid]).mean().where(cnt >= 20)
            u["最低血圧（平均）"] = dbp.groupby(life[uid]).mean().where(cnt >= 20)
            V += [_var("最高血圧（平均）", "最高血圧（平均, mmHg）", "num", "血圧", "20日以上記録した人", src=["bp"]),
                  _var("最低血圧（平均）", "最低血圧（平均, mmHg）", "num", "血圧", "20日以上記録した人", src=["bp"])]
        if "体温(朝)" in life:
            t = life["体温(朝)"].where(life["体温(朝)"].between(34, 42))
            cnt = t.groupby(life[uid]).count()
            u["体温・朝（平均）"] = t.groupby(life[uid]).mean().where(cnt >= 20)
            V.append(_var("体温・朝（平均）", "体温・朝（平均, ℃）", "num", "体温", "20日以上記録した人"))
        ach = [c for c in life.columns if c.startswith("達成")]
        if ach:
            done = life[ach].sum(axis=1, min_count=1)
            nset = life[ach].notna().sum(axis=1)
            u["行動メニュー達成率"] = (done.groupby(life[uid]).sum() / nset.groupby(life[uid]).sum().replace(0, np.nan)) * 100
            u["行動メニュー設定数（1日あたり）"] = nset[nset > 0].groupby(life[uid][nset > 0]).mean()
            V += [_var("行動メニュー達成率", "行動メニュー達成率（%）", "num", "行動メニュー"),
                  _var("行動メニュー設定数（1日あたり）", "行動メニュー設定数（1日あたり）", "num", "行動メニュー")]
    return u, add_units(V)


def kencom_monthly_wide(k: dict):
    """ユーザー×月の横持ち（起動回数・歩数・体重）。ダウンロード用。"""
    uid = "個人ID"
    parts = []
    mon = k.get("launch_monthly")
    if mon is not None:
        mon = mon.assign(ym=mon["active_month"].astype(str).str[:7])
        w = mon.pivot_table(index=uid, columns="ym", values="launch_count", aggfunc="sum")
        w.columns = [f"起動回数_{c}" for c in w.columns]
        parts.append(w)
    life = k.get("lifelog_daily")
    if life is not None:
        life = life.assign(ym=pd.to_datetime(life["日付"], errors="coerce").dt.strftime("%Y-%m"),
                           steps=life["歩数"].where(life["歩数"].between(100, 50000)))
        for col, lab in [("steps", "歩数（日平均）"), ("体重", "体重（月平均）")]:
            if col in life:
                w = life.pivot_table(index=uid, columns="ym", values=col, aggfunc="mean")
                w.columns = [f"{lab}_{c}" for c in w.columns]
                parts.append(w)
    if not parts:
        return None
    return pd.concat(parts, axis=1).reset_index()


# ================================================================ 併用者（都市OS ID で突合）
def cross_users(su_full, s_vars, ku, k_vars):
    if "_cityos" not in su_full or "_cityos" not in ku:
        return None, []
    s = su_full.dropna(subset=["_cityos"]).reset_index().set_index("_cityos")
    k = ku.dropna(subset=["_cityos"]).reset_index().set_index("_cityos")
    s = s[~s.index.duplicated(keep="last")]
    j = s.join(k, how="inner", lsuffix="（シ）", rsuffix="（ケ）")
    V = []
    for v in s_vars:
        if v["kind"] == "num" and v["group"] != "属性" and v["col"] in j:
            V.append({**v, "group": "シルタス：" + v["group"], "label": "[シ] " + v["label"], "src": {"S_" + s for s in v["src"]}})
    for v in k_vars:
        if v["kind"] == "num" and v["col"] in j:
            V.append({**v, "group": "ケンコム：" + v["group"], "label": "[ケ] " + v["label"], "src": {"K_" + s for s in v["src"]}})
    return j, V

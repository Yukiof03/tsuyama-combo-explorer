"""変数の全組み合わせを検定し、効果量・p値・q値（Benjamini-Hochberg）を返す。

数値×数値   : Spearman の順位相関（効果量 ρ）
カテゴリ×数値: 2群 Mann-Whitney U（効果量 r）／3群以上 Kruskal-Wallis（効果量 ε²）
カテゴリ×カテゴリ: カイ二乗検定（2×2で期待度数<5なら Fisher）（効果量 Cramér's V）
人数が10人未満のカテゴリは検定・図から除く（k-匿名）。
"""
from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats

K_MIN = 10
MIN_N_NUM = 30
THRESH = {"ρ": 0.1, "r": 0.1, "ε²": 0.01, "V": 0.1}


def _cats(s: pd.Series):
    vc = s.value_counts()
    return vc[vc >= K_MIN].index.tolist()


def test_pair(df, a, b, min_n=MIN_N_NUM):
    """a, b は変数定義 dict。結果 dict か None。"""
    x, y = df[a["col"]], df[b["col"]]
    if a["kind"] == "num" and b["kind"] == "num":
        m = pd.concat([x, y], axis=1).dropna()
        if len(m) < min_n or m.iloc[:, 0].nunique() < 3 or m.iloc[:, 1].nunique() < 3:
            return None
        r, p = stats.spearmanr(m.iloc[:, 0], m.iloc[:, 1])
        if np.isnan(p):
            return None
        return {"検定": "Spearman相関", "効果量": r, "効果量の種類": "ρ", "n": len(m), "p": p,
                "向き": "正" if r > 0 else "負", "詳細": ""}
    if a["kind"] == "cat" and b["kind"] == "num":
        a, b, x, y = a, b, x, y
    elif a["kind"] == "num" and b["kind"] == "cat":
        a, b, x, y = b, a, y, x
    if a["kind"] == "cat" and b["kind"] == "num":
        cats = _cats(x.dropna())
        groups = {c: y[(x == c)].dropna() for c in cats}
        groups = {c: g for c, g in groups.items() if len(g) >= K_MIN}
        if len(groups) < 2:
            return None
        meds = {c: g.median() for c, g in groups.items()}
        hi, lo = max(meds, key=meds.get), min(meds, key=meds.get)
        u = b.get("unit", "") if len(b.get("unit", "")) <= 4 else ""
        detail = f"中央値 最大「{hi}」{meds[hi]:.3g}{u}／最小「{lo}」{meds[lo]:.3g}{u}"
        n = sum(len(g) for g in groups.values())
        if len(groups) == 2:
            g1, g2 = groups.values()
            if g1.nunique() + g2.nunique() <= 2:
                return None
            u, p = stats.mannwhitneyu(g1, g2, alternative="two-sided")
            z = stats.norm.isf(p / 2) if p > 0 else 8.0
            return {"検定": "Mann-Whitney", "効果量": z / np.sqrt(n), "効果量の種類": "r", "n": n, "p": p,
                    "向き": f"{hi} > {lo}", "詳細": detail}
        try:
            h, p = stats.kruskal(*groups.values())
        except ValueError:
            return None
        return {"検定": "Kruskal-Wallis", "効果量": h / (n - 1), "効果量の種類": "ε²", "n": n, "p": p,
                "向き": f"最大：{hi}", "詳細": detail}
    # cat × cat
    m = pd.concat([x, y], axis=1).dropna()
    ca, cb = _cats(m.iloc[:, 0]), _cats(m.iloc[:, 1])
    m = m[m.iloc[:, 0].isin(ca) & m.iloc[:, 1].isin(cb)]
    if len(ca) < 2 or len(cb) < 2 or len(m) < min_n:
        return None
    ct = pd.crosstab(m.iloc[:, 0], m.iloc[:, 1])
    chi2, p, _, exp = stats.chi2_contingency(ct)
    test = "カイ二乗"
    if ct.shape == (2, 2) and (exp < 5).any():
        p = stats.fisher_exact(ct.values)[1]
        test = "Fisher"
    v = np.sqrt(chi2 / ct.values.sum() / (min(ct.shape) - 1))
    rate = (ct.div(ct.sum(axis=1), axis=0) * 100)
    col0 = rate.columns[0]
    detail = "「" + str(col0) + "」の割合: " + "／".join(f"{i} {rate.loc[i, col0]:.0f}%" for i in rate.index[:4])
    return {"検定": test, "効果量": v, "効果量の種類": "V", "n": int(ct.values.sum()), "p": p, "向き": "", "詳細": detail}


def run_all(df, variables, dataset, only_cross=False, progress=None, exclude_trivial=True, min_n=MIN_N_NUM):
    vs = [v for v in variables if v["col"] in df.columns]
    pairs = list(combinations(vs, 2))
    if exclude_trivial:  # 同じ元データから作った変数どうし（例: 年齢×年代）は定義上つながるので外す
        pairs = [(a, b) for a, b in pairs if not (a.get("src", {a["col"]}) & b.get("src", {b["col"]}))]
    if only_cross:  # 併用者: シルタス変数 × ケンコム変数 だけ
        pairs = [(a, b) for a, b in pairs if a["group"].split("：")[0] != b["group"].split("：")[0]]
    rows = []
    for i, (a, b) in enumerate(pairs):
        if progress and i % 50 == 0:
            progress(i / max(len(pairs), 1))
        try:
            r = test_pair(df, a, b, min_n=min_n)
        except Exception:  # noqa: BLE001
            r = None
        if r is None:
            continue
        rows.append({"データ": dataset, "変数1": a["label"], "変数2": b["label"], "col1": a["col"], "col2": b["col"],
                     "単位1": a.get("unit", ""), "単位2": b.get("unit", ""), "補足1": a.get("unit_note", ""), "補足2": b.get("unit_note", ""),
                     "kind1": a["kind"], "kind2": b["kind"], "分類1": a["group"], "分類2": b["group"],
                     "同系統": a["group"] == b["group"], **r})
    res = pd.DataFrame(rows)
    if res.empty:
        return res
    res = res.sort_values("p").reset_index(drop=True)
    m = len(res)
    res["q"] = (res["p"] * m / (np.arange(m) + 1))[::-1].cummin()[::-1].clip(upper=1)
    return res


def classify(res, q_th=0.05, thresh=None):
    thresh = thresh or THRESH
    if res.empty:
        return res.assign(判定=pd.Series(dtype=str))
    big = res.apply(lambda r: abs(r["効果量"]) >= thresh[r["効果量の種類"]], axis=1)
    sig = res["q"] < q_th
    res = res.copy()
    res["判定"] = np.select([sig & big, sig & ~big], ["有意（効果あり）", "有意（効果小）"], "有意でない")
    return res


def _g(r, k):
    v = r.get(k, "") if hasattr(r, "get") else ""
    return "" if v is None or (isinstance(v, float) and v != v) else str(v)


def axis_label(r, i, suffix=""):
    """変数i(1/2)の軸ラベル。例: 年齢［歳］、亜鉛 指数（100＝カロリー相応）。ラベルに既に単位があれば重ねない。"""
    import re
    lab, unit, note = r[f"変数{i}"], _g(r, f"単位{i}"), _g(r, f"補足{i}")
    # 「体重（平均, kg）」「達成率（%）」のように括弧内に単位が書かれていれば重ねない（「起動回数」の「回」は単位ではない）
    if unit and not re.search(r"[（(,、]\s*" + re.escape(unit) + r"\s*[）)]", lab):
        return f"{lab}{suffix}［{unit}］"
    if note and note not in lab:
        return f"{lab}{suffix}（{note}）"
    return lab + suffix


def val_unit(r, i):
    """値ラベルに付ける短い単位（%・歳・kg など）。長い単位は軸だけに付ける。"""
    u = _g(r, f"単位{i}")
    return u if len(u) <= 2 else ""


def sentence(r):
    """結果を1文で説明する。"""
    q = "q<0.001" if r["q"] < 0.001 else f"q={r['q']:.3f}"
    if r["効果量の種類"] == "ρ":
        dirw = "高い" if r["効果量"] > 0 else "低い"
        return f"「{r['変数1']}」が高いほど「{r['変数2']}」が{dirw}傾向（ρ={r['効果量']:+.2f}、{q}、n={r['n']:,}）"
    if r["効果量の種類"] in ("r", "ε²"):
        cat, num = (r["変数1"], r["変数2"]) if r["kind1"] == "cat" else (r["変数2"], r["変数1"])
        return f"「{cat}」によって「{num}」が異なる（{r['詳細']}、{r['効果量の種類']}={r['効果量']:.3f}、{q}、n={r['n']:,}）"
    return f"「{r['変数1']}」と「{r['変数2']}」に関連（{r['詳細']}、V={r['効果量']:.2f}、{q}、n={r['n']:,}）"

"""Plotly の図。色は役割で固定（カテゴリは決まった順に割り当て、循環させない）。"""
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from .analyze import K_MIN, axis_label

FONT = "Hiragino Sans, Yu Gothic, YuGothic, Meiryo, sans-serif"
CAT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
JUDGE_COLOR = {"有意（効果あり）": "#eb6834", "有意（効果小）": "#eda100", "有意でない": "#b5b4ae"}
INK2, GRID = "#52514e", "#e4e3df"
AGE_ORDER = ["〜29", "30代", "40代", "50代", "60-64", "65-74", "75+"]


def _layout(fig, title=None, h=430):
    fig.update_layout(font=dict(family=FONT, size=13, color="#0b0b0b"), height=h, margin=dict(l=10, r=10, t=50 if title else 20, b=10),
                      title=dict(text=title or "", x=0, font=dict(size=15)),
                      plot_bgcolor="white", paper_bgcolor="white", legend=dict(orientation="h", y=-0.18))
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID)
    return fig


def pair_chart(df, r):
    """検定結果1行に対応する図。"""
    c1, c2, l1, l2 = r["col1"], r["col2"], r["変数1"], r["変数2"]
    if r["kind1"] == "num" and r["kind2"] == "num":
        m = df[[c1, c2]].dropna()
        sample = m.sample(min(len(m), 3000), random_state=0)
        fig = go.Figure()
        fig.add_trace(go.Scattergl(x=sample[c1], y=sample[c2], mode="markers", name="ユーザー",
                                   marker=dict(size=6, color=CAT[0], opacity=0.35, line=dict(width=0)),
                                   hovertemplate=f"{axis_label(r, 1)}: %{{x:.3g}}<br>{axis_label(r, 2)}: %{{y:.3g}}<extra></extra>"))
        # 10分位ごとの中央値（傾向線）
        try:
            m["bin"] = pd.qcut(m[c1].rank(method="first"), 10, labels=False)
            t = m.groupby("bin").agg(x=(c1, "median"), y=(c2, "median"))
            fig.add_trace(go.Scatter(x=t.x, y=t.y, mode="lines+markers", name="10分位ごとの中央値",
                                     line=dict(color=CAT[1], width=2.5), marker=dict(size=8)))
        except ValueError:
            pass
        # 外れ値で軸がつぶれないよう 1〜99%点で表示
        for ax, c in (("x", c1), ("y", c2)):
            lo, hi = m[c].quantile([0.01, 0.99])
            pad = (hi - lo) * 0.05 or 1
            fig.update_layout(**{f"{ax}axis": dict(range=[lo - pad, hi + pad], title=axis_label(r, 1) if ax == "x" else axis_label(r, 2))})
        return _layout(fig)
    if r["kind1"] == "cat" and r["kind2"] == "cat":
        m = df[[c1, c2]].dropna()
        k1 = m[c1].value_counts()
        k2 = m[c2].value_counts()
        m = m[m[c1].isin(k1[k1 >= K_MIN].index) & m[c2].isin(k2[k2 >= K_MIN].index)]
        ct = pd.crosstab(m[c1], m[c2])
        pct = ct.div(ct.sum(axis=1), axis=0) * 100
        fig = go.Figure()
        for i, col in enumerate(pct.columns):
            fig.add_trace(go.Bar(y=[f"{idx}（n={ct.loc[idx].sum()}）" for idx in pct.index], x=pct[col], name=str(col),
                                 orientation="h", marker=dict(color=CAT[i % len(CAT)], line=dict(color="white", width=2)),
                                 text=[f"{v:.0f}%" for v in pct[col]], textposition="inside",
                                 hovertemplate="%{y}<br>" + f"{col}: " + "%{x:.1f}%<extra></extra>"))
        fig.update_layout(barmode="stack", xaxis=dict(title=f"「{l2}」の内訳（%）", range=[0, 100]), yaxis=dict(title=l1))
        return _layout(fig, h=max(300, 60 * len(pct) + 150))
    cat, num, lc, ln = (c1, c2, l1, l2) if r["kind1"] == "cat" else (c2, c1, l2, l1)
    m = df[[cat, num]].dropna()
    vc = m[cat].value_counts()
    keep = vc[vc >= K_MIN].index
    m = m[m[cat].isin(keep)]
    order = m.groupby(cat)[num].median().sort_values(ascending=False).index.tolist()
    natural = [o for o in AGE_ORDER if o in order]
    if len(natural) == len(order):  # 年代のように順序があるカテゴリは自然な順で並べる
        order = natural
    lo, hi = m[num].quantile([0.01, 0.99])
    fig = go.Figure()
    for i, c in enumerate(order):
        v = m.loc[m[cat] == c, num]
        fig.add_trace(go.Box(y=v, name=f"{c}<br>(n={len(v)})", marker_color=CAT[i % len(CAT)] if len(order) <= len(CAT) else CAT[0],
                             boxmean=False, boxpoints=False, line=dict(width=1.5)))
    pad = (hi - lo) * 0.05 or 1
    fig.update_layout(showlegend=False, yaxis=dict(title=axis_label(r, 2 if r["kind1"] == "cat" else 1), range=[lo - pad, hi + pad]), xaxis=dict(title=lc))
    return _layout(fig)


def volcano(res):
    d = res.copy()
    d["−log10(q)"] = (-np.log10(d["q"].clip(lower=1e-300))).clip(upper=50)  # 50以上（q<1e-50）は50で頭打ち
    d["|効果量|"] = d["効果量"].abs()
    d["組み合わせ"] = d["変数1"] + " × " + d["変数2"]
    fig = px.scatter(d, x="|効果量|", y="−log10(q)", color="判定", color_discrete_map=JUDGE_COLOR,
                     hover_data={"組み合わせ": True, "効果量の種類": True, "n": True, "|効果量|": ":.3f", "−log10(q)": ":.1f", "判定": False},
                     category_orders={"判定": list(JUDGE_COLOR)})
    fig.add_hline(y=-np.log10(0.05), line=dict(color=INK2, dash="dot", width=1), annotation_text="q=0.05", annotation_position="top left")
    fig.update_traces(marker=dict(size=7, opacity=0.75, line=dict(width=0)))
    fig.update_yaxes(title="−log10(q)（50以上は50で表示）")
    return _layout(fig, h=480)


def corr_heatmap(df, variables, res):
    """数値変数どうしの Spearman ρ。有意でないセルは空白。"""
    nums = [v for v in variables if v["kind"] == "num" and v["col"] in df.columns]
    if len(nums) < 2:
        return None
    lab = {v["col"]: v["label"] for v in nums}
    mat = pd.DataFrame(np.nan, index=[v["col"] for v in nums], columns=[v["col"] for v in nums])
    rr = res[(res["効果量の種類"] == "ρ")]
    for _, r in rr.iterrows():
        val = r["効果量"] if r["q"] < 0.05 else np.nan
        mat.loc[r["col1"], r["col2"]] = mat.loc[r["col2"], r["col1"]] = val
    names = [lab[c] for c in mat.index]
    fig = go.Figure(go.Heatmap(z=mat.values, x=names, y=names, zmin=-0.6, zmax=0.6, colorscale=[[0, "#e34948"], [0.5, "#f0efec"], [1, "#2a78d6"]],
                               hovertemplate="%{y} × %{x}<br>ρ=%{z:.2f}<extra></extra>", colorbar=dict(title="ρ")))
    fig.update_xaxes(tickangle=45, tickfont=dict(size=10))
    fig.update_yaxes(tickfont=dict(size=10), autorange="reversed")
    return _layout(fig, h=max(500, 16 * len(names) + 200))

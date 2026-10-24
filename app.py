#!/usr/bin/env python3
"""津山データ 組み合わせ分析ツール（シルタス／ケンコム）

起動:
    streamlit run app.py --server.headless true --browser.gatherUsageStats false --server.address localhost
データはこのPCの中だけで処理し、外部には送信しない。
"""
import hashlib
import hmac
import io
import os
import sys
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

from core import analyze, charts, ingest, integrate, present

st.set_page_config(page_title="津山データ 組み合わせ分析", layout="wide")

st.markdown("""
<style>
html, body, [class*="css"], .stMarkdown, .stDataFrame { font-family: "Hiragino Sans", "Yu Gothic", YuGothic, Meiryo, sans-serif; }
.block-container { padding-top: 1.6rem; }
.kpi { border: 1px solid #e4e3df; border-radius: 8px; padding: 10px 14px; background: #fcfcfb; }
.kpi .v { font-size: 1.6rem; font-weight: 700; }
.kpi .l { color: #52514e; font-size: .85rem; }
.tag { display:inline-block; padding: 2px 8px; border-radius: 10px; font-size: .8rem; font-weight: 700; color: white; }
</style>
""", unsafe_allow_html=True)

# 実行環境：ブラウザ内（stlite/Pyodide）・クラウドのサーバー・ローカルPC
IN_BROWSER = sys.platform == "emscripten"
IS_CLOUD = Path.home().as_posix().startswith("/home/appuser") or os.environ.get("TSUYAMA_CLOUD") == "1"
NO_FOLDER = IN_BROWSER or IS_CLOUD  # サーバーやブラウザではPC内フォルダの読込は使えない


def _secret(name):
    try:
        return st.secrets.get(name)
    except Exception:  # noqa: BLE001  secrets.toml が無い（ローカル）
        return None


def password_gate():
    """secrets に app_password があるときだけ、合言葉の入力を求める。"""
    pw = _secret("app_password")
    if not pw or st.session_state.get("authed"):
        return
    st.title("津山データ 組み合わせ分析")
    entered = st.text_input("合言葉", type="password")
    if entered and hmac.compare_digest(entered, str(pw)):
        st.session_state["authed"] = True
        st.rerun()
    elif entered:
        st.error("合言葉が違います")
    st.stop()


password_gate()

JUDGES = ["有意（効果あり）", "有意（効果小）", "有意でない"]
CHART_NOTE = {
    2: "点は1人ずつ、線は横軸を10等分した区間ごとの中央値。外れ値で見づらくならないよう1〜99%点の範囲を表示しています。",
    1: "箱は中央50%の範囲、中の線は中央値。10人未満のカテゴリは表示していません。",
    0: "各カテゴリの中での内訳（%）。10人未満のカテゴリは表示していません。",
}
DATASETS = ["シルタス", "ケンコム", "両アプリ併用者"]


# ================================================================ パイプライン（キャッシュ）
@st.cache_data(show_spinner=False, ttl=3600, max_entries=3)
def run_pipeline(files_key: str, _files: tuple, min_months: int, min_erate: float, exclude_trivial: bool):
    """_files はハッシュ対象外（大きいため）。同じ内容かどうかは files_key（MD5）で判定する。"""
    files = _files
    data, log = ingest.load_files(list(files))
    out = {"log": log, "tables": {}, "vars": {}, "results": {}, "full": {}, "raw": {}}
    if data["sirutasu"]:
        m = integrate.merge_sirutasu(data["sirutasu"])
        su, sfull, sv = integrate.sirutasu_users(m, min_months, min_erate)
        out["tables"]["シルタス"], out["vars"]["シルタス"], out["full"]["シルタス"] = su, sv, sfull
        out["raw"]["シルタス"] = m
    if data["kencom"]:
        ku, kv = integrate.kencom_users(data["kencom"])
        out["tables"]["ケンコム"], out["vars"]["ケンコム"] = ku, kv
        out["full"]["ケンコム"] = ku
        out["raw"]["ケンコム"] = data["kencom"]
    if "シルタス" in out["full"] and "ケンコム" in out["full"]:
        cj, cv = integrate.cross_users(out["full"]["シルタス"], out["vars"]["シルタス"], out["tables"]["ケンコム"], out["vars"]["ケンコム"])
        if cj is not None and len(cj) >= analyze.K_MIN:
            out["tables"]["両アプリ併用者"], out["vars"]["両アプリ併用者"] = cj, cv
    for name, df in out["tables"].items():
        cross = name == "両アプリ併用者"
        out["results"][name] = analyze.run_all(df, out["vars"][name], name, only_cross=cross,
                                               exclude_trivial=exclude_trivial, min_n=analyze.K_MIN if cross else analyze.MIN_N_NUM)
    return out


@st.cache_data(show_spinner=False, ttl=3600, max_entries=1500)
def pres_png(files_key, ds, c1, c2, title, style, dpi, _df, _r):
    """発表用グラフのPNG。図の中身は (データ, 変数1, 変数2, 見出し, 形式, 解像度) で決まる。"""
    return present.to_png(present.make_figure(_df, _r, title=title or None, style=style), dpi=dpi)


@st.cache_data(show_spinner=False, ttl=3600, max_entries=10)
def to_csv(df: pd.DataFrame, index=True) -> bytes:
    return df.to_csv(index=index).encode("utf-8-sig")


def results_excel(res: pd.DataFrame) -> bytes:
    cols = ["データ", "判定", "変数1", "変数2", "分類1", "分類2", "検定", "効果量の種類", "効果量", "n", "p", "q", "向き", "詳細"]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as xw:
        for j, sheet in [(["有意（効果あり）", "有意（効果小）"], "有意"), (["有意でない"], "有意でない")]:
            res[res["判定"].isin(j)][cols].to_excel(xw, sheet_name=sheet, index=False)
            xw.sheets[sheet].set_column(0, len(cols) - 1, 16)
    return buf.getvalue()


def paginate(n, key, sizes=(12, 24, 48)):
    """全 n 件をページ送りで表示するための (開始, 終了) を返す。"""
    if n == 0:
        return 0, 0
    c1, c2, c3 = st.columns([1, 1, 2.5])
    size = c1.selectbox("1ページの枚数", sizes, key=f"{key}_size")
    pages = (n - 1) // size + 1
    page = c2.number_input(f"ページ（全{pages}ページ）", 1, pages, 1, key=f"{key}_page")
    start, end = (page - 1) * size, min(page * size, n)
    c3.markdown(f"<div style='padding-top:2rem;color:#52514e'>全 {n:,} 件中 {start + 1:,}〜{end:,} 件目を表示</div>", unsafe_allow_html=True)
    return start, end


def kpi(col, value, label):
    col.markdown(f'<div class="kpi"><div class="v">{value}</div><div class="l">{label}</div></div>', unsafe_allow_html=True)


# ================================================================ サイドバー
with st.sidebar:
    st.header("設定")
    if NO_FOLDER:
        mode = "ファイルをアップロード"
    else:
        mode = st.radio("データの読み込み方", ["ファイルをアップロード", "PC内のフォルダから読む"], index=0)
    st.subheader("分析の条件")
    min_months = st.number_input("シルタス：購買のあった月数がこれ以上の人", 1, 24, 3)
    min_erate = st.number_input("シルタス：月々のエネルギー充足率（中央値）がこれ以上の人", 0.0, 100.0, 10.0, step=5.0,
                                help="ごく少量しか買っていない人を除くための条件です")
    exclude_trivial = st.checkbox("定義上つながる組み合わせを除く", True,
                                  help="例：年齢×年代、記事閲覧数×ユニーク閲覧数 など、同じ元データから作った変数どうし")
    st.subheader("有意の判定")
    q_th = st.select_slider("有意水準（補正後のq値）", options=[0.01, 0.05, 0.10], value=0.05)
    with st.expander("「効果あり」とみなす効果量の下限"):
        th = {"ρ": st.number_input("相関 |ρ|", 0.0, 1.0, 0.10, 0.05),
              "r": st.number_input("2群の差 r", 0.0, 1.0, 0.10, 0.05),
              "ε²": st.number_input("3群以上の差 ε²", 0.0, 1.0, 0.01, 0.005, format="%.3f"),
              "V": st.number_input("カテゴリどうし Cramér's V", 0.0, 1.0, 0.10, 0.05)}
    if IN_BROWSER:
        st.caption("データはこのブラウザの中だけで処理されます。サーバーには送信されません。")
    elif IS_CLOUD:
        st.caption("アップロードしたデータはクラウドのサーバー上で処理されます（ファイルとしては保存せず、計算結果も最長1時間で消去）。")
    else:
        st.caption("データはこのPCの中だけで処理され、外部には送信されません。")

st.title("津山データ 組み合わせ分析")
if IS_CLOUD:
    st.warning("このアプリはクラウド上で動いています。津山市から提供された個人単位のデータを入れる場合は、データの取り扱いルール（外部サーバーでの処理の可否）を守ってください。",
               icon="⚠️")
st.caption("シルタス（購買→栄養）とケンコム（歩数・ライフログ・アプリ利用）のファイルを入れると、アプリごとに統合し、"
           "変数の全組み合わせを検定して「有意」「有意でない」に分けて表示します。")

tab_in, tab_int, tab_res, tab_map, tab_pres, tab_help = st.tabs(
    ["① データ投入", "② 統合データ", "③ 分析結果", "④ 全体マップ", "⑤ 発表用グラフ", "使い方・注意"])

# ================================================================ ① データ投入
with tab_in:
    files = []
    if mode == "ファイルをアップロード":
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("シルタス")
            st.caption("「Sheet 2/3/4_Full Data_data.csv」など（UTF-16・タブ区切りもそのまま可）")
            up_s = st.file_uploader("シルタスのファイル（複数可）", type=["csv", "tsv", "txt"], accept_multiple_files=True, key="up_s")
        with c2:
            st.subheader("ケンコム")
            st.caption("user_summary / app_launch_active / app_launch_monthly / article_views / lifelog_daily")
            up_k = st.file_uploader("ケンコムのファイル（複数可）", type=["csv", "tsv", "txt"], accept_multiple_files=True, key="up_k")
        files = [(f.name, f.getvalue()) for f in (up_s or []) + (up_k or [])]
    else:
        folder = st.text_input("フォルダのパス", str(Path.home() / "Desktop/2026津山データ"))
        if st.button("このフォルダのCSVを読み込む", type="primary"):
            p = Path(folder).expanduser()
            if p.is_dir():
                st.session_state["folder_files"] = [(f.name, f.read_bytes()) for f in sorted(p.glob("*.csv")) + sorted(p.glob("*.tsv"))]
            else:
                st.error("フォルダが見つかりません")
        files = st.session_state.get("folder_files", [])

    if not files:
        st.info("ファイルを入れると、自動で種類を判別して統合・分析が始まります。")
        st.stop()

    with st.spinner("統合して、全組み合わせを検定しています…" + ("（ブラウザ内で計算するため1〜2分かかることがあります）" if IN_BROWSER else "（数秒〜数十秒）")):
        key_files = hashlib.md5(b"".join(n.encode() + hashlib.md5(d).digest() for n, d in files)).hexdigest()
        out = run_pipeline(key_files, tuple(files), int(min_months), float(min_erate), exclude_trivial)

    st.subheader("読み込んだファイル")
    st.dataframe(out["log"], hide_index=True, width="stretch")
    kinds = set(out["log"]["判別"])
    need = {"シルタス": ["シルタス：ユーザー属性（年齢・性別・世帯・店舗）", "シルタス：栄養素・売場の購買量"],
            "ケンコム": ["ケンコム：" + v for v in ingest.KENCOM_KINDS.values()]}
    c1, c2 = st.columns(2)
    for col, (app, req) in zip((c1, c2), need.items()):
        missing = [r.split("：")[1] for r in req if r not in kinds]
        if app in out["tables"] and not missing:
            col.success(f"{app}：必要なファイルがそろっています")
        elif app in out["tables"]:
            col.warning(f"{app}：一部のファイルがありません（{'、'.join(missing)}）。ある分だけで分析します")
        else:
            col.info(f"{app}：ファイルがありません")
    if "両アプリ併用者" in out["tables"]:
        st.caption(f"都市OS IDで両アプリを突合できた人：{len(out['tables']['両アプリ併用者'])}人（「両アプリ併用者」として参考分析）")

# 判定（サイドバーの閾値を反映）
res_all = pd.concat([analyze.classify(r, q_th, th) for r in out["results"].values() if len(r)], ignore_index=True) \
    if any(len(r) for r in out["results"].values()) else pd.DataFrame()

# ================================================================ ② 統合データ
with tab_int:
    names = [n for n in DATASETS if n in out["tables"]]
    for name, sub in zip(names, st.tabs(names)):
        with sub:
            df, V = out["tables"][name], out["vars"][name]
            c = st.columns(4)
            kpi(c[0], f"{len(df):,}人", "分析対象")
            if name == "シルタス":
                kpi(c[1], f"{len(out['full']['シルタス']):,}人", "購買のある利用者（全体）")
            kpi(c[2], f"{len(V)}", "分析に使う変数")
            kpi(c[3], f"{len(out['results'][name]):,}", "検定した組み合わせ")
            show = [v["col"] for v in V if v["col"] in df.columns]
            st.markdown("**1ユーザー＝1行に統合したデータ**（先頭100行）")
            st.dataframe(df[show].head(100), width="stretch")
            with st.expander("変数の一覧と定義"):
                st.dataframe(pd.DataFrame([{"変数": v["label"], "種類": "数値" if v["kind"] == "num" else "カテゴリ",
                                            "分類": v["group"], "説明": v["desc"]} for v in V]), hide_index=True, width="stretch")
            d1, d2, d3 = st.columns(3)
            d1.download_button("ユーザー別データ（CSV）", to_csv(df[show]), f"{name}_ユーザー別.csv", "text/csv")
            if name == "シルタス":
                d2.download_button("統合データ・縦持ち（ユーザー×月, CSV）", to_csv(out["raw"]["シルタス"], index=False),
                                   "シルタス_統合_ユーザー×月.csv", "text/csv")
                if d3.button("月次の横持ちデータを作る", key="wide_s"):
                    st.session_state["wide_s_csv"] = to_csv(integrate.sirutasu_wide(out["raw"]["シルタス"]), index=False)
                if "wide_s_csv" in st.session_state:
                    d3.download_button("横持ち（指標_年月, CSV）", st.session_state["wide_s_csv"], "シルタス_月次横持ち.csv", "text/csv")
            if name == "ケンコム":
                if d3.button("月次の横持ちデータを作る", key="wide_k"):
                    w = integrate.kencom_monthly_wide(out["raw"]["ケンコム"])
                    st.session_state["wide_k_csv"] = to_csv(w, index=False) if w is not None else None
                if st.session_state.get("wide_k_csv"):
                    d3.download_button("横持ち（起動・歩数・体重_年月, CSV）", st.session_state["wide_k_csv"], "ケンコム_月次横持ち.csv", "text/csv")
            if name == "両アプリ併用者":
                st.warning("人数が少ないため、統計的な結論は出せません（参考値）。個人が特定されないよう、データの扱いに注意してください。")

# ================================================================ ③ 分析結果
with tab_res:
    if res_all.empty:
        st.info("検定できる組み合わせがありませんでした。")
        st.stop()
    # 概要
    for name in [n for n in DATASETS if n in out["results"]]:
        r = res_all[res_all["データ"] == name]
        c = st.columns([1.2, 1, 1, 1, 1])
        c[0].markdown(f"#### {name}")
        kpi(c[1], f"{len(r):,}", "検定した組み合わせ")
        for col, j in zip(c[2:], JUDGES):
            kpi(col, f"{(r['判定'] == j).sum():,}", j)
    st.divider()
    f1, f2, f3, f4 = st.columns([1.3, 1.6, 1.1, 1])
    ds = f1.multiselect("データ", [n for n in DATASETS if n in out["results"]], default=[n for n in DATASETS if n in out["results"]][:2])
    kw = f2.text_input("変数名で絞り込み（例：食塩、歩数、年齢）", "")
    same = f3.selectbox("同じ分類どうしの組み合わせ", ["含める", "除く", "それだけ"])
    order = f4.selectbox("並び順", ["効果量が大きい順", "q値が小さい順"])
    view = res_all[res_all["データ"].isin(ds)]
    if kw:
        terms = kw.replace("、", " ").split()
        view = view[view.apply(lambda r: any(t in r["変数1"] or t in r["変数2"] for t in terms), axis=1)]
    if same == "除く":
        view = view[~view["同系統"]]
    elif same == "それだけ":
        view = view[view["同系統"]]
    view = view.assign(_abs=view["効果量"].abs()).sort_values("_abs" if order.startswith("効果") else "q",
                                                               ascending=not order.startswith("効果"))

    cols = ["判定", "データ", "変数1", "変数2", "検定", "効果量の種類", "効果量", "q", "n", "向き", "詳細"]
    sig = view[view["判定"] != "有意でない"]
    non = view[view["判定"] == "有意でない"]
    t_sig, t_non = st.tabs([f"有意（{len(sig):,}）", f"有意でない（{len(non):,}）"])

    def show_list(sub, key):
        if key == "sig":
            pick = st.radio("表示", ["すべて", "効果ありのみ", "効果小のみ"], horizontal=True, key="pick_" + key)
            if pick == "効果ありのみ":
                sub = sub[sub["判定"] == "有意（効果あり）"]
            elif pick == "効果小のみ":
                sub = sub[sub["判定"] == "有意（効果小）"]
        gallery = st.toggle("グラフを一覧で表示（全件・ページ送り）", key="gal_" + key)
        if gallery:
            s0, s1 = paginate(len(sub), "galp_" + key)
            top = sub.iloc[s0:s1]
            for i in range(0, len(top), 2):
                cc = st.columns(2)
                for col, (_, r) in zip(cc, top.iloc[i:i + 2].iterrows()):
                    with col:
                        st.markdown(f"**{r['変数1']} × {r['変数2']}**")
                        st.caption(analyze.sentence(r))
                        st.plotly_chart(charts.pair_chart(out["tables"][r["データ"]], r), width="stretch",
                                        key=f"g_{key}_{r.name}")
            return
        st.caption("行をクリックすると、下にグラフが出ます。")
        disp = sub[cols].copy()
        disp["効果量"] = disp["効果量"].round(3)
        disp["q"] = disp["q"].map(lambda x: f"{x:.2g}")
        ev = st.dataframe(disp, hide_index=True, width="stretch", height=360,
                          on_select="rerun", selection_mode="single-row", key="tbl_" + key)
        rows = ev.selection.rows if ev and ev.selection else []
        if rows:
            r = sub.iloc[rows[0]]
            color = charts.JUDGE_COLOR[r["判定"]]
            st.markdown(f'<span class="tag" style="background:{color}">{r["判定"]}</span>　**{r["変数1"]} × {r["変数2"]}**'
                        f'（{r["データ"]}・{r["検定"]}）', unsafe_allow_html=True)
            st.write(analyze.sentence(r))
            if r["データ"] == "両アプリ併用者":
                st.warning("人数が少ないため参考値です。")
            st.plotly_chart(charts.pair_chart(out["tables"][r["データ"]], r), width="stretch", key="c_" + key)
            df_r = out["tables"][r["データ"]]
            hl = present.headline(df_r, r)
            st.download_button("このグラフを発表用の画像（PNG）で保存", pres_png(key_files, r["データ"], r["col1"], r["col2"], hl, "区間ごとの中央値", 200, df_r, r),
                               f"{r['変数1']}×{r['変数2']}.png".replace("/", "／"), "image/png", key="dl_" + key)
            st.caption(CHART_NOTE[(r["kind1"] == "num") + (r["kind2"] == "num")])

    with t_sig:
        show_list(sig, "sig")
    with t_non:
        show_list(non, "non")
    st.download_button("全結果をExcelで保存（有意／有意でない の2シート）", results_excel(res_all),
                       "組み合わせ分析_結果.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ================================================================ ④ 全体マップ
with tab_map:
    name = st.radio("データ", [n for n in DATASETS if n in out["results"] and len(out["results"][n])], horizontal=True)
    r = res_all[res_all["データ"] == name]
    st.markdown("**効果量と有意性の地図**（右上ほど「強く、確かな」関連。点にマウスを重ねると組み合わせが出ます）")
    st.plotly_chart(charts.volcano(r), width="stretch")
    st.markdown("**数値どうしの相関マップ**（有意なものだけ色付き。青＝正、赤＝負）")
    fig = charts.corr_heatmap(out["tables"][name], out["vars"][name], r)
    if fig is not None:
        st.plotly_chart(fig, width="stretch")
    st.markdown("**分類の組み合わせ別：有意（効果あり）の数**")
    g = r.assign(ペア=r.apply(lambda x: " × ".join(sorted([x["分類1"], x["分類2"]])), axis=1))
    summ = g.groupby("ペア").agg(検定数=("判定", "size"), 有意_効果あり=("判定", lambda s: (s == "有意（効果あり）").sum()),
                                有意_効果小=("判定", lambda s: (s == "有意（効果小）").sum()))
    summ["有意の割合(%)"] = ((summ["有意_効果あり"] + summ["有意_効果小"]) / summ["検定数"] * 100).round(0)
    st.dataframe(summ.sort_values("有意_効果あり", ascending=False), width="stretch")

# ================================================================ ⑤ 発表用グラフ
with tab_pres:
    st.markdown("有意だった組み合わせを選ぶと、**発表スライドと同じスタイルの図**（結論を書いた見出し・値ラベル・人数と検定結果の脚注）を作ります。"
                "PNGで1枚ずつ、またはまとめてZIP・PPTX（津山の発表デザイン）で保存できます。")
    sig_all = res_all[res_all["判定"] != "有意でない"]
    if sig_all.empty:
        st.info("有意な組み合わせがありません。")
    else:
        p1, p2, p3, p4 = st.columns([1.3, 1.2, 1.5, 1])
        ds_opts = [n for n in DATASETS if n in sig_all["データ"].unique()]
        # 選べるデータが増えたら（例：シルタスの後にケンコムを入れた）選択をやり直すため、キーに選択肢を含める
        p_ds = p1.multiselect("データ", ds_opts, default=ds_opts[:2], key="p_ds_" + "_".join(ds_opts))
        p_level = p2.radio("対象", ["有意（効果あり）のみ", "有意すべて"], key="p_level")
        p_kw = p3.text_input("変数名で絞り込み", "", key="p_kw")
        p_same = p4.checkbox("同じ分類どうしを除く", True, key="p_same", help="例：栄養素の指数どうし（栄養学的に当然似る組み合わせ）")
        pool = sig_all[sig_all["データ"].isin(p_ds)]
        if p_level.startswith("有意（効果あり）"):
            pool = pool[pool["判定"] == "有意（効果あり）"]
        if p_kw:
            terms = p_kw.replace("、", " ").split()
            pool = pool[pool.apply(lambda r: any(x in r["変数1"] or x in r["変数2"] for x in terms), axis=1)]
        if p_same:
            pool = pool[~pool["同系統"]]
        pool = pool.assign(_abs=pool["効果量"].abs()).sort_values("_abs", ascending=False).reset_index(drop=True)
        label_of = {i: f"{r['変数1']} × {r['変数2']}（{r['データ']}・{r['効果量の種類']}={r['効果量']:+.2f}）" for i, r in pool.iterrows()}
        p_mode = st.radio(f"グラフにする組み合わせ（候補 {len(pool):,}件・効果量の大きい順）", ["候補をすべて", "選んだものだけ"],
                          horizontal=True, key="p_mode")
        if p_mode == "候補をすべて":
            chosen = list(label_of)
        else:
            chosen = st.multiselect("組み合わせを選ぶ（選んだ順に図番号が付きます）", list(label_of), default=[],
                                    format_func=label_of.get, key="p_chosen")
            if not chosen:
                st.info("グラフにする組み合わせを選んでください。")
        o1, o2, o3, o4 = st.columns(4)
        style = o1.radio("数値×数値の描き方", ["区間ごとの中央値", "散布図＋傾向線"], key="p_style",
                         help="区間ごとの中央値：横軸を人数が等しい5区間に分けた棒グラフ（スライド向き）")
        with_title = o2.toggle("見出しを図に入れる", True, key="p_title", help="PPTXでは見出しをスライドのタイトルに置くため、図からは外します")
        numbered = o3.toggle("図番号を付ける", True, key="p_num")
        dpi = o4.select_slider("解像度（dpi）", [150, 200, 300], value=200, key="p_dpi")

        made = []
        for k, idx in enumerate(chosen, 1):
            r = pool.loc[idx]
            df_r = out["tables"][r["データ"]]
            auto = present.headline(df_r, r)
            hkey = f"hl_{r['データ']}_{r['col1']}_{r['col2']}"
            made.append((k, r, df_r, hkey, auto))
        s0, s1 = paginate(len(made), "presp")
        shown = made[s0:s1]
        for i in range(0, len(shown), 2):
            cols2 = st.columns(2)
            for col, (k, r, df_r, hkey, auto) in zip(cols2, shown[i:i + 2]):
                with col:
                    hl = st.text_input(f"図{k}の見出し（編集できます）", auto, key=hkey)
                    title = (f"図{k} " if numbered else "") + hl if with_title else ""
                    png = pres_png(key_files, r["データ"], r["col1"], r["col2"], title, style, dpi, df_r, r)
                    st.image(png, width="stretch")
                    st.download_button(f"図{k}をPNGで保存", png, f"図{k}_{r['変数1']}×{r['変数2']}.png".replace("/", "／"), "image/png",
                                       key=f"dlp_{hkey}")
        if made:
            st.divider()
            st.markdown(f"**まとめて保存**（{len(made):,}枚。1枚あたり約0.3秒かかります）")
            z1, z2 = st.columns(2)
            sig = (tuple(chosen), style, dpi, with_title, numbered,
                   tuple(st.session_state.get(m[3], m[4]) for m in made))  # 条件が変わったら作り直す

            def build_all(with_fig_title, label):
                bar = st.progress(0.0, text=f"{label}を作っています…")
                pngs = []
                for j, (k, r, df_r, hkey, auto) in enumerate(made):
                    hl = st.session_state.get(hkey, auto)
                    title = ((f"図{k} " if numbered else "") + hl) if with_fig_title else ""
                    pngs.append((k, r, hl, pres_png(key_files, r["データ"], r["col1"], r["col2"], title, style, dpi, df_r, r)))
                    bar.progress((j + 1) / len(made), text=f"{label}を作っています… {j + 1:,}/{len(made):,}")
                bar.empty()
                return pngs

            if z1.button(f"{len(made):,}枚をZIPにまとめる", key="mk_zip", type="primary"):
                zbuf = io.BytesIO()
                with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for k, r, hl, png in build_all(with_title, "ZIP"):
                        zf.writestr(f"図{k:03d}_{r['変数1']}×{r['変数2']}.png".replace("/", "／"), png)
                st.session_state["zip_bytes"], st.session_state["zip_sig"] = zbuf.getvalue(), sig
            if st.session_state.get("zip_bytes") and st.session_state.get("zip_sig") == sig:
                z1.download_button("ZIPを保存", st.session_state["zip_bytes"], "発表用グラフ.zip", "application/zip")
            if z2.button(f"{len(made):,}枚のPPTX（津山の発表デザイン）を作る", key="mk_pptx"):
                items = [{"png": png, "title": hl, "kicker": f"組み合わせ分析｜{r['データ']}", "note": ""}
                         for k, r, hl, png in build_all(False, "PPTX")]
                with st.spinner("PPTXにまとめています…"):
                    st.session_state["pptx_bytes"] = present.build_pptx(items)
                    st.session_state["pptx_sig"] = sig
            if st.session_state.get("pptx_bytes") and st.session_state.get("pptx_sig") == sig:
                z2.download_button("PPTXを保存", st.session_state["pptx_bytes"], "発表用グラフ.pptx",
                                   "application/vnd.openxmlformats-officedocument.presentationml.presentation")
            if not present.TEMPLATE.exists():
                st.caption("※ 津山のテンプレート（assets/tsuyama_template.pptx）が見つからないため、PPTXは白紙のデザインで作ります。")
            st.caption("見出しは自動で作った案です。発表前に、内容に合った言い回しに直してください。観察データなので、結果は因果ではなく関連です。")

# ================================================================ 使い方
with tab_help:
    st.markdown(f"""
### 使い方
1. **①データ投入**で、シルタスとケンコムのファイルを入れます（ファイル名ではなく中身の列で種類を自動判別します）。
2. **②統合データ**で、アプリごとに「1ユーザー＝1行」にまとめたデータを確認・ダウンロードできます。
3. **③分析結果**で、全組み合わせの検定結果を「有意」「有意でない」に分けて見られます。行をクリックするとグラフが出ます。
4. **④全体マップ**で、どの組み合わせが強く関連しているかを一望できます。
5. **⑤発表用グラフ**で、有意だった組み合わせを発表スライドと同じスタイルの図にして、PNG・ZIP・PPTXで保存できます。

### 分析の方法
| 組み合わせ | 検定 | 効果量 |
|---|---|---|
| 数値 × 数値 | Spearmanの順位相関 | ρ |
| カテゴリ × 数値（2群） | Mann-WhitneyのU検定 | r |
| カテゴリ × 数値（3群以上） | Kruskal-Wallis検定 | ε² |
| カテゴリ × カテゴリ | カイ二乗検定（2×2で期待度数5未満はFisher） | Cramér's V |

- たくさんの組み合わせを同時に調べるため、偶然の有意を除く**多重比較の補正（Benjamini-Hochberg法）**を行い、補正後のq値で判定します。
- **有意（効果あり）**＝q値が基準未満で、効果量も下限以上。**有意（効果小）**＝q値は基準未満だが効果量が小さい（人数が多いと小さな差でも有意になるため）。
- 10人未満のカテゴリは検定・図から除きます（個人の特定を防ぐため）。数値どうしは30人以上（併用者は10人以上）のときだけ検定します。

### 指標の作り方
- **シルタス**：マルイで買う量は人によって違うため、栄養は「栄養バランス指数＝各栄養素の充足率÷エネルギー充足率×100」（100＝カロリー相応）、
  売場は「食品重量（飲料・酒を除く）に占める構成比」で比べます。
- **ケンコム**：歩数は100〜50,000歩の日のみ有効。体重変化率は最初の30日平均→最後の30日平均（観察90日以上・4回以上記録）。
- **両アプリ併用者**：都市OS IDで突合した人。人数が少ないため参考値です。

### 注意
- 観察データなので、結果は**因果ではなく関連**です。また、全組み合わせを仮説なしで調べた結果なので、施策に使う前に再確認してください。
- シルタスの「世帯人数＝1」「買い物比率＝60%」は未入力の初期値の可能性があります。
- 直近4か月に登録した人は、新しい店舗の利用者など既存層と特徴が違うことがあります（「登録時期」で確認できます）。
""")

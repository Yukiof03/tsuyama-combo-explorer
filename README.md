# 津山データ 組み合わせ分析ツール

シルタス（購買→栄養）とケンコム（歩数・ライフログ・アプリ利用）のファイルを入れると、

1. ファイルの種類を中身の列から自動判別し、
2. アプリごとに「1ユーザー＝1行」に統合し（ダウンロード可）、
3. 変数の全組み合わせを検定して、
4. 「有意」「有意でない」に分けてグラフ付きで表示し、
5. 有意な組み合わせを発表スライドと同じスタイルの図（PNG・ZIP・津山デザインのPPTX）にする、

ローカル完結のWebアプリ（Streamlit）。データはこのPCの外に送信されない。

## クラウド版（チームで使う）

Streamlit Community Cloud に、このリポジトリ（非公開）から公開している。

- 公開設定：招待したメールアドレスの人だけ閲覧可（Streamlit Cloud の Share 設定で管理）。
- クラウドでは「PC内のフォルダから読む」は無効。ファイルはアップロードで入れる。
- アップロードしたデータはクラウドのサーバー上で処理される（ファイルとしては保存しない。計算結果のキャッシュは最長1時間で消える）。
  津山市から提供された個人単位のデータを入れる場合は、データの取り扱いルールを守ること。
- 日本語フォントは `packages.txt`（fonts-noto-cjk）でサーバーに入れている。
- 合言葉を使う場合は、Streamlit Cloud の Secrets に `app_password = "..."` を設定する（コードには書かない）。

## ローカルで起動

```bash
cd ~/Tsuyama_output/tsuyama-combo-explorer
python3 -m streamlit run app.py --server.port 8531 --server.headless true --browser.gatherUsageStats false --server.address localhost
```

ブラウザで http://localhost:8531 を開く。

## 入力ファイル（最初に提供されたものと同じ構成）

| アプリ | ファイル | 判別に使う列 |
|---|---|---|
| シルタス | Sheet 2_Full Data_data.csv（属性） | `Id`, `User Sirutasu Id` |
| シルタス | Sheet 3/4_Full Data_data.csv（栄養・売場） | `Id`, `… Sufficiency Rate`, `Display Category …` |
| ケンコム | user_summary.csv | `個人ID`, `歩活参加…` / `都市OS連携フラグ` |
| ケンコム | app_launch_active.csv | `個人ID`, `active_flag` |
| ケンコム | app_launch_monthly.csv | `個人ID`, `active_month`, `launch_count` |
| ケンコム | article_views.csv | `個人ID`, `article_id` |
| ケンコム | lifelog_daily.csv | `個人ID`, `日付`, `歩数` |

UTF-16（タブ区切り）・UTF-8・CP932 に対応。ファイル名は問わない。

## 分析の中身

- 数値×数値：Spearman相関（ρ）／カテゴリ×数値：Mann-Whitney（r）・Kruskal-Wallis（ε²）／カテゴリ×カテゴリ：カイ二乗・Fisher（Cramér's V）
- 多重比較は Benjamini-Hochberg 法で補正し、q値で判定。効果量の下限も満たすものを「有意（効果あり）」とする（下限は画面で変更可）。
- 同じ元データから作った変数どうし（例：年齢×年代）は「定義上つながる組み合わせ」として既定で除外。
- 10人未満のカテゴリは検定・図から除く（k-匿名）。
- 両アプリ併用者（都市OS IDで突合）は人数が少ないため参考値。

## 発表用グラフ（⑤タブ）

- 既定で候補（有意な組み合わせ）をすべて図にし、ページ送り（1ページ12/24/48枚）で全件を確認できる。「選んだものだけ」にも切替可。
- 有意な組み合わせを選ぶと、結論を書いた見出し・値ラベル・人数と検定結果の脚注つきの静止画を作る（見出しは画面で編集可）。
- ZIP・PPTXはボタンを押すと全件を作る（1枚約0.3秒、578枚で約2分。進み具合を表示）。
- ③分析結果の「グラフを一覧で表示」も全件をページ送りで見られる。
- 数値×数値は「人数が等しい5区間ごとの中央値」の棒グラフ（または散布図＋傾向線）、カテゴリ×数値は中央値の棒グラフ、カテゴリ×カテゴリは内訳の帯グラフ。
- PNG（1枚ずつ）、ZIP（まとめて）、PPTX（`assets/tsuyama_template.pptx` の「基本スライド」レイアウトに、見出し＝スライドタイトル、図＝白パネル内で配置。游ゴシック＋日本語指定）。
- ③分析結果で選んだ1件も「発表用の画像（PNG）で保存」できる。

## ファイル構成

- `app.py` … 画面
- `core/ingest.py` … 読込・判別
- `core/integrate.py` … 統合・指標づくり（変数定義）
- `core/analyze.py` … 全組み合わせの検定・判定
- `core/charts.py` … 画面上のグラフ（plotly）
- `core/present.py` … 発表用の図（matplotlib）とPPTX出力
- `assets/tsuyama_template.pptx` … 津山の発表テンプレート（26sp中間_津山.pptx の複製）
- `core/labels.py` … シルタス列名の日本語ラベル（tsuyama-health-analytics から複製）
- `smoke_test.py` … 実データで読込〜分析が通るかの確認用（`python3 smoke_test.py <フォルダ>`）

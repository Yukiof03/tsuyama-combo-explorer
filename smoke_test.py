"""実データ（ローカルのフォルダ）で、読込→統合→全組み合わせ分析が通るかを確認する。"""
import sys
import time
from pathlib import Path

from core import analyze, integrate, ingest

folder = Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / "Desktop/2026津山データ")
files = [(p.name, p.read_bytes()) for p in sorted(folder.glob("*.csv"))]
t0 = time.time()
data, log = ingest.load_files(files)
print(log.to_string(index=False))
m = integrate.merge_sirutasu(data["sirutasu"])
su, sfull, sv = integrate.sirutasu_users(m)
ku, kv = integrate.kencom_users(data["kencom"])
cj, cv = integrate.cross_users(sfull, sv, ku, kv)
print("シルタス", su.shape, len(sv), "ケンコム", ku.shape, len(kv), "併用", None if cj is None else cj.shape, len(cv), f"{time.time()-t0:.1f}s")
for name, df, V, oc in [("シルタス", su, sv, False), ("ケンコム", ku, kv, False), ("併用者", cj, cv, True)]:
    t1 = time.time()
    res = analyze.classify(analyze.run_all(df, V, name, only_cross=oc, min_n=10 if oc else 30))
    print(name, len(res), res["判定"].value_counts().to_dict(), f"{time.time()-t1:.1f}s")
    print(res.head(3)[["変数1", "変数2", "効果量の種類", "効果量", "q"]].to_string())
    if len(res):
        print(analyze.sentence(res.iloc[0]))

"""Aircraft type and FAA wake category per tail number, from the FAA aircraft registry when available.

Registry: https://registry.faa.gov/database/ReleasableAircraft.zip -> data/raw/faa/{MASTER,DEREG,ACFTREF}.txt
N-numbers get reassigned, so a 2015 tail is matched to the registration valid in 2015:
current registration issued by end 2015, else a deregistration cancelled from 2015 on.
"""

from __future__ import annotations

from functools import lru_cache

import pandas as pd

from .config import DATA_DIR

FAA_DIR = DATA_DIR / "faa"
CACHE = FAA_DIR / "tail_types.csv"  # tail -> model, built once from the 500 MB registry
REGISTRY_SRC = "FAA aircraft registry (MASTER/DEREG/ACFTREF), registration valid in 2015"

SUPER_MARKERS = ("A380",)
HEAVY_MARKERS = ("747", "767", "777", "787", "A300", "A310", "A330", "A340", "A350", "MD-11", "DC-10", "L-1011")


def category_from_model(model: str) -> str:
    """FAA JO 7110.65 weight class from the type name. Airline jets and turboprops in the DOT file are >= Large."""
    m = model.upper().replace(" ", "")
    if any(k in m for k in SUPER_MARKERS):
        return "SUPER"
    if any(k in m for k in HEAVY_MARKERS):
        return "HEAVY"
    if "757" in m:
        return "B757"
    return "LARGE"


def heuristic_category(airline: str, distance_mi: float) -> str:
    """Used when the tail is unknown: long-haul / Hawaii flying is widebody, the rest narrowbody or regional."""
    return "HEAVY" if distance_mi > 2600 or (airline == "HA" and distance_mi > 2000) else "LARGE"


def _read(name: str, cols: dict[str, str]) -> pd.DataFrame:
    path = FAA_DIR / name
    with open(path, encoding="utf-8-sig") as f:
        header = [c.strip().replace("-", " ") for c in f.readline().split(",")]
    # Some rows carry an unquoted comma in a name field: read only the leading columns we need, by position
    idx = {header.index(c): new for c, new in cols.items()}
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig", skiprows=1, header=None, names=range(len(header) + 5),
                     low_memory=False)
    return df[list(idx)].rename(columns=idx).apply(lambda s: s.str.strip())


def build_cache(tails: set[str]) -> pd.DataFrame:
    ref = _read("ACFTREF.txt", {"CODE": "code", "MFR": "mfr", "MODEL": "model"})
    ref["type"] = ref["mfr"] + " " + ref["model"]
    keys = {t.removeprefix("N"): t for t in tails}
    master = _read("MASTER.txt", {"N NUMBER": "n", "MFR MDL CODE": "code", "CERT ISSUE DATE": "date"})
    master = master[master["n"].isin(keys) & (master["date"] <= "20151231")].assign(rank=0)
    dereg = _read("DEREG.txt", {"N NUMBER": "n", "MFR MDL CODE": "code", "CANCEL DATE": "date"})
    dereg = dereg[dereg["n"].isin(keys) & (dereg["date"] >= "20150101")].assign(rank=1)
    # Prefer the current registration; among deregistrations, the first one cancelled after 2015 started
    both = pd.concat([master, dereg]).sort_values(["n", "rank", "date"]).drop_duplicates("n")
    out = both.merge(ref[["code", "type"]], on="code", how="left").dropna(subset=["type"])
    out = pd.DataFrame({"tail": out["n"].map(keys), "type": out["type"]})
    out.to_csv(CACHE, index=False)
    return out


@lru_cache
def tail_types(tails: frozenset[str] = frozenset()) -> dict[str, str]:
    if CACHE.exists():
        return dict(pd.read_csv(CACHE).itertuples(index=False))
    if (FAA_DIR / "MASTER.txt").exists() and tails:
        return dict(build_cache(set(tails)).itertuples(index=False))
    return {}

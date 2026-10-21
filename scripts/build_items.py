"""data/d2r/items.json 생성 — blizzhackers/d2data (MIT) 의 게임 데이터 + 한국어 문자열 조인.

    python scripts/build_items.py --download            # raw 를 받아서 생성
    python scripts/build_items.py --raw <dir>           # 이미 받은 json/ 폴더에서 생성

레코드: {id, kind, name_en, name_ko, code, base_en, base_ko, lvl, aliases[]}
  kind ∈ unique | set | runeword | rune | charm | base
한국어 값은 레거시 음차("할리퀸 크레스트")와 D2R 번역("수수께끼")이 섞여 있으므로 aliases 에 자동 변형(공백 제거 등)을 넣고,
친구 어휘는 data/d2r/slang.yaml 에서 따로 관리한다. 빠진 한국어명은 meta.missing_ko 에 기록 → 수동 보강.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://raw.githubusercontent.com/blizzhackers/d2data/master/json/"
FILES = ["uniqueitems", "setitems", "runes", "misc", "armor", "weapons", "localestrings-kor", "localestrings-eng"]


def fetch(raw: Path) -> None:
    raw.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        p = raw / f"{f}.json"
        if not p.exists():
            print("  download", f)
            urllib.request.urlretrieve(BASE + f + ".json", p)


def alias_forms(name: str) -> list[str]:
    out = {name, name.replace(" ", ""), name.replace("'", ""), name.replace("'", "").replace(" ", "")}
    return sorted(a for a in out if a and a != name)


def build(raw: Path) -> dict:
    def load(f: str):
        return json.loads((raw / f"{f}.json").read_text(encoding="utf-8"))

    kor = load("localestrings-kor")
    items, missing = [], []

    def ko(key: str) -> str | None:
        v = kor.get(key)
        return v if v and not re.fullmatch(r"[\s?]*", v) else None

    for v in load("uniqueitems").values():
        if not v.get("index") or not v.get("code"):
            continue
        name_ko = ko(v["index"])
        if not name_ko:
            missing.append(("unique", v["index"]))
        items.append(
            {
                "id": f"u:{v['index']}",
                "kind": "unique",
                "name_en": v["index"],
                "name_ko": name_ko,
                "code": v["code"],
                "base_en": v.get("*ItemName"),
                "base_ko": ko(v["code"]),
                "lvl": v.get("lvl"),
                "aliases": alias_forms(name_ko or ""),
            }
        )
    for v in load("setitems").values():
        if not v.get("index"):
            continue
        name_ko = ko(v["index"])
        if not name_ko:
            missing.append(("set", v["index"]))
        items.append(
            {
                "id": f"s:{v['index']}",
                "kind": "set",
                "name_en": v["index"],
                "name_ko": name_ko,
                "code": v.get("item"),
                "base_en": v.get("*ItemName"),
                "base_ko": ko(v.get("item", "")),
                "set_en": v.get("set"),
                "set_ko": ko(v.get("set", "")),
                "lvl": v.get("lvl"),
                "aliases": alias_forms(name_ko or ""),
            }
        )
    for v in load("runes").values():
        key, en = v.get("Name"), v.get("*Rune Name")
        if not key or not en:
            continue
        name_ko = ko(key)
        if not name_ko:
            missing.append(("runeword", en))
        runes = [v.get(f"Rune{i}") for i in range(1, 7) if v.get(f"Rune{i}")]
        items.append(
            {
                "id": f"rw:{en}",
                "kind": "runeword",
                "name_en": en,
                "name_ko": name_ko,
                "code": key,
                "runes": runes,
                "aliases": alias_forms(name_ko or ""),
            }
        )
    kinds = {
        "rune": "rune",
        "scha": "charm",
        "mcha": "charm",
        "lcha": "charm",
        "jewl": "jewel",
        "amul": "base",
        "ring": "base",
    }
    for code, v in load("misc").items():
        if not isinstance(v, dict) or v.get("type") not in kinds:
            continue
        name_ko = ko(code)
        if not name_ko:
            missing.append((kinds[v["type"]], v.get("name", code)))
        items.append(
            {
                "id": f"{kinds[v['type']]}:{code}",
                "kind": kinds[v["type"]],
                "name_en": v.get("name"),
                "name_ko": name_ko,
                "code": code,
                "lvl": v.get("level"),
                "aliases": alias_forms(name_ko or ""),
            }
        )
    for f in ("armor", "weapons"):
        for code, v in load(f).items():
            if not isinstance(v, dict) or not v.get("name"):
                continue
            name_ko = ko(code)
            if not name_ko:
                missing.append(("base", v["name"]))
            items.append(
                {
                    "id": f"base:{code}",
                    "kind": "base",
                    "name_en": v["name"],
                    "name_ko": name_ko,
                    "code": code,
                    "type": v.get("type"),
                    "lvl": v.get("level"),
                    "aliases": alias_forms(name_ko or ""),
                }
            )
    counts = {}
    for it in items:
        counts[it["kind"]] = counts.get(it["kind"], 0) + 1
    return {
        "meta": {
            "source": "https://github.com/blizzhackers/d2data (MIT)",
            "built": dt.date.today().isoformat(),
            "counts": counts,
            "n_missing_ko": len(missing),
            "missing_ko": missing,
            "note": "name_ko 는 레거시 음차/D2R 번역 혼재. 친구 어휘는 slang.yaml",
        },
        "items": items,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=ROOT / "data" / "d2r" / "raw")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "d2r" / "items.json")
    a = ap.parse_args()
    if a.download:
        fetch(a.raw)
    d = build(a.raw)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(d, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"items: {d['meta']['counts']}  missing_ko={d['meta']['n_missing_ko']}  -> {a.out}")
    print("  missing sample:", d["meta"]["missing_ko"][:12])

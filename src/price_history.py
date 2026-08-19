"""商品価格の日次スナップショットを蓄積し、値下がり・最安値を判定する。

このサイトが楽天市場そのものに対して持てる数少ない独自価値が「時間」。
毎日データを取っているので、単発のAPIレスポンスからは絶対に作れない
情報を出せる。自動生成のまま差別化できる数少ない方向になる。

ただし実測では、楽天の「表示価格」はほとんど動かない
(6日間の観測で174商品中1商品、0.6%しか変動しなかった)。
実質的な値引きはポイント倍率で行われており、こちらは約19%の商品が
2倍以上かつ全件が期間限定だった。そのため価格と倍率の両方を記録する。

CIは実行ごとに環境が消えるため、履歴はリポジトリに書き戻して永続化する
（.github/workflows/daily.yml のコミットステップ）。
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

from .articles import Article

log = logging.getLogger(__name__)

# 保持期間。長くするほどファイルが膨らむので、値下がり判定に十分な範囲に留める
HISTORY_DAYS = 90

# この日数見かけなくなった商品は履歴ごと捨てる(掲載から外れた商品を溜めない)
STALE_DAYS = 30


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        # 履歴が壊れていても記事生成は続けたい。空から作り直す
        log.warning("価格履歴を読めなかったので作り直します: %s", e)
        return {}


def save(path: Path, store: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # 差分を読める形にしておく(CIのコミット履歴で価格変動を追える)
    path.write_text(
        json.dumps(store, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8",
    )


def _prune(store: dict, today: date) -> None:
    """古いスナップショットと、長く見かけない商品を捨てる。"""
    oldest = (today - timedelta(days=HISTORY_DAYS)).isoformat()
    stale = (today - timedelta(days=STALE_DAYS)).isoformat()

    for code in list(store):
        rec = store[code]
        rec["h"] = [pt for pt in rec.get("h", []) if pt["d"] >= oldest]
        if not rec["h"] or rec["h"][-1]["d"] < stale:
            del store[code]


def update(articles: list[Article], store: dict, today: date) -> dict:
    """今日の価格を記録し、各商品に履歴由来の情報を書き戻す。

    同じ商品が複数記事に出ることがあるので、記録は item_code 単位で1回だけ行い、
    注釈は Product ごとに付ける（同じ商品オブジェクトとは限らないため）。
    """
    iso = today.isoformat()

    for article in articles:
        for p in article.products:
            if not p.item_code:
                continue

            rec = store.setdefault(p.item_code, {"h": []})
            hist = rec["h"]

            # 同日に複数回実行されても履歴が二重にならないようにする
            point = {"d": iso, "p": p.price, "r": p.point_rate}
            if not hist or hist[-1]["d"] != iso:
                hist.append(point)
            else:
                hist[-1] = point

            # 今日より前の直近観測。無ければ比較しない
            past = [pt for pt in hist if pt["d"] != iso]
            p.prev_price = past[-1]["p"] if past else 0
            # "r" は途中で導入したキーなので、古い履歴には存在しない
            p.prev_point_rate = past[-1].get("r", 0) if past else 0
            p.lowest_price = min(pt["p"] for pt in hist)
            p.days_tracked = len({pt["d"] for pt in hist})
            p.distinct_prices = len({pt["p"] for pt in hist})

    _prune(store, today)
    return store


def annotate(articles: list[Article], path: Path, today: date | None = None) -> None:
    """履歴の読み込み・更新・保存をまとめて行う。"""
    today = today or date.today()
    store = load(path)
    update(articles, store, today)
    save(path, store)

    prods = [p for a in articles for p in a.products]
    log.info(
        "価格履歴: %d商品を追跡中 / 比較可能 %d件 / 値下がり %d件 / 最安 %d件 / ポイント増 %d件",
        len(store),
        sum(1 for p in prods if p.days_tracked > 1),
        sum(1 for p in prods if p.price_drop),
        sum(1 for p in prods if p.is_lowest),
        sum(1 for p in prods if p.point_rate_up),
    )

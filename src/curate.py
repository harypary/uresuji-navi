"""どの商品を記事に載せるかを決めるロジック。

このファイルが収益の中核。ページに並ぶ10商品の選び方で
クリック率と成果額が決まるので、感覚ではなく期待報酬額でソートする。

    期待報酬 ≒ クリックされやすさ × 買われやすさ × 単価 × 料率

3要素それぞれの代理変数:
  クリックされやすさ … レビュー件数(=知名度・需要の代理)
  買われやすさ       … レビュー平均(低評価品はカゴ落ちする)
  単価               … itemPrice。ただし高額品ほどCVRが落ちるので平方根で減衰
"""

from __future__ import annotations

import math
import re

from .rakuten import Product

# 単価が期待報酬に効く強さ。1.0=報酬額そのまま、0=単価を無視。
# 高額品ほど報酬は大きいが購入率は落ちるため、その中間を取っている。
# 「安物ばかり並ぶ」なら上げる、「高すぎて売れない」なら下げる。
PRICE_DECAY_EXPONENT = 0.5

# 同一商品が別ショップから何件も出てくるのを潰すための正規化パターン
_NOISE = re.compile(
    r"[\[【(（].*?[\]】)）]"          # 【送料無料】【楽天1位】などの装飾ブロック
    r"|送料無料|ポイント\d+倍|あす楽|正規品|新品|即納"
    r"|[\s　]+"
)


def _dedupe_key(product: Product) -> str:
    """商品名から装飾を剥がして、同一商品の重複出品をまとめるためのキーを作る。"""
    return _NOISE.sub("", product.name)[:24].lower()


def expected_revenue(product: Product, commission_rate: float) -> float:
    """1インプレッションあたりの期待報酬(相対値)。絶対額ではなく順位付け用。

    commission_rate はジャンル単位の推定値だが、APIが商品ごとの実料率
    (affiliateRate)を返す場合はそちらを優先する。同じジャンルでも
    ショップによって料率が数倍違うため、実値のほうが精度が高い。
    """
    if product.price <= 0:
        return 0.0

    rate = product.affiliate_rate or commission_rate

    # レビュー0件〜数万件までを圧縮。件数が10倍でも効果は2倍強に留める
    demand = math.log1p(product.review_count)

    # 評価3.0以下はほぼ選ばれない。4.0→4.5の差を効かせるため2乗する
    quality = (product.review_average / 5.0) ** 2 if product.review_average else 0.3

    # 高額品は報酬単価が高いが購入率が落ちる。指数で減衰させてバランスを取る
    value = product.price ** PRICE_DECAY_EXPONENT * (rate / 100.0)

    return demand * quality * value


def curate(
    products: list[Product],
    commission_rate: float,
    limit: int,
    min_review_count: int = 3,
    min_review_average: float = 3.5,
    price_range: tuple[int, int] = (500, 200_000),
) -> list[Product]:
    """期待報酬の高い順に、重複を除いた商品を limit 件返す。"""
    lo, hi = price_range
    seen: set[str] = set()
    scored: list[tuple[float, Product]] = []

    for p in products:
        if not (lo <= p.price <= hi):
            continue
        if p.review_count < min_review_count:
            continue
        # 低評価品を載せるとページ全体の信頼性が落ち、他の商品のクリック率まで下がる。
        # レビューが付いていてなお評価が低いものだけを弾く(0件は上の条件で処理済み)
        if p.review_average and p.review_average < min_review_average:
            continue
        if not p.image:
            continue

        key = _dedupe_key(p)
        if key in seen:
            continue
        seen.add(key)

        scored.append((expected_revenue(p, commission_rate), p))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [p for _, p in scored[:limit]]


def fill(
    products: list[Product],
    commission_rate: float,
    limit: int,
    min_review_count: int,
) -> list[Product]:
    """curate の緩和版。件数が足りなければレビュー件数の条件を段階的に下げて埋める。

    ニッチなジャンルだとレビュー件数の条件で全滅することがあり、
    記事が空になるくらいなら条件を緩めたほうがよい。
    ただし緩めるのは「レビューが少ない」だけで、「評価が低い」商品は
    どこまで緩めても採用しない(min_review_average は据え置き)。
    """
    for threshold in (min_review_count, 1, 0):
        picked = curate(products, commission_rate, limit, threshold)
        if len(picked) >= limit:
            return picked
    return picked  # 全部緩めても足りない場合は取れただけ返す

"""APIキーが無くてもサイトの見た目を確認できるダミーデータ生成。

main.py --demo から呼ばれる。楽天へのリクエストは一切行わない。
生成されるリンクはすべて楽天市場のトップページに向く（成果は発生しない）。
"""

from __future__ import annotations

import random

from .articles import Article
from .rakuten import Product

_ADJ = ["軽量", "大容量", "静音", "折りたたみ", "抗菌", "コンパクト", "プロ仕様", "北欧風"]
_PLACEHOLDER = "https://placehold.jp/cccccc/666666/300x300.png?text=SAMPLE"


def _product(genre_name: str, i: int, rng: random.Random) -> Product:
    price = rng.choice([1280, 2480, 3980, 5980, 8800, 12800, 19800])
    return Product(
        name=f"【サンプル】{rng.choice(_ADJ)}{genre_name} モデル{i:02d}",
        price=price,
        url="https://www.rakuten.co.jp/",
        image=_PLACEHOLDER,
        shop="サンプルショップ",
        caption=f"これはデモ用のダミー商品です。実際の運用では楽天{genre_name}カテゴリの実データが入ります。",
        review_average=round(rng.uniform(3.8, 4.9), 2),
        review_count=rng.randint(12, 4200),
        item_code=f"demo:{genre_name}:{i}",
    )


def build_demo_articles(cfg: dict) -> list[Article]:
    rng = random.Random(42)  # 実行のたびに中身が変わるとレイアウト比較しづらいので固定
    n = cfg["generation"]["items_per_article"]
    articles: list[Article] = []

    for genre in cfg["genres"]:
        for angle in cfg["angles"]:
            fmt = {"genre": genre["name"], "n": n}
            articles.append(
                Article(
                    slug=f"{genre['slug']}-{angle['slug']}",
                    title=angle["title"].format(**fmt),
                    lead=angle["lead"].format(**fmt),
                    genre_name=genre["name"],
                    genre_slug=genre["slug"],
                    products=[_product(genre["name"], i + 1, rng) for i in range(n)],
                )
            )
    return articles

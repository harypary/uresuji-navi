"""設定(genres × angles)から記事データを組み立てる。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from .curate import fill
from .rakuten import Product, RakutenAPIError, RakutenClient

log = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))


@dataclass
class Article:
    slug: str
    title: str
    lead: str
    genre_name: str
    genre_slug: str
    products: list[Product]
    updated_at: datetime = field(default_factory=lambda: datetime.now(JST))

    @property
    def url_path(self) -> str:
        return f"articles/{self.slug}/"

    @property
    def description(self) -> str:
        names = "、".join(p.name.split()[0][:14] for p in self.products[:3])
        return f"{self.title}。{names}など、楽天市場の売れ筋データから厳選。{self.updated_at:%Y年%m月%d日}更新。"

    @property
    def hero_image(self) -> str:
        return self.products[0].image if self.products else ""


def _collect(client: RakutenClient, genre: dict, angle: dict, cfg: dict) -> list[Product]:
    """1記事分の商品候補をAPIから集める。"""
    gen = cfg["generation"]

    if angle["source"] == "ranking":
        return client.ranking(
            genre["genre_id"],
            period=gen["ranking_period"],
            expect_name=genre["name"],
        )

    # search: ジャンルに紐づくキーワードを順に叩いて候補プールを作る
    pool: list[Product] = []
    for keyword in genre.get("keywords") or [genre["name"]]:
        pool.extend(
            client.search(
                keyword,
                genre_id=genre["genre_id"],
                sort=angle.get("sort"),
                hits=30,
                min_price=angle.get("min_price"),
            )
        )
    return pool


def build_articles(client: RakutenClient, cfg: dict) -> list[Article]:
    """設定に書かれた全ジャンル × 全アングルの記事を生成する。"""
    gen = cfg["generation"]
    n = gen["items_per_article"]
    articles: list[Article] = []

    for genre in cfg["genres"]:
        for angle in cfg["angles"]:
            slug = f"{genre['slug']}-{angle['slug']}"
            try:
                pool = _collect(client, genre, angle, cfg)
            except RakutenAPIError as e:
                # 1ジャンルのAPIエラーで全体を落とさない。他の記事は生成を続ける
                log.error("取得失敗 %s: %s", slug, e)
                continue

            products = fill(
                pool,
                commission_rate=genre["commission_rate"],
                limit=n,
                min_review_count=gen["min_review_count"],
            )

            if len(products) < 3:
                log.warning("商品が %d 件しか無いため %s をスキップ", len(products), slug)
                continue

            fmt = {"genre": genre["name"], "n": len(products)}
            articles.append(
                Article(
                    slug=slug,
                    title=angle["title"].format(**fmt),
                    lead=angle["lead"].format(**fmt),
                    genre_name=genre["name"],
                    genre_slug=genre["slug"],
                    products=products,
                )
            )
            log.info("生成 %s (%d商品)", slug, len(products))

    return articles

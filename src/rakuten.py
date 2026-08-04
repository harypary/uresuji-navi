"""楽天ウェブサービス(商品検索API / ランキングAPI)の薄いクライアント。

affiliateId をリクエストに載せると、レスポンスの affiliateUrl に
アフィリエイトリンクが入って返ってくる。自前でリンクを組み立てるより
確実なので、成果リンクは必ずこの affiliateUrl を使う。

2026年のインフラ刷新でエンドポイントと認証が変わっている:
  - 旧 app.rakuten.co.jp/services/api/... は 2026-05-13 に停止済み
  - 新 openapi.rakuten.co.jp 配下。APIごとにパスの第1階層が異なる
  - 認証は applicationId(UUID) と accessKey の2点セットが必須
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)

# バージョンはAPIごとに異なる。管理画面ではなく公式ドキュメントの記載に合わせること。
# https://webservice.rakuten.co.jp/documentation
SEARCH_URL = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"
RANKING_URL = "https://openapi.rakuten.co.jp/ichibaranking/api/IchibaItem/Ranking/20220601"
GENRE_URL = "https://openapi.rakuten.co.jp/ichibagt/api/IchibaGenre/Search/20260701"


class RakutenAPIError(RuntimeError):
    pass


@dataclass
class Product:
    """記事テンプレートが必要とする分だけに削ぎ落とした商品。"""

    name: str
    price: int
    url: str  # アフィリエイトリンク(affiliateUrl。無ければ生URLにフォールバック)
    image: str
    shop: str
    caption: str
    review_average: float
    review_count: int
    item_code: str
    # 商品ごとの実際のアフィリエイト料率(%)。APIが返すのでジャンル単位の推定値より正確。
    # 0 の場合は設定ファイルの commission_rate にフォールバックする
    affiliate_rate: float = 0.0

    @property
    def price_display(self) -> str:
        return f"{self.price:,}円"

    @property
    def short_caption(self) -> str:
        """カードに載せる用の短い説明。楽天のitemCaptionは改行と煽り文が多いので整える。"""
        text = " ".join(self.caption.split())
        return text[:120] + "…" if len(text) > 120 else text


def _to_product(raw: dict) -> Product | None:
    """APIの生アイテムを Product に変換する。想定外の形なら None。"""
    # 検索APIは {"Item": {...}}、ランキングAPIも同形だが将来の差異に備えて剥がす
    item = raw.get("Item", raw)

    name = item.get("itemName")
    url = item.get("affiliateUrl") or item.get("itemUrl")
    if not name or not url:
        return None

    images = item.get("mediumImageUrls") or []
    if images and isinstance(images[0], dict):
        image = images[0].get("imageUrl", "")
    elif images:
        image = images[0]
    else:
        image = ""
    # 楽天の画像URLは末尾の _ex= でサイズが決まる。カード表示用に大きめを指定
    image = image.replace("?_ex=128x128", "?_ex=300x300")

    return Product(
        name=name,
        price=int(item.get("itemPrice") or 0),
        url=url,
        image=image,
        shop=item.get("shopName", ""),
        caption=item.get("itemCaption", ""),
        review_average=float(item.get("reviewAverage") or 0),
        review_count=int(item.get("reviewCount") or 0),
        item_code=item.get("itemCode", ""),
        affiliate_rate=float(item.get("affiliateRate") or 0),
    )


class RakutenClient:
    def __init__(
        self,
        application_id: str,
        access_key: str,
        affiliate_id: str | None = None,
        interval_sec: float = 1.2,
    ):
        if not application_id:
            raise RakutenAPIError(
                "RAKUTEN_APPLICATION_ID が未設定です。.env を確認してください。"
            )
        if not access_key:
            # 2026年の刷新以降、applicationId 単体では認証が通らない
            raise RakutenAPIError(
                "RAKUTEN_ACCESS_KEY が未設定です。管理画面の「アクセスキー」を .env に設定してください。"
            )
        self.application_id = application_id
        self.access_key = access_key
        self.affiliate_id = affiliate_id
        self.interval_sec = interval_sec
        self._last_call = 0.0
        self._session = requests.Session()

    def _throttle(self) -> None:
        """楽天APIは1req/sec目安。超えると429で締め出されるので必ず間隔を空ける。"""
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.interval_sec:
            time.sleep(self.interval_sec - elapsed)
        self._last_call = time.monotonic()

    def _get(self, url: str, params: dict) -> dict:
        params = {k: v for k, v in params.items() if v is not None}
        params["applicationId"] = self.application_id
        params["accessKey"] = self.access_key
        params["format"] = "json"
        if self.affiliate_id:
            params["affiliateId"] = self.affiliate_id

        for attempt in range(4):
            self._throttle()
            resp = self._session.get(url, params=params, timeout=20)

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code == 429 or resp.status_code >= 500:
                wait = 2 ** attempt * 2
                log.warning(
                    "楽天API %s (attempt %d/4) — %d秒待って再試行",
                    resp.status_code, attempt + 1, wait,
                )
                time.sleep(wait)
                continue

            # 400番台はパラメータ不正。リトライしても直らないので即座に上げる
            raise RakutenAPIError(f"{resp.status_code}: {resp.text[:300]}")

        raise RakutenAPIError(f"リトライ上限に到達しました: {url}")

    def ranking(
        self, genre_id: int, period: str = "realtime", expect_name: str | None = None
    ) -> list[Product]:
        """ジャンル内の売上ランキング。既に売れている＝CVRが高い商品が並ぶ。

        expect_name を渡すと、レスポンスの title と突き合わせて設定ミスを検知する。
        ジャンルIDを1桁間違えても正常に200が返るため（例: 化粧品のつもりが
        バッグのIDだった）、ここで気づけないと的外れな記事が黙って量産される。
        title は元から返ってくるので追加のAPIコールは発生しない。
        """
        data = self._get(RANKING_URL, {"genreId": genre_id, "period": period})

        title = data.get("title", "")
        if expect_name and title and expect_name not in title:
            log.warning(
                "ジャンルID %s は '%s' の想定だが、楽天の返答は '%s'。"
                " config/site.yaml の genre_id を確認してください",
                genre_id, expect_name, title,
            )

        return [p for p in map(_to_product, data.get("Items", [])) if p]

    def search(
        self,
        keyword: str,
        genre_id: int | None = None,
        sort: str | None = None,
        hits: int = 30,
        min_price: int | None = None,
    ) -> list[Product]:
        """キーワード検索。sort は '-reviewCount' / '+itemPrice' / '-itemPrice' など。"""
        data = self._get(
            SEARCH_URL,
            {
                "keyword": keyword,
                "genreId": genre_id,
                "sort": sort,
                "hits": min(hits, 30),  # APIの上限が30
                "minPrice": min_price,
                "imageFlag": 1,  # 画像が無い商品はカードが崩れるので最初から除外
            },
        )
        return [p for p in map(_to_product, data.get("Items", [])) if p]

    def find_genres(self, genre_id: int = 0) -> list[dict]:
        """ジャンルIDを調べる用。0(ルート)から辿って目的のジャンルを探す。"""
        # 20260701 版から children の形が変わり、child でラップされなくなった
        data = self._get(GENRE_URL, {"genreId": genre_id})
        return [
            {"id": c["genreId"], "name": c.get("nameJa") or c.get("genreName", "")}
            for c in data.get("children", [])
        ]

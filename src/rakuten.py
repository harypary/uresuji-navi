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

# 「過去最安」と表示するのに最低限必要な観測日数。
# 2日目に「過去最安！」と出しても嘘くさいだけなので、1週間は溜める
MIN_DAYS_FOR_LOWEST = 7


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

    # ポイント倍率。楽天は表示価格をほとんど動かさず、ここで実質価格を動かす。
    # 通常1倍(=購入額の1%還元)で、キャンペーン中は5倍・10倍になる
    point_rate: int = 1

    # --- ここから下は price_history.py が書き込む。APIからは取れない情報 ---
    prev_price: int = 0        # 前回観測時の価格(0なら比較対象なし)
    lowest_price: int = 0      # 観測期間中の最安値
    days_tracked: int = 0      # 観測日数
    distinct_prices: int = 0   # 観測期間中に現れた価格の種類数
    prev_point_rate: int = 0   # 前回観測時のポイント倍率
    base_point_rate: int = 0   # 観測期間中の最低倍率(=キャンペーンのない平常時の値)

    @property
    def price_drop(self) -> int:
        """前回観測比の値下がり額。値上がり・比較不能なら0。"""
        if not self.prev_price:
            return 0
        return max(self.prev_price - self.price, 0)

    @property
    def price_drop_display(self) -> str:
        return f"{self.price_drop:,}円"

    @property
    def is_lowest(self) -> bool:
        """観測期間中の最安値かどうか。

        観測日数が浅いうちは「最安」に意味が無いので出さない。
        さらに一度も値動きしていない商品を「最安」と呼ぶのは誤解を招くため、
        価格が2種類以上観測できている商品に限る。実測では楽天の表示価格は
        ほとんど動かず、この条件が無いと全商品に最安バッジが付いてしまう。
        """
        return (
            self.days_tracked >= MIN_DAYS_FOR_LOWEST
            and self.distinct_prices >= 2
            and self.lowest_price > 0
            and self.price <= self.lowest_price
        )

    @property
    def has_point_campaign(self) -> bool:
        return self.point_rate >= 2

    @property
    def point_back(self) -> int:
        """ポイント還元額の目安。倍率10倍=購入額の10%相当。"""
        return self.price * self.point_rate // 100

    @property
    def effective_price_display(self) -> str:
        return f"{self.price - self.point_back:,}円"

    @property
    def point_rate_up(self) -> bool:
        """平常時より倍率が上がっているか(=キャンペーン期間中か)。

        前日比で判定すると、倍率が上がったその1日しかバッジが出ず、
        キャンペーンが続いている間ずっと無表示になる。実測でも
        「08-21に1倍→10倍、08-22も10倍」で2日目に消えてしまった。
        そのため観測期間中の最低倍率(平常時)と比較する。
        """
        return bool(self.base_point_rate) and self.point_rate > self.base_point_rate

    @property
    def price_display(self) -> str:
        return f"{self.price:,}円"

    @property
    def short_caption(self) -> str:
        """カードに載せる用の短い説明。楽天のitemCaptionは改行と煽り文が多いので整える。"""
        text = " ".join(self.caption.split())
        return text[:120] + "…" if len(text) > 120 else text


def _is_safe_url(url: str) -> bool:
    """href/src に出して安全なURLか。

    HTMLエスケープはスキームを検証しないため、`javascript:alert(1)` のような値は
    エスケープを通り抜けてそのまま href に載る。APIレスポンスは外部入力なので、
    http/https 以外は受け付けない。
    """
    return url.lower().startswith(("https://", "http://"))


def _to_product(raw: dict) -> Product | None:
    """APIの生アイテムを Product に変換する。想定外の形なら None。"""
    # 検索APIは {"Item": {...}}、ランキングAPIも同形だが将来の差異に備えて剥がす
    item = raw.get("Item", raw)

    name = item.get("itemName")
    url = item.get("affiliateUrl") or item.get("itemUrl")
    if not name or not url or not _is_safe_url(url):
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
    if image and not _is_safe_url(image):
        image = ""  # 画像は無くても記事は成立するので、URLを捨てるだけにする

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
        point_rate=int(item.get("pointRate") or 1),
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

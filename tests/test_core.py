"""ネットワークに出ずに回せる、パイプライン中核部分のテスト。

CI(PRチェック)で実行する。楽天APIは叩かないので Secret 不要。
これまで開発中に都度手で流していた検証を、壊れたら気づけるよう固定したもの。

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from datetime import date, timedelta

import yaml

from src.articles import Article
from src.curate import curate, fill
from src.price_history import load, save, update
from src.rakuten import MIN_DAYS_FOR_LOWEST, Product, _is_safe_url, _to_product
from src.render import render_site

ROOT = pathlib.Path(__file__).resolve().parent.parent
D0 = date(2026, 1, 1)


def mk(code="A", price=10000, avg=4.5, cnt=100, rate=1, name=None,
       url="https://item.rakuten.co.jp/x/", image="https://i/x.png"):
    p = Product(name or f"商品{code}", price, url, image, "shop", "cap", avg, cnt, code)
    p.point_rate = rate
    return p


def art(products, slug="t", genre_slug="kaden-kitchen"):
    return Article(slug, "タイトル", "lead", "キッチン家電", genre_slug, products)


class TestCurate(unittest.TestCase):
    def test_同一商品の重複出品をまとめる(self):
        pool = [mk("a", name="【送料無料】人気の電気ケトル 1.0L"),
                mk("b", name="人気の電気ケトル 1.0L あす楽")]
        self.assertEqual(len(curate(pool, 2.0, 10)), 1)

    def test_低評価_レビューなし_価格範囲外を除外する(self):
        pool = [mk("ok"), mk("low", avg=2.5, cnt=50), mk("none", avg=0, cnt=0),
                mk("cheap", price=100), mk("pricey", price=480_000)]
        self.assertEqual([p.item_code for p in curate(pool, 2.0, 10)], ["ok"])

    def test_件数を緩めても低評価は入れない(self):
        pool = [mk("none", avg=0, cnt=0), mk("low", avg=2.5, cnt=4)]
        codes = [p.item_code for p in fill(pool, 2.0, 10, min_review_count=3)]
        self.assertIn("none", codes)
        self.assertNotIn("low", codes)


class TestUrlSafety(unittest.TestCase):
    def test_http_https以外のスキームを拒否する(self):
        for bad in ["javascript:alert(1)", "JavaScript:x", "data:text/html,x", "vbscript:x", "//evil.com"]:
            self.assertFalse(_is_safe_url(bad), bad)
        self.assertTrue(_is_safe_url("https://item.rakuten.co.jp/a/"))

    def test_危険なリンクの商品は捨て_危険な画像は画像だけ捨てる(self):
        self.assertIsNone(_to_product({"itemName": "x", "affiliateUrl": "javascript:alert(1)"}))
        p = _to_product({"itemName": "x", "affiliateUrl": "https://item.rakuten.co.jp/a/",
                         "mediumImageUrls": [{"imageUrl": "javascript:alert(1)"}]})
        self.assertIsNotNone(p)
        self.assertEqual(p.image, "")

    def test_ポイント倍率を読み取る(self):
        p = _to_product({"itemName": "x", "affiliateUrl": "https://a/", "pointRate": 10})
        self.assertEqual(p.point_rate, 10)


class TestPriceHistory(unittest.TestCase):
    def run_days(self, seq, code="A"):
        """(価格, 倍率) の列を1日ずつ記録し、最終日の商品を返す。"""
        store = {}
        for i, (price, rate) in enumerate(seq):
            p = mk(code, price=price, rate=rate)
            update([art([p])], store, D0 + timedelta(days=i))
        return p

    def test_初日は比較しない(self):
        p = self.run_days([(10000, 1)])
        self.assertEqual(p.price_drop, 0)
        self.assertFalse(p.is_lowest)

    def test_値下がりを検出し値上がりは0にする(self):
        self.assertEqual(self.run_days([(10000, 1), (9200, 1)]).price_drop, 800)
        self.assertEqual(self.run_days([(10000, 1), (12000, 1)]).price_drop, 0)

    def test_価格が一度も動かない商品に最安を付けない(self):
        self.assertFalse(self.run_days([(5000, 1)] * 12).is_lowest)

    def test_観測日数が足りれば値動きのある商品に最安を付ける(self):
        seq = [(5000, 1)] * MIN_DAYS_FOR_LOWEST + [(4500, 1)]
        self.assertTrue(self.run_days(seq).is_lowest)

    def test_キャンペーン中はずっと平常時比でUPを出す(self):
        p = self.run_days([(20000, 1), (20000, 1), (20000, 10), (20000, 10), (20000, 10)])
        self.assertTrue(p.point_rate_up)
        self.assertEqual(p.base_point_rate, 1)
        self.assertEqual(p.effective_price_display, "18,000円")

    def test_常時高倍率の商品にはUPを出さない(self):
        p = self.run_days([(20000, 10)] * 4)
        self.assertFalse(p.point_rate_up)
        self.assertTrue(p.has_point_campaign)

    def test_同日に2回実行しても履歴が増えない(self):
        store = {}
        update([art([mk(price=10000)])], store, D0)
        update([art([mk(price=11000)])], store, D0)
        self.assertEqual(len(store["A"]["h"]), 1)
        self.assertEqual(store["A"]["h"][0]["p"], 11000)

    def test_長く掲載されない商品を捨てる(self):
        store = {}
        update([art([mk("B")])], store, D0)
        update([art([mk("A")])], store, D0 + timedelta(days=60))
        self.assertNotIn("B", store)

    def test_倍率キーの無い古い履歴を読める(self):
        store = {"A": {"h": [{"d": "2025-12-31", "p": 10000}]}}
        p = mk(price=9500, rate=10)
        update([art([p])], store, D0)
        self.assertEqual(p.prev_point_rate, 0)
        self.assertEqual(p.price_drop, 500)

    def test_壊れた履歴ファイルは空から作り直す(self):
        f = pathlib.Path(tempfile.mkdtemp()) / "h.json"
        save(f, {"A": {"h": []}})
        self.assertEqual(load(f), {"A": {"h": []}})
        f.write_text("{壊れたJSON", encoding="utf-8")
        with self.assertLogs("src.price_history", level="WARNING"):
            self.assertEqual(load(f), {})


class TestRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = yaml.safe_load((ROOT / "config" / "site.yaml").read_text(encoding="utf-8"))

    def render(self, products, **kw):
        out = pathlib.Path(tempfile.mkdtemp()) / "docs"
        render_site([art(products)], self.cfg, "https://example.com", out, **kw)
        return out, (out / "articles" / "t" / "index.html").read_text(encoding="utf-8")

    def test_APIデータ由来のXSSをエスケープする(self):
        evil = mk(name='<script>alert(1)</script>" onmouseover="alert(2)')
        evil.caption = "</script><script>alert(5)</script>"
        _, html = self.render([evil] * 3)
        self.assertNotIn("<script>alert(1)", html)
        self.assertNotIn('" onmouseover="alert(2)', html)
        self.assertNotIn("</script><script>alert(5)", html)

    def test_バッジは条件を満たす商品にだけ出る(self):
        drop = mk("drop", price=9200)
        drop.prev_price, drop.lowest_price, drop.days_tracked, drop.distinct_prices = 10000, 9200, 3, 2
        new = mk("new", price=5000)
        camp = mk("camp", price=20000, rate=10)
        camp.base_point_rate = 1
        _, html = self.render([drop, new, camp])
        self.assertIn("▼ 800円値下がり", html)
        self.assertIn("通常1倍→ポイント10倍", html)
        self.assertIn("実質 <strong>18,000円</strong>", html)
        self.assertEqual(html.count("badge-drop"), 1)

    def test_法定表示とセキュリティ設定が入る(self):
        _, html = self.render([mk()])
        self.assertIn("プロモーションを含みます", html)
        self.assertIn("Supported by", html)
        self.assertIn('http-equiv="Content-Security-Policy"', html)
        self.assertNotIn("frame-ancestors", html)
        self.assertIn('rel="nofollow sponsored noopener"', html)

    def test_機械向けファイルを出力する(self):
        out, _ = self.render([mk()], google_site_verification="TOKEN")
        for name in ["sitemap.xml", "sitemap_index.xml", "feed.xml", "robots.txt", ".nojekyll"]:
            self.assertTrue((out / name).exists(), name)
        self.assertIn("sitemap_index.xml", (out / "robots.txt").read_text(encoding="utf-8"))
        self.assertIn('content="TOKEN"', (out / "index.html").read_text(encoding="utf-8"))

    def test_構造化データがJSONとして読める(self):
        _, html = self.render([mk(name='引用符"と<タグ>を含む商品')])
        block = html.split('<script type="application/ld+json">', 1)[1].split("</script>", 1)[0]
        data = json.loads(block)
        self.assertEqual(data["@type"], "ItemList")
        self.assertEqual(data["itemListElement"][0]["item"]["name"], '引用符"と<タグ>を含む商品')


if __name__ == "__main__":
    unittest.main()

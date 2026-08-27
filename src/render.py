"""記事データを静的サイト(docs/)として書き出す。

出力先を docs/ にしているのは、GitHub Pages の
「Deploy from a branch → /docs」設定でそのまま公開できるため。
"""

from __future__ import annotations

import logging
import shutil
import zlib
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .articles import JST, Article

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(ROOT / "templates"),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _related(article: Article, articles: list[Article], limit: int = 5) -> list[Article]:
    """内部リンク用。同ジャンルを優先し、足りなければ他ジャンルで埋める。

    内部リンクはクローラの巡回とセッションあたりのPVを増やすので、
    どの記事も必ず数本の被リンクを持つようにしておく。
    """
    same = [a for a in articles if a.genre_slug == article.genre_slug and a.slug != article.slug]
    other = [a for a in articles if a.genre_slug != article.genre_slug]

    # 他ジャンルは記事ごとに開始位置をずらし、被リンクが特定記事に偏らないようにする。
    # 組み込み hash() はプロセスごとに値が変わり毎回リンクが入れ替わるので crc32 を使う
    offset = zlib.crc32(article.slug.encode()) % max(len(other), 1)
    rotated = other[offset:] + other[:offset]

    return (same + rotated)[:limit]


def render_site(
    articles: list[Article],
    cfg: dict,
    base_url: str,
    out_dir: Path,
    google_site_verification: str = "",
) -> None:
    env = _env()
    site = cfg["site"]
    now = datetime.now(JST)
    base_url = base_url.rstrip("/")

    ctx = {
        "site": site,
        "base_url": base_url,
        "now": now,
        "google_site_verification": google_site_verification,
    }

    # 出力先をまっさらにする。設定から外したジャンルの記事を残さないため。
    # docs/ 配下は毎回生成物で埋め直すので、手書きファイルは置かないこと。
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    # ---- トップページ(ジャンル順を site.yaml の並びに揃える) ----
    grouped: OrderedDict[str, list[Article]] = OrderedDict()
    for genre in cfg["genres"]:
        group = [a for a in articles if a.genre_slug == genre["slug"]]
        if group:
            grouped[genre["name"]] = group

    _write(
        out_dir / "index.html",
        env.get_template("index.html").render(
            **ctx, root="", grouped=list(grouped.items()), articles=articles
        ),
    )

    # ---- 記事ページ ----
    article_tpl = env.get_template("article.html")
    for article in articles:
        _write(
            out_dir / "articles" / article.slug / "index.html",
            article_tpl.render(
                **ctx,
                root="../../",  # docs/articles/<slug>/index.html からの相対
                article=article,
                related=_related(article, articles),
            ),
        )

    # ---- 固定ページ・機械向けファイル ----
    _write(
        out_dir / "privacy" / "index.html",
        env.get_template("privacy.html").render(**ctx, root="../"),
    )
    for name in ("sitemap.xml", "sitemap_index.xml", "feed.xml", "robots.txt"):
        _write(out_dir / name, env.get_template(name).render(**ctx, articles=articles))

    # ---- 静的アセット ----
    shutil.copytree(ROOT / "static", out_dir / "assets")

    # ---- サイトルート直下に置くファイル ----
    # Search Console の所有権確認ファイル(google*.html)や ads.txt など、
    # 「必ずルート直下でなければならない」ものをここに入れる。
    # docs/ は毎回作り直すので、生成物ではないファイルはこちらで管理する。
    site_root = ROOT / "site_root"
    if site_root.is_dir():
        for item in site_root.iterdir():
            if item.name.startswith(".") or not item.is_file():
                continue
            shutil.copy2(item, out_dir / item.name)
            log.info("ルート直下に配置: %s", item.name)

    # Jekyll のビルドを止める。無いと _ 始まりのパスが404になることがある
    (out_dir / ".nojekyll").touch()

    log.info("出力完了: %s (記事%d本)", out_dir, len(articles))

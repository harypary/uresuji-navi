"""楽天アフィリエイトサイトの自動生成パイプライン。

    python main.py --demo     # APIキー不要。ダミーデータで見た目を確認
    python main.py            # 楽天APIから実データを取得してサイトを再生成
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.articles import build_articles
from src.demo import build_demo_articles
from src.rakuten import RakutenAPIError, RakutenClient
from src.render import render_site

ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="楽天アフィリエイトサイト自動生成")
    p.add_argument("--config", default=ROOT / "config" / "site.yaml", type=Path)
    p.add_argument("--out", default=ROOT / "docs", type=Path)
    p.add_argument("--base-url", default=None, help="未指定なら .env の SITE_BASE_URL")
    p.add_argument("--demo", action="store_true", help="楽天APIを叩かずダミーデータで生成")
    return p.parse_args()


def main() -> int:
    # Windowsのコンソールは既定がcp932で、日本語ログや記号でUnicodeEncodeErrorになる
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    load_dotenv()
    args = parse_args()

    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    base_url = args.base_url or os.getenv("SITE_BASE_URL", "http://localhost:8000")

    if args.demo:
        logging.warning("デモモード: ダミーデータで生成します（成果リンクは含まれません）")
        articles = build_demo_articles(cfg)
    else:
        affiliate_id = os.getenv("RAKUTEN_AFFILIATE_ID", "")
        if not affiliate_id:
            # ここを見落とすと「動いているのに1円も入らないサイト」が出来上がる
            logging.error(
                "RAKUTEN_AFFILIATE_ID が未設定です。このまま生成しても成果は発生しません。"
                " .env を設定するか、見た目の確認だけなら --demo を使ってください。"
            )
            return 1

        try:
            client = RakutenClient(
                application_id=os.getenv("RAKUTEN_APPLICATION_ID", ""),
                access_key=os.getenv("RAKUTEN_ACCESS_KEY", ""),
                affiliate_id=affiliate_id,
                interval_sec=cfg["generation"]["request_interval_sec"],
            )
            articles = build_articles(client, cfg)
        except RakutenAPIError as e:
            logging.error("楽天API: %s", e)
            return 1

    if not articles:
        logging.error("記事が1本も生成できませんでした。config/site.yaml を確認してください。")
        return 1

    render_site(articles, cfg, base_url, args.out)
    print(f"\n✅ {len(articles)}本の記事を {args.out} に生成しました")
    print(f"   ローカル確認: python -m http.server -d {args.out} 8000")
    return 0


if __name__ == "__main__":
    sys.exit(main())

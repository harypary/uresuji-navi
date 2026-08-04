"""楽天のジャンルIDを調べるCLI。config/site.yaml の genre_id を埋めるのに使う。

    python -m src.genres            # ルート直下の大ジャンル一覧
    python -m src.genres 100026     # そのジャンルの子ジャンル一覧
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

from .rakuten import RakutenClient


def main() -> int:
    load_dotenv()
    genre_id = int(sys.argv[1]) if len(sys.argv) > 1 else 0

    client = RakutenClient(
        os.getenv("RAKUTEN_APPLICATION_ID", ""),
        os.getenv("RAKUTEN_ACCESS_KEY", ""),
    )
    children = client.find_genres(genre_id)

    if not children:
        print(f"ジャンル {genre_id} に子ジャンルはありません（末端ジャンルです）")
        return 0

    print(f"--- ジャンル {genre_id} の子ジャンル ---")
    for child in children:
        print(f"{child['id']:>10}  {child['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

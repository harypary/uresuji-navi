# 楽天アフィリエイト 自動収益サイト

楽天ウェブサービスから売れ筋データを取得 → 期待報酬順に商品を選定 → 記事HTMLを生成 →
GitHub Pages へ自動デプロイ。**毎朝6時に全自動で更新される**アフィリエイトサイトです。

サーバー代・API利用料・記事生成コストはすべて0円。動かし続ける限りランニングコストは発生しません。

---

## 1. 儲かる仕組み

### 収益の計算式

```
月間報酬 =  PV × クリック率 × 購入率 × 平均単価 × 料率
```

このシステムは、右の4項目それぞれに具体的な打ち手を仕込んでいます。

| 要素 | 実装している打ち手 | 該当ファイル |
|---|---|---|
| PV | ジャンル×切り口で記事を自動量産 + 毎日更新 + sitemap/RSS | [config/site.yaml](config/site.yaml), [templates/sitemap.xml](templates/sitemap.xml) |
| クリック率 | ランキング形式・大きなCTAボタン・1記事に10個のリンク | [templates/article.html](templates/article.html), [static/style.css](static/style.css) |
| 購入率 | 「すでに売れている商品」「高評価の商品」だけを掲載 | [src/curate.py](src/curate.py) |
| 単価×料率 | 期待報酬額でスコアリングして掲載順を決定 | [src/curate.py:39](src/curate.py:39) |
| 独自価値 | 価格とポイント倍率を毎日記録し、実質価格・値下がりを表示 | [src/price_history.py](src/price_history.py) |

### 価格履歴とポイント倍率が唯一の差別化要素

商品情報を並べただけのページは、楽天市場で直接見られる情報と大差がありません。
Googleは独自価値の薄い自動生成ページを明確に低評価するため、**ページ数を増やす戦略には上限があります**。

このシステムが楽天そのものに対して持てる優位は「時間」だけです。毎日データを取っているので、
単発のAPIレスポンスからは絶対に作れない情報を出せます。

**実測でわかったこと（2026-08-13〜19 の6日間）**

| 指標 | 結果 |
|---|---|
| 表示価格が動いた商品 | 174商品中 **1商品（0.6%）**、しかも20円差 |
| ポイント倍率が2倍以上 | 90商品中 **17商品（19%）**、**全件が期間限定** |

**楽天は表示価格をほとんど動かさず、ポイント倍率で実質価格を動かしています。**
そのため価格だけを追っても差別化になりません。両方を記録し、表示の主役は倍率側に置いています。

- `通常1倍→ポイント20倍` — 平常時の倍率と現在の倍率。キャンペーン期間中ずっと表示される
- `ポイント還元を含めた実質 17,820円` — 楽天の商品ページでは自分で計算しないと分からない
- `▼ 800円値下がり` — 前回観測比
- `過去30日で最安` — 7日以上観測し、**かつ価格が2種類以上**観測できた商品のみ

最後の条件が重要です。楽天の価格はほとんど動かないため、これが無いと
「一度も値動きしていない商品」すべてに最安バッジが付いてしまいます。

**倍率の比較は前日比ではなく「観測期間中の最低倍率」に対して行います。**
前日比だと倍率が上がったその1日しかバッジが出ず、キャンペーンが続いている間は
無表示になってしまうためです（実測で `08-21に1倍→10倍、08-22も10倍` の
2日目に消える事象を確認）。

履歴は `data/price_history.json` に90日分保持し、GitHub Actions が
リポジトリへ書き戻して永続化します（CIは実行ごとに環境が消えるため）。
30日間掲載されなかった商品は履歴ごと破棄してファイルの肥大を防いでいます。

---

## 2. システム構成

```
main.py                  パイプライン全体の入口
├── src/rakuten.py       楽天API クライアント(レート制限・リトライ込み)
├── src/curate.py        ★収益の中核: 期待報酬スコアで商品を選定・重複排除
├── src/articles.py      ジャンル × 切り口 で記事データを組み立て
├── src/render.py        Jinja2 で docs/ に静的サイトを書き出し
├── src/demo.py          APIキー無しで見た目を確認するダミーデータ
├── src/genres.py        楽天ジャンルIDを調べるCLI
├── config/site.yaml     ★運用で触るのはここ: ジャンル・切り口・掲載件数
├── templates/           HTML / sitemap.xml / feed.xml / robots.txt
├── static/style.css     デザイン(CTAボタンの見た目 = クリック率)
└── docs/                生成物。GitHub Pages の公開ディレクトリ
```

現在の設定で **6ジャンル × 3切り口 = 18記事** が毎日生成されます。
`config/site.yaml` にジャンルを1つ足すだけで3記事増えます。

---

## 3. セットアップ

**手作業が必要なのは 3-1 だけです。** 楽天のID取得はログイン・利用規約への同意・
報酬振込先の設定を伴うため、本人が行う必要があり自動化できません。
IDさえ手に入れば、以降は `.\setup.ps1` 一発で公開まで終わります。

### 3-1. 楽天の認証情報を取得する（10分・ここだけ手作業）

**① アプリを申請する**

1. https://webservice.rakuten.co.jp/ に楽天会員でログイン
2. 「新規申請登録」から以下の内容で申請する
3. ステータスが「アクティブ」になるのを待つ

| 項目 | 値 |
|---|---|
| 申請名 | 売れ筋ナビ |
| アプリケーションURL | `https://<ユーザー名>.github.io/uresuji-navi` |
| 申請タイプ | **API/バックエンドサービス**（ブラウザではなくCI上から叩くため） |
| APIアクセススコープ | **楽天市場API のみ**（トラベル/ブックス/GORA/Kobo/Recipe は不要） |
| 許可されたIPアドレス | `0.0.0.0/0` |
| 期待されるQPS | `1` |

> **「許可されたIPアドレス」の注意**: この欄はドメイン名もURLも受け付けません。
> GitHub Actions のランナーは Azure の約4000件のCIDRからIPが毎回変わり固定できないため、
> `0.0.0.0/0` を指定します（バリデーション通過を確認済み）。

**データの目的・使用**（申請フォームの記入例）:

```
取得した商品情報（商品名・価格・画像・レビュー評価）を、カテゴリ別ランキング記事として
表示する目的でのみ使用します。情報の保存は静的HTMLの生成時に限り、
データベースへの蓄積や再配布は行いません。
```

**② 管理画面から3つの値を控える**

申請が「アクティブ」になると、アプリの詳細画面に以下が表示されます。
**この3つすべてが必要**です。

| 画面の表示 | `.env` のキー | 形式 |
|---|---|---|
| アプリケーションID | `RAKUTEN_APPLICATION_ID` | UUID（`0f6d4c40-....`） |
| **アクセスキー**（伏字） | `RAKUTEN_ACCESS_KEY` | 46文字のトークン |
| アフィリエイトID | `RAKUTEN_AFFILIATE_ID` | `xxxxxxxx.xxxxxxxx.xxxxxxxx.xxxxxxxx` |

> ⚠️ **2026年のインフラ刷新で認証方式が変わりました。**
> 以前の「19桁の数字1つ（applicationId）」ではなく、
> **applicationId と accessKey の2点セット**が必須です。
> 片方だけだと `400 {"error":"wrong_parameter"}` で弾かれます。

> ⚠️ アフィリエイトIDが未設定だと `affiliateUrl` が**空で返り、成果が1円も付きません**。
> `main.py` は未設定のとき起動を止めるようにしてあります。

### 3-2. ローカルで動かす

```powershell
pip install -r requirements.txt

# APIキー無しで見た目だけ確認
python main.py --demo
python -m http.server -d docs 8000     # → http://localhost:8000

# 本番データで生成
copy .env.example .env                  # .env に取得した3つの値を記入
python main.py
```

ジャンルIDを調べたいとき:

```powershell
python -m src.genres          # 大ジャンル一覧
python -m src.genres 100939   # そのジャンルの子ジャンル一覧
```

### 3-3. GitHub Pages で自動運用する（1コマンド）

`.env` に3つの値を記入したら、あとは全自動です。

```powershell
.\setup.ps1 -RepoName uresuji-navi
```

`-RepoName` はそのまま公開URLになります。楽天の商標に類似する名前
（`rakuten` を含むもの）はスクリプトが検査して停止します。

[setup.ps1](setup.ps1) が以下をまとめて実行します。

1. `.env` の検証（サンプル値のままなら停止）
2. 楽天APIで実際に記事を生成し、**IDが有効かを確認**
3. `git init` → commit → GitHubリポジトリ作成 → push
4. Secrets / Variables を `.env` から自動登録
5. GitHub Pages を「GitHub Actions」ソースで有効化
6. 初回デプロイを起動

事前に GitHub CLI の認証だけ済ませておいてください（`gh auth login`）。

以降は毎朝6時(JST)に [.github/workflows/daily.yml](.github/workflows/daily.yml) が
自動で回り、サイトが更新され続けます。手動で回したいときは `gh workflow run daily.yml`。

> **手動で設定したい場合**: Settings → Secrets and variables → Actions で
> `RAKUTEN_APPLICATION_ID` / `RAKUTEN_ACCESS_KEY` / `RAKUTEN_AFFILIATE_ID` を Secret に、
> `SITE_BASE_URL` を Variable に登録し、Settings → Pages の Source を
> 「GitHub Actions」にすれば同じ状態になります。

---

## 4. 公開後にやること（ここが収益を分ける）

自動化されるのは記事生成までです。集客の初速だけは手を動かす価値があります。

1. **Google Search Console にサイトを登録し、`sitemap.xml` を送信**
   → これをやらないと検索結果に出るまでの時間が大きく変わります

   - プロパティは「**URLプレフィックス**」で `https://<user>.github.io/<repo>/` を登録する。
     「ドメイン」はDNS認証が必要で、`github.io` は自分のドメインではないため使えない
   - 所有権確認は「HTMLファイル」方式。ダウンロードしたファイルを
     [site_root/](site_root/) に置けば、毎日の再生成後も維持される
   - サイトマップ送信欄には **先頭スラッシュなしで `sitemap.xml`** と入力する。
     `/sitemap.xml` と書くとドメインルート（`<user>.github.io/sitemap.xml`）に
     解決されて404になり、「取得できませんでした」で失敗する

   > ⚠️ **プロジェクトページ（サブディレクトリ公開）の制約**:
   > クローラーは robots.txt を**ホストのルートしか読まない**ため、
   > `/<repo>/robots.txt` は無視されます。そこに書いた `Sitemap:` 行も
   > 読まれないので、**sitemapの自動発見は機能しません**。
   > GSCでの手動送信が唯一の登録経路になります。
2. **1〜2ヶ月後、Search Console の「検索パフォーマンス」を見る**
   → 表示回数が付いているジャンルが分かる
3. **伸びたジャンルに `config/site.yaml` を寄せる**
   → 反応の無いジャンルを削り、伸びたジャンルの `keywords` を細分化して記事を増やす

このループを回すのが、このシステムの本来の使い方です。

---

## 5. 守るべきルール

コード側で対応済みですが、テンプレートを編集するときは壊さないでください。

- **ステマ規制（景品表示法）** — 全ページ最上部に「本ページはプロモーションを含みます」を表示
  （[templates/base.html](templates/base.html) の `.pr-notice`。**削除すると景表法違反になります**）
- **リンク属性** — アフィリエイトリンクには `rel="nofollow sponsored"` を付与済み
- **APIレート制限** — 1リクエスト/秒を [src/rakuten.py](src/rakuten.py) で強制。緩めるとBANされます
- **価格情報の鮮度** — 「取得時点の情報」である旨をフッターと免責ページに明記済み
- **商品情報の出典** — 「Supported by 楽天ウェブサービス」をフッターに設置済み（第13条により必須）
- **公開URLに楽天の商標を含めない** — 第10条1項(8)。違反するとアプリIDを停止・削除され得ます。
  [setup.ps1](setup.ps1) がリポジトリ名を検査して停止するようにしてありますが、
  独自ドメインを当てる場合も同様に避けてください
- **楽天アフィリエイト以外で収益化しない** — 第10条1項(4)(5)。
  **AdSenseや他社アフィリエイトをこのサイトに貼るのは規約違反**です。PVが増えても手を出さないこと
- **運営主体の明示** — 第11条1項。「個人運営であり楽天グループとの提携関係はない」旨をフッターに記載済み
- **楽天以外へのリンクを商品欄に置かない** — 第8条4項。商品カードのリンクは全て楽天向けにしてあります

---

## 6. ハマりどころ（2026年API刷新の実測メモ）

公式ドキュメントに散らばっている情報を、実際に叩いて確認した結果です。

**エンドポイントはAPIごとにパスの第1階層が違う**（[rakuten.py](src/rakuten.py)）

| API | URL | 版 |
|---|---|---|
| 商品検索 | `openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/` | `20260701` |
| ランキング | `openapi.rakuten.co.jp/ichibaranking/api/IchibaItem/Ranking/` | `20220601` |
| ジャンル検索 | `openapi.rakuten.co.jp/ichibagt/api/IchibaGenre/Search/` | `20260701` |

旧 `app.rakuten.co.jp/services/api/...` は2026-05-13に停止済みです。

**ランキングAPIの `period` は `realtime` のみ**
`daily` / `weekly` / `monthly` は `400 set period from realtime` で弾かれます。

**ジャンル検索のレスポンス構造が変わった**
`children[].child.genreName` → `children[].nameJa` にフラット化されています。

**ジャンルIDを間違えても200が返る** ← 最も危険
存在するIDなら別ジャンルでも正常応答するため、設定ミスに気づけません。
実際に開発中、`216131` をスキンケアのつもりで指定して「バッグ・小物」の商品が
並んでいました。対策として、ランキングAPIのレスポンスに含まれる `title` と
`config/site.yaml` の `name` を突き合わせ、不一致なら警告を出しています
（[rakuten.py](src/rakuten.py) の `ranking()`）。追加のAPIコールは発生しません。

ジャンルIDを調べ直すときは `python -m src.genres <親ID>` を使ってください。

**料率はAPIが返す** — `affiliateRate` に商品ごとの実料率が入るため、
`config/site.yaml` の `commission_rate` より優先して使っています
（[curate.py](src/curate.py)）。設定値はAPIが返さなかった場合のフォールバックです。

**レート制限は厳しい** — 連続で叩くとすぐ429が返ります。
1.2秒間隔＋指数バックオフで再試行しています。

## 7. 次の一手（未実装）

- **IndexNow 対応** — Bing/Yandex に更新を即時通知。毎日更新サイトとは相性が良い
- **Google Analytics / Microsoft Clarity** — どのCTAが押されているかの計測
- **記事の自然文化** — `commission_rate` の高いジャンルに限り Claude API で導入文を生成（[claude-api](https://docs.claude.com/) 参照）
- **セール連動** — 楽天スーパーSALE・お買い物マラソン期間に告知セクションを自動挿入（この期間は成果が跳ねる）

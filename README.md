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

### 楽天アフィリエイトが個人向きな理由

- **審査がない** — 楽天会員なら登録した瞬間から使える（A8/Amazonのようなサイト審査待ちがない）
- **クリックした商品以外の購入も成果になる** — ユーザーが楽天に飛んだあと別の商品を買っても報酬が発生する。
  つまり「何を売るか」より **「とにかく楽天に送客する回数」** が効く。CTAを多く置く設計はこのため。
- **料率は商品ジャンルごとに2%〜8%** — `config/site.yaml` の `commission_rate` に設定し、スコアリングに反映される。

> 成果条件・料率・支払条件は楽天側の改定が入ります。運用前に
> [楽天アフィリエイト公式](https://affiliate.rakuten.co.jp/) の最新規約を必ず確認してください。

### 現実的な数字感

自動生成サイトが**すぐに稼げるわけではありません**。SEOで検索流入が付くまで3〜6ヶ月かかります。
初期は「18記事を毎日更新し続けるコストがゼロ」という点を活かして、
検索順位が付いたジャンルに `config/site.yaml` を寄せていく運用が現実的です。

**このシステムが自動化するのは「作業」であって「集客」ではありません。**
放置で儲かる魔法ではなく、記事制作コストをゼロにして試行回数を増やすための道具です。

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

### 3-1. 楽天のIDを2つ取得する（10分・ここだけ手作業）

**① アプリID (applicationId)** — 商品データを取るためのAPIキー

1. https://webservice.rakuten.co.jp/ に楽天会員でログイン
2. 「新規申請登録」から以下の内容で申請する
3. 発行された **applicationId**（19桁の数字）を控える

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

**② アフィリエイトID** — 報酬を自分に紐付けるためのID

1. https://affiliate.rakuten.co.jp/ にログイン（登録は無料・審査なし）
2. 「アフィリエイトID」を確認（`xxxxxxxx.xxxxxxxx.xxxxxxxx.xxxxxxxx` 形式）

> ⚠️ アフィリエイトIDが未設定だとリンクは生成されますが**成果が1円も付きません**。
> `main.py` は未設定のとき起動を止めるようにしてあります。

### 3-2. ローカルで動かす

```powershell
pip install -r requirements.txt

# APIキー無しで見た目だけ確認
python main.py --demo
python -m http.server -d docs 8000     # → http://localhost:8000

# 本番データで生成
copy .env.example .env                  # .env に取得した2つのIDを記入
python main.py
```

ジャンルIDを調べたいとき:

```powershell
python -m src.genres          # 大ジャンル一覧
python -m src.genres 100026   # そのジャンルの子ジャンル一覧
```

### 3-3. GitHub Pages で自動運用する（1コマンド）

`.env` に2つのIDを記入したら、あとは全自動です。

```powershell
.\setup.ps1
```

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
> `RAKUTEN_APPLICATION_ID` / `RAKUTEN_AFFILIATE_ID` を Secret に、
> `SITE_BASE_URL` を Variable に登録し、Settings → Pages の Source を
> 「GitHub Actions」にすれば同じ状態になります。

---

## 4. 公開後にやること（ここが収益を分ける）

自動化されるのは記事生成までです。集客の初速だけは手を動かす価値があります。

1. **Google Search Console にサイトを登録し、`sitemap.xml` を送信**
   → これをやらないと検索結果に出るまでの時間が大きく変わります
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

## 6. 次の一手（未実装）

- **IndexNow 対応** — Bing/Yandex に更新を即時通知。毎日更新サイトとは相性が良い
- **Google Analytics / Microsoft Clarity** — どのCTAが押されているかの計測
- **記事の自然文化** — `commission_rate` の高いジャンルに限り Claude API で導入文を生成（[claude-api](https://docs.claude.com/) 参照）
- **セール連動** — 楽天スーパーSALE・お買い物マラソン期間に告知セクションを自動挿入（この期間は成果が跳ねる）

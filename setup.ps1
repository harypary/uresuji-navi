# ============================================================
#  .env に楽天のIDを貼ったあと、これ1本で公開まで終わらせるスクリプト
#
#    .\setup.ps1                          # 既定のリポジトリ名で公開
#    .\setup.ps1 -RepoName my-site        # 名前を指定
#
#  やること:
#    1. .env の検証
#    2. ローカルで記事を生成して動作確認
#    3. git init + commit + GitHubへpush（リポジトリが無ければ作成）
#    4. Secrets / Variables を .env から自動登録
#    5. GitHub Pages を "GitHub Actions" ソースで有効化
#    6. ワークフローを即時実行して公開
# ============================================================

param(
    # 公開リポジトリ名。そのまま公開URLになる。
    # 楽天ウェブサービス利用規約 第10条1項(8)により、URLに楽天の商号・商標と
    # 同一/類似の文字列を含めることは禁止されている（アプリID停止の対象）。
    # ローカルのフォルダ名(24.rakutenn)をそのまま使わないのはこのため。
    [string]$RepoName = "uresuji-navi"
)

$ErrorActionPreference = "Stop"
# PowerShell 7.4+ は既定で「外部コマンドの非0終了」も例外にする。
# このスクリプトは git/gh の終了コードを自前で判定しているので無効化しておく
$PSNativeCommandUseErrorActionPreference = $false
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = "1"

function Step($n, $msg) { Write-Host "`n[$n] $msg" -ForegroundColor Cyan }
function Ok($msg)       { Write-Host "    OK  $msg" -ForegroundColor Green }
function Fail($msg)     { Write-Host "`nERROR: $msg" -ForegroundColor Red; exit 1 }

# ---- 1. .env の検証 ----------------------------------------
Step 1 ".env を確認"

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Fail ".env を作成しました。楽天の2つのIDを記入してから、もう一度実行してください。`n     $((Resolve-Path '.env').Path)"
}

$envVars = @{}
foreach ($line in Get-Content ".env" -Encoding UTF8) {
    if ($line -match '^\s*([A-Z_]+)\s*=\s*(.*?)\s*$') { $envVars[$Matches[1]] = $Matches[2] }
}

# 2026年の刷新以降、applicationId と accessKey の2点セットが必須
foreach ($key in @("RAKUTEN_APPLICATION_ID", "RAKUTEN_ACCESS_KEY", "RAKUTEN_AFFILIATE_ID")) {
    $val = $envVars[$key]
    # .env.example のサンプル値が残っていると「動くのに1円も入らない」状態になる
    if (-not $val -or $val -like "00000000-*" -or $val -like "xxxxxx*" -or $val -like "abcdef01*") {
        Fail "$key が未記入（またはサンプル値のまま）です。.env を編集してください。"
    }
}
Ok "楽天の認証情報を3件読み込みました"

# ---- 2. GitHub 側の情報を決める -----------------------------
Step 2 "GitHubリポジトリを確認"

gh auth status 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "GitHub CLI が未認証です。先に 'gh auth login' を実行してください。" }

$owner = (gh api user --jq .login)
$repo  = $RepoName

# 規約違反のURLで公開してしまうと、後からアプリIDごと止められる。ここで弾く
if ($repo -match "(?i)raku ?ten|楽天") {
    Fail "リポジトリ名 '$repo' は楽天の商標に類似するためURLに使えません（利用規約 第10条1項(8)）。`n     -RepoName で別の名前を指定してください。例: .\setup.ps1 -RepoName uresuji-navi"
}

$siteUrl = "https://$owner.github.io/$repo"
Ok "公開URL: $siteUrl"

# ---- 3. ローカル生成でAPIキーの正しさを検証 -------------------
Step 3 "楽天APIから記事を生成（IDが正しいかの確認を兼ねる）"

python main.py
if ($LASTEXITCODE -ne 0) { Fail "記事の生成に失敗しました。上のログを確認してください。" }
Ok "生成に成功。楽天のIDは有効です"

# ---- 4. push ------------------------------------------------
Step 4 "GitHubへpush"

if (-not (Test-Path ".git")) { git init -q; git branch -M main }
git add -A
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) { git commit -q -m "楽天アフィリエイト自動生成サイト" }

git remote get-url origin 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    # Pages を無料で使うには public である必要がある
    gh repo create $repo --public --source=. --remote=origin --push
} else {
    git push -u origin main
}
Ok "$owner/$repo"

# ---- 5. Secrets / Variables ---------------------------------
Step 5 "Secrets と Variables を登録"

gh secret set RAKUTEN_APPLICATION_ID --body $envVars["RAKUTEN_APPLICATION_ID"] --repo "$owner/$repo"
gh secret set RAKUTEN_ACCESS_KEY     --body $envVars["RAKUTEN_ACCESS_KEY"]     --repo "$owner/$repo"
gh secret set RAKUTEN_AFFILIATE_ID   --body $envVars["RAKUTEN_AFFILIATE_ID"]   --repo "$owner/$repo"
gh variable set SITE_BASE_URL --body $siteUrl --repo "$owner/$repo"

# Search Console の確認トークンは公開metaタグに出る値なので Secret ではなく Variable
if ($envVars["GOOGLE_SITE_VERIFICATION"]) {
    gh variable set GOOGLE_SITE_VERIFICATION --body $envVars["GOOGLE_SITE_VERIFICATION"] --repo "$owner/$repo"
    Ok "Search Console の確認トークンを登録"
}
Ok "アフィリエイトIDはSecretとして保存（リポジトリ上では非公開）"

# ---- 6. Pages を有効化 --------------------------------------
Step 6 "GitHub Pages を有効化"

# 未設定なら POST、設定済みなら PUT。どちらか片方しか成功しないので順に試す
gh api -X POST "repos/$owner/$repo/pages" -f build_type=workflow 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    gh api -X PUT "repos/$owner/$repo/pages" -f build_type=workflow 2>$null | Out-Null
}
Ok "ソース: GitHub Actions"

# ---- 7. 初回デプロイ ----------------------------------------
Step 7 "初回デプロイを実行"

gh workflow run daily.yml --repo "$owner/$repo"
Ok "ワークフローを起動しました"

Write-Host "`n========================================" -ForegroundColor Yellow
Write-Host " セットアップ完了" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Yellow
Write-Host " 公開URL : $siteUrl"
Write-Host " 進捗確認: gh run watch --repo $owner/$repo"
Write-Host " 以降は毎朝6時(JST)に自動更新されます。"
Write-Host "`n 次にやること: Google Search Console に $siteUrl/sitemap.xml を送信"
Write-Host " （これをやらないと検索流入が付くまでの時間が大きく変わります）`n"

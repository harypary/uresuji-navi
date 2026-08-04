# site_root/

ここに置いたファイルは、生成時に公開サイトの**ルート直下**へそのままコピーされます。

```
site_root/googlexxxx.html  →  https://<site>/googlexxxx.html
```

「必ずルート直下に無いと機能しない」ファイル置き場です。

- `google*.html` — Google Search Console の所有権確認ファイル
- `BingSiteAuth.xml` — Bing Webmaster Tools の確認ファイル
- `ads.txt` — 広告関連（※楽天規約により本サイトでは使用不可）
- IndexNow のキーファイル

`docs/` は毎回まるごと作り直されるため、手書きのファイルを直接置いても消えます。
消えては困るファイルは必ずこのディレクトリで管理してください。

この README 自体もコピーされますが、実害はないので放置で構いません。
気になる場合はファイル名の先頭を `.` にすると除外されます。

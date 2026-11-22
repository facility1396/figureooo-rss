# フィギュア関連RSS

このリポジトリでは、figure.ooo、ダイキ工業、CAMELOTのRSSを生成し、GitHub Pagesで公開します。

## 公開フィード

- figure.ooo：タイトル・トップ画像・記事リンクのみ  
  https://facility1396.github.io/figureooo-rss/feed.xml
- ダイキ工業：製品情報RSS  
  https://facility1396.github.io/figureooo-rss/daiki/feed.xml
- CAMELOT：製品タイトル・トップ画像・製品ページへのリンクのみ  
  https://facility1396.github.io/figureooo-rss/camelot/feed.xml

一覧ページ：
https://facility1396.github.io/figureooo-rss/

## 動作

- GitHub Actionsで30分ごとに更新
- figure.oooは公式RSSを読み込み、各記事ページからトップ画像だけを取得
- figure.oooのRSSには記事タイトル、記事リンク、トップ画像のみを掲載
- ダイキ工業は製品情報のみを取得し、お知らせ等は除外
- CAMELOTは公式製品一覧から商品リンクを抽出し、タイトル・トップ画像・商品ページリンクのみを掲載
- CAMELOTの一覧カードに画像がない場合、最大12商品まで商品ページのOG画像等を確認
- Bot確認やアクセス拒否が検出された場合は回避せず、その回のCAMELOTフィードを空で生成してログに警告を残す

## 手動実行

GitHubのActionsタブから「Build RSS feeds」を選択し、「Run workflow」を実行できます。

## 注意

- figure.oooとCAMELOTの画像は元サイトの画像URLを参照します。画像ファイルをこのリポジトリに複製するものではありません。
- CAMELOTの一覧ページは、この実行環境からHTML構造を直接検証できていません。初回のActionsログと生成RSSで抽出結果を確認してください。商品リンクが検出されない場合は、ページ構造に合わせてセレクターを調整する必要があります。
- 元サイトのHTML構造変更やアクセス制限により、画像・商品リンクの取得に失敗する場合があります。
- サイト側の利用条件・権利関係は、各サイトの規約等を別途確認してください。

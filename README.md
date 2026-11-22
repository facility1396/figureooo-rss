# フィギュア関連RSS

このリポジトリでは、figure.ooo、ダイキ工業、CAMELOTのRSSを生成し、GitHub Pagesで公開します。

## 公開フィード

- figure.ooo：タイトル・トップ画像・記事リンクのみ  
  https://facility1396.github.io/figureooo-rss/feed.xml
- ダイキ工業：製品情報RSS  
  https://facility1396.github.io/figureooo-rss/daiki/feed.xml
- CAMELOT：商品名・トップ画像・公式商品ページへのリンクのみ  
  https://facility1396.github.io/figureooo-rss/camelot/feed.xml

一覧ページ：
https://facility1396.github.io/figureooo-rss/

## 動作

- GitHub Actionsで30分ごとに更新
- figure.oooは公式RSSを読み込み、各記事ページからトップ画像だけを取得
- figure.oooのRSSには記事タイトル、記事リンク、トップ画像のみを掲載
- figure.oooの記事本文や本文中の画像一覧はRSSに含めず、記事を読む場合は元サイトを開く
- ダイキ工業は製品情報のみを取得し、お知らせ等は除外
- CAMELOTは公式製品一覧の `article.p-product-card` から商品情報を取得
- CAMELOTは商品名・一覧に表示されるトップ画像URL・公式商品ページへのリンクのみを掲載
- CAMELOTのCOMING SOONカードは商品ページへのリンクがないため除外

## 手動実行

GitHubのActionsタブから「Build RSS feeds」を選択し、「Run workflow」を実行できます。

## 注意

- figure.oooとCAMELOTの画像は元サイトの画像URLを参照します。画像ファイルをこのリポジトリに複製するものではありません。
- CAMELOTの一覧HTMLで商品カードが検出できない場合は、空のフィードを作らずビルドを失敗させます。サイト側の構造変更をActionsのログで確認してください。
- Bot確認やアクセス拒否が検出された場合は回避せず、その回のビルドを停止します。
- 元サイトのHTML構造変更やアクセス制限により、画像・商品リンクの取得に失敗する場合があります。
- サイト側の利用条件・権利関係は、各サイトの規約等を別途確認してください。

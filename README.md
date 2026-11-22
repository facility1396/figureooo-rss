# フィギュア関連RSS

このリポジトリでは、figure.ooo とダイキ工業のRSSを生成し、GitHub Pagesで公開します。

## 公開フィード

- figure.ooo：タイトル・トップ画像・記事リンクのみ  
  https://facility1396.github.io/figureooo-rss/feed.xml
- ダイキ工業：製品情報RSS  
  https://facility1396.github.io/figureooo-rss/daiki/feed.xml

一覧ページ：
https://facility1396.github.io/figureooo-rss/

## 動作

- GitHub Actionsで30分ごとに更新
- figure.oooは公式RSSを読み込み、各記事ページからトップ画像だけを取得
- figure.oooのRSSには記事タイトル、記事リンク、トップ画像のみを掲載
- figure.oooの記事本文や本文中の画像一覧はRSSに含めず、記事を読む場合は元サイトを開く
- ダイキ工業は製品情報のみを取得し、お知らせ等は除外

## 手動実行

GitHubのActionsタブから「Build RSS feeds」を選択し、「Run workflow」を実行できます。

## 注意

- figure.oooの画像は元サイトの画像URLを参照します。画像ファイルをこのリポジトリに複製するものではありません。
- 元サイトのHTML構造変更やアクセス制限により、トップ画像の取得に失敗する場合があります。Actionsのログで確認してください。
- サイト側の利用条件・権利関係は、各サイトの規約等を別途確認してください。

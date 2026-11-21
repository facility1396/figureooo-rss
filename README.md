# figure.ooo 画像付きRSS

figure.ooo の既存RSSを読み込み、記事ページから画像と本文HTMLを抽出して、Inoreader向けのRSSを生成します。

## セットアップ

1. Settings → Pages を開き、Build and deployment の Source を **GitHub Actions** に設定します。
2. Actions タブで **Build image-enhanced RSS** を選び、Run workflow を実行します。
3. 成功後、次のURLをInoreaderに登録します。

   `https://facility1396.github.io/figureooo-rss/feed.xml`

## 動作

- 30分ごとに figure.ooo/feed.xml を取得
- 記事ページから本文領域と画像を抽出
- `media:thumbnail` と `enclosure` にメイン画像を設定
- `media:content` に抽出した画像を列挙
- `content:encoded` に本文HTML（本文画像を含む）を格納
- GitHub Pagesで `feed.xml` を公開

## 注意

- 初回実行は Actions タブから手動実行してください。
- サイト側のHTML構造変更やアクセス制限（403等）で画像抽出が失敗する場合があります。Actions のログで確認してください。
- 画像は figure.ooo の画像URLを参照します。画像ファイルをこのリポジトリに複製するものではありません。
- Inoreaderの一覧サムネイル表示は、Inoreader側の表示設定や画像取得仕様にも依存します。
- RSSには元記事の画像・本文が含まれるため、成人向けカテゴリの表示にも注意してください。

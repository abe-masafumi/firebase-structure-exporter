# 環境構築手順

このリポジトリで Firestore の構造をエクスポートするための環境構築手順をまとめています。以下の手順は macOS / Linux を想定しています。

## 1. リポジトリの取得

```bash
git clone https://github.com/abe-masafumi/firebase-structure-exporter.git
cd firebase-structure-exporter
```

## 2. Python 仮想環境の作成

```bash
python -m venv venv
source venv/bin/activate
```

（Windows の場合は `venv\Scripts\activate`）

## 3. 依存パッケージのインストール

```bash
pip install -r requirements.txt
```

`google-cloud-firestore` と `python-dotenv` がインストールされ、 Firestore への接続と `.env` の読み込みに対応します。

## 4. 環境変数ファイルの設定

```bash
cp .env.example .env
```

`.env` を開き、以下の値を設定します。

- `FIRESTORE_PROJECT_ID`: Firestore プロジェクト ID
- `GOOGLE_APPLICATION_CREDENTIALS`: サービスアカウント JSON のパス（相対パス可）
- `OUTPUT_FILE`: 任意。出力先を変えたい場合のみ設定
- `SAMPLE_DOCUMENT_LIMIT`: 各コレクションから取得する最新ドキュメント数（任意、未設定なら 100）
- `SAMPLE_ORDER_FIELD`: サンプリング時に並び替えに使うフィールド。`created_at` などのタイムスタンプフィールドを指定可能（未設定なら `__name__`）

サービスアカウント JSON は `.gitignore` 済みの場所に置き、 Git に含めないでください。

## 5. Firestore 構造のエクスポート

```bash
python export_structure.py
```

実行すると Firestore へ接続し、各コレクションについてサンプル取得したドキュメント群（最新 `SAMPLE_DOCUMENT_LIMIT` 件）から判明したフィールドとサブコレクションの構造のみを `output/firestore_structure.json`（または `OUTPUT_FILE`）に集約出力します。

出力例（抜粋）:

```json
{
  "project_id": "my-project",
  "exported_at": "2024-01-01T00:00:00+00:00",
  "collections": {
    "albums": {
      "fields": {
        "created_at": "DatetimeWithNanoseconds",
        "pet_id": "str",
        "user_id": "str",
        "name": "str"
      },
      "subcollections": {
        "files": {
          "fields": {
            "filename": "str",
            "description": "str",
            "metadata": "dict",
            "created_at": "DatetimeWithNanoseconds"
          }
        }
      }
    }
  }
}
```

## 6. 仮想環境の終了

作業終了後は以下で仮想環境を抜けられます。

```bash
deactivate
```

以上で環境構築と実行準備は完了です。

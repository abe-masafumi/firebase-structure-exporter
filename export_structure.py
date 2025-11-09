#!/usr/bin/env python3
"""
Export the structure of a Firestore database to JSON.
"""

from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
from google.api_core.exceptions import FailedPrecondition, InvalidArgument
from google.cloud import firestore


# 進捗がわかるようにモジュール共通のロガーを定義。
logger = logging.getLogger(__name__)


# .env で指定された認証キーのパスを絶対パスに解決し存在確認を行う。
def resolve_credentials_path(credentials_path: str | None) -> Path:
    if not credentials_path:
        raise ValueError("GOOGLE_APPLICATION_CREDENTIALS is not set in .env")

    full_path = Path(credentials_path).expanduser()
    if not full_path.is_absolute():
        full_path = (PROJECT_ROOT / full_path).resolve()

    if not full_path.exists():
        raise FileNotFoundError(f"Service account file not found: {full_path}")

    return full_path


# ドキュメント内のフィールド型とサブコレクション構造を辞書にまとめる。
def describe_document(doc_snapshot: firestore.DocumentSnapshot) -> Dict[str, Any]:
    field_types = {}
    data = doc_snapshot.to_dict() or {}

    for field_name, value in data.items():
        field_types[field_name] = type(value).__name__

    structure: Dict[str, Any] = {"fields": field_types}

    subcollections = {}
    for subcollection_ref in doc_snapshot.reference.collections():
        subcollections[subcollection_ref.id] = describe_collection(subcollection_ref)

    if subcollections:
        structure["subcollections"] = subcollections

    return structure


# コレクションを走査して最新ドキュメント（最大 SAMPLE_DOCUMENT_LIMIT 件）の構造を取得する。
def describe_collection(collection_ref: firestore.CollectionReference) -> Dict[str, Any]:
    aggregate_structure: Dict[str, Any] = {"fields": {}, "subcollections": {}}
    doc_count = 0
    document_iterator = _iter_documents_with_limit(collection_ref)

    for doc_snapshot in document_iterator:
        doc_structure = describe_document(doc_snapshot)
        merge_collection_structures(aggregate_structure, doc_structure)
        doc_count += 1

    logger.info("Described %d document(s) in collection '%s'", doc_count, collection_ref.id)
    if SAMPLE_DOCUMENT_LIMIT and doc_count == SAMPLE_DOCUMENT_LIMIT:
        logger.info(
            "Reached sample limit (%d docs) for collection '%s'; remaining documents are skipped.",
            SAMPLE_DOCUMENT_LIMIT,
            collection_ref.id,
        )

    if not aggregate_structure["subcollections"]:
        aggregate_structure.pop("subcollections")
    if not aggregate_structure["fields"]:
        aggregate_structure.pop("fields", None)

    return aggregate_structure


# SAMPLE_DOCUMENT_LIMIT を考慮しつつ、必要に応じてソート／フォールバック付きでドキュメントを取得する。
def _iter_documents_with_limit(collection_ref: firestore.CollectionReference):
    if not SAMPLE_DOCUMENT_LIMIT:
        yield from collection_ref.stream()
        return

    order_field = SAMPLE_ORDER_FIELD or "__name__"
    query = collection_ref.order_by(order_field, direction=firestore.Query.DESCENDING).limit(SAMPLE_DOCUMENT_LIMIT)

    try:
        yield from query.stream()
        return
    except (FailedPrecondition, InvalidArgument) as exc:
        logger.warning(
            "collection '%s' をフィールド '%s' の最新順に取得するには Firestore のインデックスが必要です。"
            " インデックス未作成またはフィールド未設定のためソートなしの取得にフォールバックします: %s",
            collection_ref.id,
            order_field,
            exc.message if hasattr(exc, "message") else exc,
        )

    count = 0
    for doc_snapshot in collection_ref.stream():
        yield doc_snapshot
        count += 1
        if count >= SAMPLE_DOCUMENT_LIMIT:
            break


# 集約済み構造(target)に source のフィールド／サブコレクション情報をマージする。
def merge_collection_structures(target: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
    target_fields = target.setdefault("fields", {})
    for field_name, type_name in source.get("fields", {}).items():
        target_fields.setdefault(field_name, type_name)

    source_subcollections = source.get("subcollections", {})
    if not source_subcollections:
        return target

    target_subcollections = target.setdefault("subcollections", {})
    for sub_name, sub_structure in source_subcollections.items():
        if sub_name in target_subcollections:
            merge_collection_structures(target_subcollections[sub_name], sub_structure)
        else:
            target_subcollections[sub_name] = deepcopy(sub_structure)

    return target


# すべてのルートコレクションを巡り、プロジェクト全体の構造マップを作成する。
def export_structure(client: firestore.Client) -> Dict[str, Any]:
    structure = {
        "project_id": client.project,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "collections": {},
    }

    for collection_ref in client.collections():
        logger.info("Processing collection '%s'", collection_ref.id)
        structure["collections"][collection_ref.id] = describe_collection(collection_ref)

    return structure


# 生成した構造情報を JSON として指定パスに書き出す。
def write_output(payload: Dict[str, Any], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("Wrote output to %s", destination)


# エントリーポイント：環境変数を読み込み、クライアントを初期化してエクスポートを開始する。
def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")

    load_dotenv()
    global SAMPLE_DOCUMENT_LIMIT, SAMPLE_ORDER_FIELD
    SAMPLE_DOCUMENT_LIMIT = int(os.getenv("SAMPLE_DOCUMENT_LIMIT", str(DEFAULT_SAMPLE_DOCUMENT_LIMIT)))
    SAMPLE_ORDER_FIELD = os.getenv("SAMPLE_ORDER_FIELD", DEFAULT_SAMPLE_ORDER_FIELD)

    project_id = os.getenv("FIRESTORE_PROJECT_ID")
    if not project_id:
        raise ValueError("FIRESTORE_PROJECT_ID is not set in .env")

    credentials_path = resolve_credentials_path(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(credentials_path)

    output_file = os.getenv("OUTPUT_FILE", "output/firestore_structure.json")
    output_path = (PROJECT_ROOT / output_file).resolve()

    logger.info("Connecting to Firestore project '%s'", project_id)
    client = firestore.Client(project=project_id)
    logger.info("Starting export...")
    structure = export_structure(client)
    write_output(structure, output_path)

    logger.info("Export complete")


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_SAMPLE_DOCUMENT_LIMIT = 100
SAMPLE_DOCUMENT_LIMIT = DEFAULT_SAMPLE_DOCUMENT_LIMIT
DEFAULT_SAMPLE_ORDER_FIELD = "__name__"
SAMPLE_ORDER_FIELD = DEFAULT_SAMPLE_ORDER_FIELD


if __name__ == "__main__":
    main()

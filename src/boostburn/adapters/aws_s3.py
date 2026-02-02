from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional

import boto3
from botocore.exceptions import ClientError


@dataclass(frozen=True)
class S3Object:
    key: str
    etag: str
    last_modified: datetime


class S3Adapter:
    def list_objects(self, bucket: str, prefix: str) -> List[S3Object]:
        raise NotImplementedError

    def get_object_bytes(self, bucket: str, key: str) -> bytes:
        raise NotImplementedError

    def put_object(self, bucket: str, key: str, body: bytes, content_type: str = "application/json") -> str:
        raise NotImplementedError

    def get_object_etag(self, bucket: str, key: str) -> Optional[str]:
        raise NotImplementedError


class AwsS3Adapter(S3Adapter):
    def __init__(self) -> None:
        self._client = boto3.client("s3")

    def list_objects(self, bucket: str, prefix: str) -> List[S3Object]:
        objects: List[S3Object] = []
        token: Optional[str] = None
        while True:
            params = {"Bucket": bucket, "Prefix": prefix}
            if token:
                params["ContinuationToken"] = token
            response = self._client.list_objects_v2(**params)
            for item in response.get("Contents", []) or []:
                etag = item.get("ETag", "").strip('"')
                objects.append(S3Object(key=item["Key"], etag=etag, last_modified=item["LastModified"]))
            if not response.get("IsTruncated"):
                break
            token = response.get("NextContinuationToken")
        return objects

    def get_object_bytes(self, bucket: str, key: str) -> bytes:
        response = self._client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    def put_object(self, bucket: str, key: str, body: bytes, content_type: str = "application/json") -> str:
        response = self._client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )
        return response.get("ETag", "").strip('"')

    def get_object_etag(self, bucket: str, key: str) -> Optional[str]:
        try:
            response = self._client.head_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        return response.get("ETag", "").strip('"')

"""运营按 Android / iOS 发布整包和热更新，供手机启动时检查。"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppRelease

PLATFORMS = ("android", "ios")
KINDS = ("native", "wgt")


class AppReleaseError(Exception):
    def __init__(self, message: str, code: str = "invalid"):
        self.message = message
        self.code = code
        super().__init__(message)


def _clean_platform(value: str) -> str:
    text = (value or "").strip().lower()
    if text not in PLATFORMS:
        raise AppReleaseError("平台只能是 android 或 ios")
    return text


def _clean_kind(value: str) -> str:
    text = (value or "").strip().lower() or "native"
    if text not in KINDS:
        raise AppReleaseError("类型只能是整包或热更新")
    return text


def _clean_version_name(value: str) -> str:
    text = (value or "").strip()
    if not text:
        raise AppReleaseError("请填写版本名")
    if len(text) > 32:
        raise AppReleaseError("版本名不能超过 32 字")
    return text


def _clean_version_code(value: int) -> int:
    try:
        code = int(value)
    except (TypeError, ValueError) as exc:
        raise AppReleaseError("版本号须为整数") from exc
    if code < 1 or code > 2_000_000_000:
        raise AppReleaseError("版本号须在 1 到 2000000000 之间")
    return code


def _clean_url(value: str, *, required: bool, platform: str, kind: str) -> str:
    text = (value or "").strip()
    if not text:
        if required:
            raise AppReleaseError("发布时请填写下载地址")
        return ""
    if len(text) > 500:
        raise AppReleaseError("下载地址不能超过 500 字")
    parsed = urlparse(text)
    schemes = {"http", "https"}
    # iOS 整包不能在 App 内安装，只打开 TestFlight、App Store 或企业分发链接。
    if platform == "ios" and kind == "native":
        schemes |= {"itms-apps", "itms-services"}
    if parsed.scheme not in schemes or not parsed.netloc:
        if platform == "ios" and kind == "native":
            raise AppReleaseError("iOS 整包地址须为 https、itms-apps 或 itms-services 链接")
        raise AppReleaseError("下载地址须为 http 或 https 链接")
    return text


def _clean_notes(value: str | None) -> str:
    text = (value or "").strip()
    if len(text) > 500:
        raise AppReleaseError("更新说明不能超过 500 字")
    return text


def _clean_min_native(value: int | None, *, kind: str) -> int | None:
    if kind != "wgt" or value is None or value == "":
        return None
    return _clean_version_code(value)


def _public(row: AppRelease) -> dict:
    published = row.published_at
    return {
        "id": row.id,
        "platform": row.platform,
        "kind": row.kind or "native",
        "version_name": row.version_name,
        "version_code": int(row.version_code),
        "download_url": row.download_url or "",
        "notes": row.notes or "",
        "force_update": bool(row.force_update),
        "is_published": bool(row.is_published),
        "is_current": bool(row.is_current),
        "min_native_version_code": int(row.min_native_version_code) if row.min_native_version_code else None,
        "published_at": published.isoformat(sep=" ", timespec="minutes") if published else None,
    }


def _phone(row: AppRelease | None) -> dict | None:
    if row is None or not row.is_published or not (row.download_url or "").strip():
        return None
    data = _public(row)
    data.pop("id", None)
    data.pop("is_published", None)
    data.pop("is_current", None)
    return data


def _current_row(db: Session, platform: str, kind: str) -> AppRelease | None:
    return db.scalar(
        select(AppRelease)
        .where(
            AppRelease.platform == platform,
            AppRelease.kind == kind,
            AppRelease.is_current.is_(True),
        )
        .order_by(AppRelease.id.desc())
        .limit(1)
    )


def current_release(db: Session, platform: str) -> dict:
    """手机端按系统取已发布的整包和热更新。没有记录时对应项为空。"""
    name = _clean_platform(platform)
    return {
        "native": _phone(_current_row(db, name, "native")),
        "wgt": _phone(_current_row(db, name, "wgt")),
    }


def _history(db: Session, platform: str, kind: str) -> list[AppRelease]:
    return list(
        db.scalars(
            select(AppRelease)
            .where(AppRelease.platform == platform, AppRelease.kind == kind)
            .order_by(AppRelease.id.desc())
            .limit(20)
        ).all()
    )


def list_releases(db: Session) -> dict:
    out: dict = {}
    for platform in PLATFORMS:
        out[platform] = {}
        for kind in KINDS:
            rows = _history(db, platform, kind)
            current = next((row for row in rows if row.is_current), None)
            out[platform][kind] = {
                "current": _public(current) if current else None,
                "history": [_public(row) for row in rows],
            }
    return out


def save_release(
    db: Session,
    *,
    platform: str,
    kind: str,
    version_name: str,
    version_code: int,
    download_url: str,
    notes: str | None,
    force_update: bool,
    is_published: bool,
    min_native_version_code: int | None,
) -> dict:
    name = _clean_platform(platform)
    package_kind = _clean_kind(kind)
    version = _clean_version_name(version_name)
    code = _clean_version_code(version_code)
    url = _clean_url(download_url, required=is_published, platform=name, kind=package_kind)
    text = _clean_notes(notes)
    min_native = _clean_min_native(min_native_version_code, kind=package_kind)
    current = _current_row(db, name, package_kind)
    now = datetime.now()
    if current is not None and int(current.version_code) == code:
        current.version_name = version
        current.download_url = url
        current.notes = text
        current.force_update = bool(force_update)
        current.is_published = bool(is_published)
        current.min_native_version_code = min_native
        current.published_at = now
        db.commit()
        db.refresh(current)
        return _public(current)

    if current is not None:
        current.is_current = False
    row = AppRelease(
        platform=name,
        kind=package_kind,
        version_name=version,
        version_code=code,
        download_url=url,
        notes=text,
        force_update=bool(force_update),
        is_published=bool(is_published),
        is_current=True,
        min_native_version_code=min_native,
        published_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _public(row)


def _row_by_id(db: Session, release_id: int) -> AppRelease:
    row = db.get(AppRelease, release_id)
    if row is None:
        raise AppReleaseError("发布记录不存在", "not_found")
    return row


def _version_taken(db: Session, row: AppRelease, version_code: int) -> bool:
    other = db.scalar(
        select(AppRelease.id).where(
            AppRelease.platform == row.platform,
            AppRelease.kind == row.kind,
            AppRelease.version_code == version_code,
            AppRelease.id != row.id,
        )
    )
    return other is not None


def update_release(
    db: Session,
    release_id: int,
    *,
    version_name: str,
    version_code: int,
    download_url: str,
    notes: str | None,
    force_update: bool,
    is_published: bool,
    is_current: bool,
    min_native_version_code: int | None,
) -> dict:
    """改某一条记录本身。设为当前时，同平台同类型的其他当前记录让位。"""
    row = _row_by_id(db, release_id)
    kind = row.kind or "native"
    version = _clean_version_name(version_name)
    code = _clean_version_code(version_code)
    if _version_taken(db, row, code):
        raise AppReleaseError("同一平台和类型下已有这个版本号")
    url = _clean_url(download_url, required=is_published, platform=row.platform, kind=kind)
    if is_current:
        others = db.scalars(
            select(AppRelease).where(
                AppRelease.platform == row.platform,
                AppRelease.kind == kind,
                AppRelease.is_current.is_(True),
                AppRelease.id != row.id,
            )
        ).all()
        for other in others:
            other.is_current = False
    row.version_name = version
    row.version_code = code
    row.download_url = url
    row.notes = _clean_notes(notes)
    row.force_update = bool(force_update)
    row.is_published = bool(is_published)
    row.is_current = bool(is_current)
    row.min_native_version_code = _clean_min_native(min_native_version_code, kind=kind)
    row.published_at = datetime.now()
    db.commit()
    db.refresh(row)
    return _public(row)


def delete_release(db: Session, release_id: int) -> None:
    row = _row_by_id(db, release_id)
    db.delete(row)
    db.commit()

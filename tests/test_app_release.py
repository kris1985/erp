"""运营按系统发布整包和热更新，手机不登录即可读取。"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import Base, get_db
from app.main import app


def _client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app), db


def _login_ops(client: TestClient) -> dict:
    settings = get_settings()
    res = client.post(
        "/api/v1/operators/login",
        json={"username": settings.operator_username, "password": settings.operator_password},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['data']['access_token']}"}


def _put(client: TestClient, headers: dict, **payload):
    body = {
        "version_name": "1.0.1",
        "version_code": 101,
        "download_url": "https://tyulan.cn/download/app.apk",
        "is_published": True,
    }
    body.update(payload)
    return client.put("/api/v1/operators/app-releases", headers=headers, json=body)


def test_app_release_splits_platform_and_hot_update():
    client, _db = _client()
    try:
        empty = client.get("/api/v1/app-releases/current", params={"platform": "android"})
        assert empty.status_code == 200, empty.text
        assert empty.json()["data"] == {"native": None, "wgt": None}

        bad_platform = client.get("/api/v1/app-releases/current", params={"platform": "harmony"})
        assert bad_platform.status_code == 400

        denied = client.put(
            "/api/v1/operators/app-releases",
            json={"platform": "android", "kind": "native", "version_name": "1.0.1", "version_code": 101},
        )
        assert denied.status_code == 401

        headers = _login_ops(client)
        apk = _put(
            client,
            headers,
            platform="android",
            kind="native",
            version_code=101,
            download_url="https://tyulan.cn/download/app-101.apk",
            notes="整包",
            force_update=True,
        )
        assert apk.status_code == 200, apk.text

        wgt = _put(
            client,
            headers,
            platform="android",
            kind="wgt",
            version_name="1.0.2",
            version_code=102,
            download_url="https://tyulan.cn/download/app-102.wgt",
            min_native_version_code=101,
            notes="热更新",
        )
        assert wgt.status_code == 200, wgt.text
        assert wgt.json()["data"]["min_native_version_code"] == 101

        ios = _put(
            client,
            headers,
            platform="ios",
            kind="native",
            version_code=101,
            download_url="itms-apps://apps.apple.com/app/id0",
            notes="去 App Store",
        )
        assert ios.status_code == 200, ios.text

        android = client.get("/api/v1/app-releases/current", params={"platform": "android"}).json()["data"]
        assert android["native"]["version_code"] == 101
        assert android["native"]["force_update"] is True
        assert android["wgt"]["version_code"] == 102
        assert android["wgt"]["min_native_version_code"] == 101

        ios_current = client.get("/api/v1/app-releases/current", params={"platform": "ios"}).json()["data"]
        assert ios_current["native"]["download_url"].startswith("itms-apps://")
        assert ios_current["wgt"] is None

        hidden = _put(
            client,
            headers,
            platform="android",
            kind="wgt",
            version_name="1.0.2",
            version_code=102,
            download_url="https://tyulan.cn/download/app-102.wgt",
            is_published=False,
        )
        assert hidden.status_code == 200, hidden.text
        after = client.get("/api/v1/app-releases/current", params={"platform": "android"}).json()["data"]
        assert after["native"]["version_code"] == 101
        assert after["wgt"] is None
    finally:
        app.dependency_overrides.clear()


def test_app_release_edit_and_delete():
    client, _db = _client()
    try:
        headers = _login_ops(client)
        first = _put(
            client,
            headers,
            platform="android",
            kind="native",
            version_name="1.0.1",
            version_code=101,
            download_url="https://tyulan.cn/download/app-101.apk",
            notes="第一版",
        )
        assert first.status_code == 200, first.text
        first_id = first.json()["data"]["id"]
        second = _put(
            client,
            headers,
            platform="android",
            kind="native",
            version_name="1.0.2",
            version_code=102,
            download_url="https://tyulan.cn/download/app-102.apk",
            notes="第二版",
        )
        assert second.status_code == 200, second.text
        second_id = second.json()["data"]["id"]

        denied = client.put(
            f"/api/v1/operators/app-releases/{first_id}",
            json={"version_name": "1.0.1", "version_code": 101, "is_current": False},
        )
        assert denied.status_code == 401

        edited = client.put(
            f"/api/v1/operators/app-releases/{first_id}",
            headers=headers,
            json={
                "version_name": "1.0.1",
                "version_code": 101,
                "download_url": "https://tyulan.cn/download/app-101-fixed.apk",
                "notes": "改说明",
                "force_update": False,
                "is_published": True,
                "is_current": False,
            },
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["data"]["notes"] == "改说明"
        assert edited.json()["data"]["download_url"].endswith("app-101-fixed.apk")
        assert edited.json()["data"]["is_current"] is False
        current = client.get("/api/v1/app-releases/current", params={"platform": "android"}).json()["data"]
        assert current["native"]["version_code"] == 102

        promoted = client.put(
            f"/api/v1/operators/app-releases/{first_id}",
            headers=headers,
            json={
                "version_name": "1.0.1",
                "version_code": 101,
                "download_url": "https://tyulan.cn/download/app-101-fixed.apk",
                "notes": "改说明",
                "is_published": True,
                "is_current": True,
            },
        )
        assert promoted.status_code == 200, promoted.text
        current = client.get("/api/v1/app-releases/current", params={"platform": "android"}).json()["data"]
        assert current["native"]["version_code"] == 101
        assert current["native"]["notes"] == "改说明"

        clash = client.put(
            f"/api/v1/operators/app-releases/{first_id}",
            headers=headers,
            json={
                "version_name": "1.0.1",
                "version_code": 102,
                "download_url": "https://tyulan.cn/download/app-101-fixed.apk",
                "is_published": True,
                "is_current": True,
            },
        )
        assert clash.status_code == 400

        missing = client.put(
            "/api/v1/operators/app-releases/99999",
            headers=headers,
            json={
                "version_name": "9.9.9",
                "version_code": 999,
                "download_url": "https://tyulan.cn/download/missing.apk",
                "is_published": True,
                "is_current": False,
            },
        )
        assert missing.status_code == 404

        removed = client.delete(f"/api/v1/operators/app-releases/{first_id}", headers=headers)
        assert removed.status_code == 200, removed.text
        current = client.get("/api/v1/app-releases/current", params={"platform": "android"}).json()["data"]
        assert current["native"] is None

        listed = client.get("/api/v1/operators/app-releases", headers=headers).json()["data"]
        codes = [row["version_code"] for row in listed["android"]["native"]["history"]]
        assert codes == [102]
        # 删掉当前的 101 后，102 仍是历史记录，不会自动变成当前。
        assert listed["android"]["native"]["current"] is None

        gone = client.delete(f"/api/v1/operators/app-releases/{second_id}", headers=headers)
        assert gone.status_code == 200, gone.text
        missing_delete = client.delete("/api/v1/operators/app-releases/99999", headers=headers)
        assert missing_delete.status_code == 404
    finally:
        app.dependency_overrides.clear()

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import create_app
from sentinel.config.settings import Settings


def test_fastapi_serves_built_web_app_without_hiding_api_404s(tmp_path) -> None:
    dist_dir = tmp_path / "dist"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text("<html><body><div id=\"root\"></div></body></html>", encoding="utf-8")
    (assets_dir / "app.js").write_text("console.log('teo');", encoding="utf-8")
    settings = Settings(
        data_dir=tmp_path,
        db_path=tmp_path / "sentinel.sqlite",
        web_dist_dir=dist_dir,
    )
    client = TestClient(create_app(settings))

    root = client.get("/")
    client_route = client.get("/consulta")
    asset = client.get("/assets/app.js")
    missing_api = client.get("/api/not-real")

    assert root.status_code == 200
    assert "root" in root.text
    assert client_route.status_code == 200
    assert "root" in client_route.text
    assert asset.status_code == 200
    assert "teo" in asset.text
    assert missing_api.status_code == 404

"""G0 và G2: máy chủ, bảo mật, tác vụ nền, API dán nhãn."""

import threading
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from facesort import server as server_mod
from facesort.config import Config
from facesort.project import create_project
from tests.factories import World
from tests.fakes import FakeFaceEngine, det, unit

BASE = "http://127.0.0.1:8765"


def client(app):
    return TestClient(app, base_url=BASE)


@pytest.fixture
def world(tmp_path):
    """Dự án có sẵn dữ liệu giả: 3 nhóm, vài mặt lẻ."""
    cfg = Config(
        input_dir=str(tmp_path / "Ảnh cưới gốc"), output_dir=str(tmp_path / "Đầu ra")
    )
    (tmp_path / "Ảnh cưới gốc").mkdir()
    project = create_project("p", cfg)
    w = World(tmp_path, db_path=project.db_path)
    rng = np.random.default_rng(1)
    cs = [unit(rng.normal(size=512)) for _ in range(4)]
    w.cs = cs
    w.shas = [w.add_photo(f"{i}.png", i + 1) for i in range(4)]
    w.conn.execute("UPDATE photos SET width=8, height=8")
    w.clusters = []
    for k, c in enumerate(cs[:3]):
        cid = w.cluster()
        w.clusters.append(cid)
        for _j in range(3 + (3 - k)):  # nhóm 0 lớn nhất
            e = unit(c + rng.normal(scale=0.01, size=512)).astype(np.float32)
            w.conn.execute(
                "INSERT INTO faces (photo_sha256,x,y,w,h,det_score,embedding,quality_ok,cluster_id)"
                " VALUES (?,1,1,5,5,.9,?,1,?)",
                (w.shas[k], e.tobytes(), cid),
            )
    # 2 mặt lẻ
    for _ in range(2):
        e = unit(cs[3] + rng.normal(scale=0.01, size=512)).astype(np.float32)
        w.conn.execute(
            "INSERT INTO faces (photo_sha256,x,y,w,h,det_score,embedding,quality_ok) "
            "VALUES (?,1,1,5,5,.9,?,1)",
            (w.shas[3], e.tobytes()),
        )
    w.conn.commit()
    thumbs = project.dir / "thumbs" / "faces"
    thumbs.mkdir(parents=True, exist_ok=True)
    for fid in [r[0] for r in w.conn.execute("SELECT id FROM faces")]:
        Image.new("RGB", (20, 20)).save(thumbs / f"{fid}.jpg")
    w.project = project
    return w


@pytest.fixture
def api(world):
    return client(server_mod.create_app("p"))


# ---------------------------------------------------------------- bảo mật


def test_index_ok(api):
    r = api.get("/")
    assert r.status_code == 200 and "facesort" in r.text


def test_foreign_host_rejected(world):
    app = server_mod.create_app("p")
    c = TestClient(app, base_url="http://evil.example.com")
    assert c.get("/api/status").status_code == 403
    assert c.get("/").status_code == 403


def test_foreign_origin_rejected(api):
    r = api.post("/api/undo", headers={"Origin": "http://evil.example.com"})
    assert r.status_code == 403
    r = api.get("/api/status", headers={"Origin": "http://localhost:8765"})
    assert r.status_code == 200


def test_thumb_only_integer_ids_and_missing_404(api, world):
    fid = world.conn.execute("SELECT id FROM faces LIMIT 1").fetchone()[0]
    assert api.get(f"/thumbs/faces/{fid}.jpg").status_code == 200
    assert api.get("/thumbs/faces/999999.jpg").status_code == 404
    assert api.get("/thumbs/faces/..%2F..%2Fconfig.toml").status_code in (404, 422)
    assert api.get("/thumbs/faces/abc.jpg").status_code in (404, 422)


def test_photo_preview_validates_sha_and_draws(api, world):
    assert api.get("/api/photos/not-a-sha/preview").status_code == 404
    assert api.get("/api/photos/" + "0" * 64 + "/preview").status_code == 404
    r = api.get(f"/api/photos/{world.shas[0]}/preview")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    fid = world.conn.execute("SELECT id FROM faces LIMIT 1").fetchone()[0]
    assert api.get(f"/api/photos/{world.shas[0]}/preview?face={fid}").status_code == 200


def test_no_project_gives_vietnamese_409(tmp_path):
    c = client(server_mod.create_app(None))
    r = c.get("/api/status")
    assert r.status_code == 409 and "dự án" in r.json()["error"]
    assert c.get("/api/projects").json() == {"projects": [], "current": None}


# ---------------------------------------------------------------- cấu hình, dự án


def test_get_put_config_and_validation(api, world, tmp_path):
    cfg = api.get("/api/config").json()["config"]
    assert cfg["cluster_eps"] == 0.5
    assert api.put("/api/config", json={"config": {"cluster_eps": 0.42}}).status_code == 200
    assert api.get("/api/config").json()["config"]["cluster_eps"] == 0.42
    r = api.put("/api/config", json={"config": {"output_dir": str(tmp_path / "Ảnh cưới gốc" / "x")}})
    assert r.status_code == 422 and "output_dir" in r.json()["error"]
    r = api.put("/api/config", json={"config": {"input_dir": str(tmp_path / "khong_co")}})
    assert r.status_code == 422 and "Không tìm thấy folder input" in r.json()["error"]
    r = api.put("/api/config", json={"config": {"cluster_eps": "abc"}})
    assert r.status_code == 422
    assert api.put("/api/config", json={"config": {"bogus": 1}}).status_code == 422
    assert api.get("/api/config").json()["config"]["cluster_eps"] == 0.42  # không lưu khi lỗi


def test_create_project_via_api(tmp_path):
    c = client(server_mod.create_app(None))
    inp = tmp_path / "Ảnh cưới"
    inp.mkdir()
    r = c.post("/api/projects", json={"input_dir": str(tmp_path / "nope"), "output_dir": str(tmp_path / "o")})
    assert r.status_code == 422 and "folder input" in r.json()["error"]
    r = c.post("/api/projects", json={"input_dir": str(inp), "output_dir": str(inp / "o")})
    assert r.status_code == 422
    r = c.post("/api/projects", json={"input_dir": str(inp), "output_dir": str(tmp_path / "out")})
    assert r.status_code == 200 and r.json()["name"] == "Ảnh cưới"
    assert c.get("/api/projects").json()["current"] == "Ảnh cưới"
    r = c.post("/api/projects", json={"input_dir": str(inp), "output_dir": str(tmp_path / "out")})
    assert r.status_code == 422  # trùng tên dự án


def test_pick_folder(api, monkeypatch):
    monkeypatch.setattr(server_mod, "pick_folder", lambda initial=None: "D:\\Ảnh")
    assert api.post("/api/pick-folder", json={}).json() == {"path": "D:\\Ảnh"}

    def boom(initial=None):
        raise RuntimeError

    monkeypatch.setattr(server_mod, "pick_folder", boom)
    r = api.post("/api/pick-folder", json={})
    assert r.status_code == 501 and "dán đường dẫn" in r.json()["error"]


# ---------------------------------------------------------------- đọc


def test_status_and_clusters(api, world):
    s = api.get("/api/status").json()
    assert s["clusters"] == 3 and s["clusters_labeled"] == 0
    assert s["loose_faces"] == 2 and s["faces"] == 6 + 5 + 4 + 2 - 0 or s["faces"] > 0
    r = api.get("/api/clusters?filter=unlabeled").json()
    assert r["total"] == 3
    sizes = [c["faces"] for c in r["items"]]
    assert sizes == sorted(sizes, reverse=True)
    first = r["items"][0]
    assert first["main_face"] and first["photos"] == 1 and first["label"] is None
    assert len(first["small_faces"]) <= 5
    assert api.get("/api/clusters?filter=xyz").status_code == 422


def test_cluster_faces_and_404(api, world):
    cid = world.clusters[0]
    faces = api.get(f"/api/clusters/{cid}/faces").json()["faces"]
    assert len(faces) == 6
    assert api.get("/api/clusters/9999/faces").status_code == 404


# ---------------------------------------------------------------- ghi


def test_label_same_name_shares_label_and_hints(api, world):
    a, b, c = world.clusters
    r1 = api.put(f"/api/clusters/{a}/label", json={"name": "Ông A"}).json()
    r2 = api.put(f"/api/clusters/{b}/label", json={"name": "ông a"}).json()
    assert r1["label_id"] == r2["label_id"] and r2["label"] == "Ông A"
    assert len(api.get("/api/labels").json()["labels"]) == 1
    assert api.get("/api/clusters?filter=labeled").json()["total"] == 2
    assert api.get("/api/clusters?filter=unlabeled").json()["total"] == 1


def test_label_rejects_reserved_and_empty(api, world):
    cid = world.clusters[0]
    r = api.put(f"/api/clusters/{cid}/label", json={"name": "_Khac"})
    assert r.status_code == 422 and "_Khac" in r.json()["error"]
    assert api.put(f"/api/clusters/{cid}/label", json={"name": "  "}).status_code == 422
    r = api.put(f"/api/clusters/{cid}/label", json={"name": "Cô Lan / Chú Tư"})
    assert r.status_code == 200
    assert api.get("/api/labels").json()["labels"][0]["folder_name"] == "Cô Lan _ Chú Tư"
    assert api.put("/api/clusters/9999/label", json={"name": "X"}).status_code == 422


def test_ignore_detach_label_face_and_undo(api, world):
    cid = world.clusters[0]
    api.put(f"/api/clusters/{cid}/label", json={"name": "Ông A"})
    fid = api.get(f"/api/clusters/{cid}/faces").json()["faces"][0]["id"]
    assert api.post(f"/api/faces/{fid}/detach").status_code == 200
    assert len(api.get(f"/api/clusters/{cid}/faces").json()["faces"]) == 5
    loose = api.get("/api/faces/loose").json()
    assert loose["total"] == 3
    hint = [i for i in loose["items"] if i["id"] == fid][0]["hint"]
    assert hint and hint["label"] == "Ông A"  # mặt vừa tách vẫn giống Ông A
    assert api.put(f"/api/faces/{fid}/label", json={"name": "Bà B"}).status_code == 200
    assert api.get("/api/faces/loose").json()["total"] == 2  # đã có nhãn tay
    assert api.post(f"/api/faces/{fid}/ignore").status_code == 200
    assert api.post("/api/faces/99999/ignore").status_code == 404
    # hoàn tác lần lượt: ignore, label_face, detach, label_cluster
    kinds = [api.post("/api/undo").json()["undone"] for _ in range(4)]
    assert kinds == ["ignore_face", "label_face", "detach_face", "label_cluster"]
    assert api.post("/api/undo").status_code == 404
    assert api.get("/api/clusters?filter=unlabeled").json()["total"] == 3
    assert len(api.get("/api/labels").json()["labels"]) == 0


def test_ignore_cluster_toggle(api, world):
    cid = world.clusters[2]
    api.post(f"/api/clusters/{cid}/ignore", json={"ignored": True})
    assert api.get("/api/clusters?filter=ignored").json()["total"] == 1
    api.post(f"/api/clusters/{cid}/ignore", json={"ignored": False})
    assert api.get("/api/clusters?filter=ignored").json()["total"] == 0


def test_suggest_merge_endpoint(api, world):
    a = world.clusters[0]
    api.put(f"/api/clusters/{a}/label", json={"name": "Lan"})
    r = api.get(f"/api/clusters/{a}/suggest-merge")
    assert r.status_code == 200 and isinstance(r.json()["suggestions"], list)
    assert api.get("/api/clusters/9999/suggest-merge").status_code == 404


def test_rename_and_merge_label(api, world):
    a, b, _ = world.clusters
    la = api.put(f"/api/clusters/{a}/label", json={"name": "Lan"}).json()["label_id"]
    lb_ = api.put(f"/api/clusters/{b}/label", json={"name": "Lan Anh"}).json()["label_id"]
    r = api.patch(f"/api/labels/{lb_}", json={"name": "lan"}).json()
    assert r == {"label_id": la, "merged": True}
    assert len(api.get("/api/labels").json()["labels"]) == 1
    assert api.patch("/api/labels/999", json={"name": "x"}).status_code == 404


# ---------------------------------------------------------------- tác vụ nền


def wait_job(c, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        j = c.get("/api/job").json()
        if j["state"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("job không kết thúc")


def make_project_with_photos(tmp_path, n=4):
    inp = tmp_path / "Ảnh cưới"
    inp.mkdir()
    for i in range(n):
        Image.new("RGB", (100 + i, 80), (i * 9, 3, 3)).save(inp / f"ảnh {i}.jpg")
    return inp


def fake_factory(results):
    eng = FakeFaceEngine(results)
    return lambda cfg: eng


def person_faces(seed=0, n=1):
    rng = np.random.default_rng(seed)
    c = unit(np.random.default_rng(42).normal(size=512))
    return [det(emb=unit(c + rng.normal(scale=0.01, size=512))) for _ in range(n)]


def test_scan_and_export_jobs_end_to_end(tmp_path):
    inp = make_project_with_photos(tmp_path, 4)
    out = tmp_path / "Kết quả"
    app = server_mod.create_app(None, fake_factory([person_faces(i) for i in range(4)]))
    c = client(app)
    assert c.post("/api/projects", json={"input_dir": str(inp), "output_dir": str(out)}).status_code == 200
    assert c.post("/api/jobs/scan").status_code == 200
    j = wait_job(c)
    assert j["state"] == "done", j
    assert j["result"]["photos"] == 4 and j["result"]["clusters"] == 1
    cl = c.get("/api/clusters").json()["items"][0]
    c.put(f"/api/clusters/{cl['id']}/label", json={"name": "Họ nhà gái"})
    assert c.post("/api/jobs/export").status_code == 200
    j = wait_job(c)
    assert j["state"] == "done", j
    assert j["result"]["per_folder"] == {"Họ nhà gái": 4}
    assert j["result"]["copied"] == 4 and j["result"]["unlabeled_clusters"] == 0
    assert len(list((out / "Họ nhà gái").iterdir())) == 4
    # lần hai không copy lại
    c.post("/api/jobs/export")
    assert wait_job(c)["result"]["total_files"] == 0


def test_second_job_rejected_and_writes_blocked_while_running(world):
    app = server_mod.create_app("p")
    c = client(app)
    gate = threading.Event()

    def slow(progress, should_stop):
        progress("detect", 1, 10)
        gate.wait(5)
        return {"cancelled": should_stop()}

    app.state.fs.runner.start("scan", slow)
    assert c.post("/api/jobs/scan").status_code == 409
    assert c.post("/api/jobs/export").status_code == 409
    r = c.put(f"/api/clusters/{world.clusters[0]}/label", json={"name": "X"})
    assert r.status_code == 409
    assert c.get("/api/clusters").status_code == 200  # đọc vẫn được
    snap = c.get("/api/job").json()
    assert snap["state"] == "running" and snap["step"] == "detect" and snap["total"] == 10
    c.post("/api/job/cancel")
    gate.set()
    j = wait_job(c)
    assert j["state"] == "cancelled"
    assert c.put(f"/api/clusters/{world.clusters[0]}/label", json={"name": "X"}).status_code == 200


def test_job_error_is_vietnamese_not_traceback(tmp_path):
    inp = make_project_with_photos(tmp_path, 1)
    app = server_mod.create_app(None, fake_factory([]))
    c = client(app)
    c.post("/api/projects", json={"input_dir": str(inp), "output_dir": str(tmp_path / "o")})
    inp_cfg = c.get("/api/config").json()["config"]
    assert inp_cfg["input_dir"]
    c.post("/api/jobs/scan")  # engine giả hết kết quả -> lỗi bên trong
    j = wait_job(c)
    assert j["state"] == "error" and "Traceback" not in j["error"]


def test_job_blocked_when_project_locked_by_other_process(world):
    app = server_mod.create_app("p")
    c = client(app)
    with world.project.lock():
        assert c.post("/api/jobs/scan").status_code == 200
        j = wait_job(c)
    assert j["state"] == "error" and "đang được" in j["error"]


def test_open_output(api, world, monkeypatch, tmp_path):
    assert api.post("/api/open-output").status_code == 404
    (tmp_path / "Đầu ra").mkdir()
    opened = []
    monkeypatch.setattr(server_mod, "open_folder", lambda p: opened.append(p))
    assert api.post("/api/open-output").status_code == 200 and len(opened) == 1

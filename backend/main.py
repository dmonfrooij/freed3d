"""
FREE3D Backend v4
TripoSR image-to-3D pipeline
"""
import os, sys, uuid, shutil, asyncio, logging, zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("free3d")

BASE_DIR   = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads";  UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR = BASE_DIR / "outputs";  OUTPUT_DIR.mkdir(exist_ok=True)

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

triposr_model = None
bg_remover    = None
jobs: dict    = {}

# ─── Model laden ──────────────────────────────────────────────────────────────

def load_models():
    global triposr_model, bg_remover

    try:
        from transparent_background import Remover
        bg_remover = Remover()
        logger.info("✅ transparent-background geladen")
    except Exception as e:
        logger.warning(f"transparent-background niet beschikbaar: {e}")

    try:
        import torch
        if not torch.cuda.is_available():
            logger.warning("Geen CUDA GPU beschikbaar — TripoSR niet geladen")
            return
        from tsr.system import TSR
        logger.info("TripoSR laden (~1 GB eerste keer)...")
        triposr_model = TSR.from_pretrained(
            "stabilityai/TripoSR",
            config_name="config.yaml",
            weight_name="model.ckpt",
        )
        triposr_model.renderer.set_chunk_size(131072)  # max kwaliteit renderer
        triposr_model.to("cuda")
        logger.info("✅ TripoSR geladen!")
    except Exception as e:
        logger.warning(f"TripoSR kon niet laden: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, load_models)
    yield


app = FastAPI(title="FREE3D", version="4.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class JobStatus(BaseModel):
    job_id:      str
    status:      str
    progress:    int = 0
    message:     str = ""
    mode:        str = ""
    stl_url:     Optional[str] = None
    tmf_url:     Optional[str] = None
    glb_url:     Optional[str] = None
    preview_url: Optional[str] = None


def upd(job_id, **kw):
    if job_id in jobs:
        jobs[job_id].update(kw)


def export_3mf(mesh, path: Path):
    try:
        mesh.export(str(path)); return
    except Exception:
        pass
    model = ET.Element("model", {"unit":"millimeter",
        "xmlns":"http://schemas.microsoft.com/3dmanufacturing/core/2015/02"})
    res = ET.SubElement(model, "resources")
    obj = ET.SubElement(res, "object", {"id":"1","type":"model"})
    me  = ET.SubElement(obj, "mesh")
    ve  = ET.SubElement(me, "vertices")
    for v in mesh.vertices:
        ET.SubElement(ve, "vertex", {"x":f"{v[0]:.6f}","y":f"{v[1]:.6f}","z":f"{v[2]:.6f}"})
    te = ET.SubElement(me, "triangles")
    for f in mesh.faces:
        ET.SubElement(te, "triangle", {"v1":str(f[0]),"v2":str(f[1]),"v3":str(f[2])})
    build = ET.SubElement(model, "build")
    ET.SubElement(build, "item", {"objectid":"1"})
    xml_str = ET.tostring(model, encoding="unicode", xml_declaration=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        zf.writestr("_rels/.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        zf.writestr("3D/3dmodel.model", xml_str)


def render_preview(mesh, path: Path):
    try:
        import trimesh
        png = trimesh.Scene(mesh).save_image(resolution=(512,512))
        if png: path.write_bytes(png); return
    except Exception:
        pass
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (512,512), (18,18,22))
        ImageDraw.Draw(img).text((180,240), "3D Model", fill=(232,255,71))
        img.save(str(path))
    except Exception:
        pass


def to_trimesh(raw):
    import trimesh
    if isinstance(raw, trimesh.Trimesh):  return raw
    if isinstance(raw, trimesh.Scene):
        parts = list(raw.geometry.values())
        return trimesh.util.concatenate(parts) if parts else trimesh.Trimesh()
    if hasattr(raw, "verts_packed"):
        return trimesh.Trimesh(
            vertices=raw.verts_packed().cpu().numpy(),
            faces=raw.faces_packed().cpu().numpy())
    return trimesh.Trimesh(vertices=raw.vertices, faces=raw.faces)


def remove_background_simple(img):
    """Verwijder effen achtergrond via hoekkleur analyse (geen extra library)."""
    import numpy as np
    from PIL import ImageFilter
    rgba = img.convert("RGBA")
    data = np.array(rgba, dtype=np.float32)
    rgb  = data[:, :, :3]
    corners = np.concatenate([
        rgb[:10,:10].reshape(-1,3), rgb[:10,-10:].reshape(-1,3),
        rgb[-10:,:10].reshape(-1,3), rgb[-10:,-10:].reshape(-1,3),
    ])
    bg = np.median(corners, axis=0)
    dist = np.sqrt(np.sum((rgb - bg)**2, axis=2))
    thresh = max(25.0, float(np.percentile(dist, 20)))
    alpha = np.clip((dist - thresh) * 8, 0, 255).astype(np.uint8)
    from PIL import Image
    alpha_img = Image.fromarray(alpha).filter(ImageFilter.GaussianBlur(2))
    result = rgba.copy()
    result.putalpha(alpha_img)
    return result

# ─── TripoSR verwerking ───────────────────────────────────────────────────────

async def process_triposr(job_id: str, image_path: Path, out_dir: Path):
    try:
        import torch
        import numpy as np
        import trimesh
        from PIL import Image
        from tsr.utils import resize_foreground

        bg_mode = jobs[job_id].get("bg_mode", "remove")
        loop    = asyncio.get_event_loop()

        # ── 1. Achtergrond verwijderen ────────────────────────────────────────
        upd(job_id, status="processing", progress=10, message="Afbeelding laden...")
        img = Image.open(image_path).convert("RGBA")

        if bg_mode == "remove":
            upd(job_id, progress=15, message="Achtergrond verwijderen...")
            try:
                if bg_remover is not None:
                    def do_tb():
                        import tempfile, os as _os
                        tmp = tempfile.mktemp(suffix=".png")
                        img.convert("RGB").save(tmp)
                        result = bg_remover.process(Image.open(tmp), type="rgba")
                        _os.unlink(tmp)
                        return result.convert("RGBA")
                    img = await loop.run_in_executor(None, do_tb)
                else:
                    img = await loop.run_in_executor(None, lambda: remove_background_simple(img))
                upd(job_id, progress=25, message="Achtergrond verwijderd ✓")
            except Exception as e:
                logger.warning(f"Achtergrond verwijderen mislukt ({e}), doorgaan...")

        # ── 2. TripoSR preprocessing ──────────────────────────────────────────
        upd(job_id, progress=28, message="Afbeelding voorbewerken...")
        img = resize_foreground(img, 0.85)

        # Alpha compositing naar grijze achtergrond
        img_np = np.array(img, dtype=np.float32) / 255.0
        if img_np.ndim == 3 and img_np.shape[2] == 4:
            a = img_np[:,:,3:4]
            img_np = img_np[:,:,:3] * a + 0.5 * (1.0 - a)
        img = Image.fromarray((img_np * 255.0).astype(np.uint8))

        # Vergroot naar 512x512 voor maximale input kwaliteit
        # TripoSR's cond_image_size is 512 - geef het de volle resolutie
        img = img.resize((512, 512), Image.LANCZOS)

        # ── 3. Inferentie ─────────────────────────────────────────────────────
        upd(job_id, progress=32, message="3D model berekenen (TripoSR)...")

        def run_inf():
            with torch.no_grad():
                return triposr_model([img], device="cuda")

        scene_codes = await loop.run_in_executor(None, run_inf)

        # ── 4. Mesh extractie ─────────────────────────────────────────────────
        upd(job_id, progress=72, message="Mesh extraheren...")

        def run_mesh():
            target = jobs[job_id].get("resolution", 512)
            # Start bij gekozen resolutie, val terug bij VRAM problemen
            fallbacks = [r for r in [1024, 768, 640, 512, 448, 384, 320, 256] if r <= target]
            fallbacks = fallbacks or [256]
            for res in fallbacks:
                try:
                    logger.info(f"Mesh extractie op resolutie {res}...")
                    return triposr_model.extract_mesh(
                        scene_codes, resolution=res, has_vertex_color=False)[0], res
                except (RuntimeError, torch.cuda.OutOfMemoryError) as e:
                    logger.warning(f"Resolutie {res} mislukt ({e}), probeer lager...")
                    torch.cuda.empty_cache()
                    continue
            raise RuntimeError("Alle resoluties mislukt")

        raw, used_res = await loop.run_in_executor(None, run_mesh)
        logger.info(f"✅ Mesh klaar op resolutie {used_res}")

        # ── 5. Post-processing voor maximale kwaliteit ────────────────────────
        upd(job_id, progress=78, message=f"Post-processing (resolutie {used_res})... even geduld")
        mesh = to_trimesh(raw)

        def postprocess(m):
            import trimesh
            import trimesh.smoothing
            import numpy as np

            logger.info(f"Start post-processing: {len(m.faces)} faces")

            # Stap 1: Houd alleen het grootste aaneengesloten onderdeel
            components = m.split(only_watertight=False)
            if components:
                m = max(components, key=lambda c: len(c.faces))
                logger.info(f"Na cleanup: {len(m.faces)} faces")

            # Stap 2: Fix mesh problemen
            trimesh.repair.fix_normals(m)
            trimesh.repair.fix_winding(m)
            trimesh.repair.fill_holes(m)

            # Stap 3: Laplacian smoothing - verwijdert stepping artefacten
            # Meer iteraties = vloeiender maar minder scherpe details
            # 10 iteraties met lage lambda = beste balans
            try:
                m = trimesh.smoothing.filter_laplacian(m, iterations=10, lamb=0.2)
                logger.info("Laplacian smoothing klaar")
            except Exception as e:
                logger.warning(f"Smoothing mislukt: {e}")

            # Stap 4: Taubin smoothing bovenop - behoud volume beter dan puur laplacian
            try:
                m = trimesh.smoothing.filter_taubin(m, iterations=10)
                logger.info("Taubin smoothing klaar")
            except Exception as e:
                logger.warning(f"Taubin smoothing mislukt: {e}")

            # Stap 5: Verwijder geïsoleerde vertices en degenerate faces
            m.update_faces(m.nondegenerate_faces())
            m.update_faces(m.unique_faces())
            m.remove_unreferenced_vertices()

            # Stap 6: Nogmaals gaten dichten na smoothing
            trimesh.repair.fill_holes(m)

            # Stap 7: Schaal naar 100mm longest axis (standaard printmaat)
            bounds = m.bounds
            size = max(bounds[1] - bounds[0])
            if size > 0:
                m.apply_scale(100.0 / size)

            logger.info(f"Post-processing klaar: {len(m.faces)} faces, watertight: {m.is_watertight}")
            return m

        upd(job_id, progress=82, message="Smoothing en mesh repair...")
        mesh = await loop.run_in_executor(None, postprocess, mesh)

        upd(job_id, progress=92, message="Exporteren naar STL / 3MF / GLB...")
        mesh.export(str(out_dir / "model.glb"))
        mesh.export(str(out_dir / "model.stl"))
        export_3mf(mesh, out_dir / "model.3mf")

        upd(job_id, progress=95, message="Preview renderen...")
        render_preview(mesh, out_dir / "preview.png")

        upd(job_id, status="done", progress=100, message="Klaar!",
            mode="TripoSR (lokaal)",
            stl_url=f"/outputs/{job_id}/model.stl",
            tmf_url=f"/outputs/{job_id}/model.3mf",
            glb_url=f"/outputs/{job_id}/model.glb",
            preview_url=f"/outputs/{job_id}/preview.png")

    except Exception as e:
        logger.error(f"TripoSR fout: {e}", exc_info=True)
        upd(job_id, status="error", message=str(e))

# ─── Demo modus ───────────────────────────────────────────────────────────────

async def process_demo(job_id: str, image_path: Path, out_dir: Path):
    import trimesh
    for p, m in [(20,"Analyseren..."),(50,"Model bouwen..."),(80,"Exporteren...")]:
        upd(job_id, status="processing", progress=p, message=m)
        await asyncio.sleep(1.0)
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=1.0)
    mesh.export(str(out_dir / "model.glb"))
    mesh.export(str(out_dir / "model.stl"))
    export_3mf(mesh, out_dir / "model.3mf")
    render_preview(mesh, out_dir / "preview.png")
    upd(job_id, status="done", progress=100, message="Demo (geen GPU beschikbaar)",
        mode="Demo",
        stl_url=f"/outputs/{job_id}/model.stl",
        tmf_url=f"/outputs/{job_id}/model.3mf",
        glb_url=f"/outputs/{job_id}/model.glb",
        preview_url=f"/outputs/{job_id}/preview.png")

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "triposr":    triposr_model is not None,
        "bg_remover": bg_remover is not None,
        "mode":       "triposr" if triposr_model else "demo",
    }

@app.post("/convert", response_model=JobStatus)
async def convert(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    bg_mode: str = "remove",
    resolution: int = 512,
):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "Alleen afbeeldingen toegestaan")

    job_id   = str(uuid.uuid4())
    ext      = Path(file.filename or "img.jpg").suffix or ".jpg"
    img_path = UPLOAD_DIR / f"{job_id}{ext}"

    with open(img_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    jobs[job_id] = dict(
        job_id=job_id, status="queued", progress=0,
        message="In de wachtrij...",
        mode="triposr" if triposr_model else "demo",
        bg_mode=bg_mode,
        resolution=resolution,
        stl_url=None, tmf_url=None, glb_url=None, preview_url=None,
    )

    async def run():
        out = OUTPUT_DIR / job_id
        out.mkdir(exist_ok=True)
        if triposr_model:
            await process_triposr(job_id, img_path, out)
        else:
            await process_demo(job_id, img_path, out)

    background_tasks.add_task(run)
    j = {k:v for k,v in jobs[job_id].items() if k != "bg_mode"}
    return JobStatus(**j)

@app.get("/status/{job_id}", response_model=JobStatus)
async def get_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Job niet gevonden")
    j = {k:v for k,v in jobs[job_id].items() if k != "bg_mode"}
    return JobStatus(**j)

@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    jobs.pop(job_id, None)
    shutil.rmtree(OUTPUT_DIR / job_id, ignore_errors=True)
    return {"deleted": job_id}

app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")

@app.get("/", response_class=HTMLResponse)
async def frontend():
    for c in [
        BASE_DIR.parent / "frontend" / "index.html",
        BASE_DIR.parent / "index.html",
        Path.cwd() / "frontend" / "index.html",
    ]:
        if c.exists():
            return c.read_text(encoding="utf-8")
    return HTMLResponse("<h1>FREE3D</h1><a href='/docs'>API docs</a>")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)

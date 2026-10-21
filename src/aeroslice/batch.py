from __future__ import annotations
from datetime import datetime
from pathlib import Path
import re
import uuid
from .core import Context, Cancelled, Options, write_json, sha256
from .fileio import load_model, export_model
from .converters import convert


def unique_folder(root, prefix="run"):
    return Path(root) / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"


def set_roles(model, mapping=None, open_role=None):
    for i, part in enumerate(model.parts):
        role = (mapping or {}).get(str(i), (mapping or {}).get(part.name))
        if role is None and open_role and not part.mesh.is_watertight:
            role = open_role
        if role:
            if role not in ("auto", "solid", "shell", "sheet", "keep"):
                raise ValueError(f"未知类型：{role}")
            part.role = role


def save_conversion(result, folder, fmt="3mf", separate=False, ctx=None, *,
                    write_report=True, output_name="converted", auto_number=False):
    from .core import Model
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    paths, warnings = [], []

    def destination(name):
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)[:90].strip(". ") or "converted"
        path = folder / f"{name}.{fmt}"
        if auto_number:
            index = 2
            while path.exists():
                path = folder / f"{name}_{index}.{fmt}"
                index += 1
        return path

    try:
        if separate:
            for i, part in enumerate(result.model.parts):
                name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", part.name)[:90].strip(". ") or "part"
                path = destination(f"{i+1:03}_{name}")
                warnings += export_model(Model([part], result.model.source,metadata=result.model.metadata.copy()), path, ctx=ctx)
                paths.append(path)
        else:
            path = destination(output_name)
            warnings += export_model(result.model, path, ctx=ctx)
            paths.append(path)
        # Read actual outputs again. Face count and bounds are tested after serialization.
        checks = []
        for path in paths:
            reread = load_model(path, ctx, max_faces=max(750_000, sum(len(p.mesh.faces) for p in result.model.parts)*2), split=False)
            checks.append(dict(file=str(path), sha256=sha256(path), readable=True,
                               faces=len(reread.mesh.faces), bounds_mm=reread.mesh.bounds.tolist(),
                               watertight=bool(reread.mesh.is_watertight)))
        result.report["export"] = {"files": checks, "warnings": sorted(set(warnings))}
    except Exception as e:
        result.report["export"] = {"status": "failed", "error": str(e), "written_files": [str(p) for p in paths]}
        if write_report:write_json(folder / "conversion_report.json", result.report)
        raise
    if write_report:write_json(folder / "conversion_report.json", result.report)
    return paths


def process_file(path, output, options=None, fmt="3mf", roles=None, open_role=None, separate=False, ctx=None, *, write_report=True):
    options, ctx = options or Options(), ctx or Context()
    digest = sha256(path)
    model = load_model(path, ctx, options.max_faces,split=options.reconstruction!='layered')
    set_roles(model, roles, open_role)
    if options.reconstruction=='continuous':
        from .ready import convert_ready
        result=convert_ready(model,options,ctx)
    else:result = convert(model, options, ctx)
    result.report.update(source_file=str(Path(path).resolve()), source_file_sha256=digest,
                         source_file_unchanged=(digest == sha256(path)))
    paths = save_conversion(result, output, fmt, separate, ctx, write_report=write_report)
    return result, paths


def run_batch(files, root, options=None, fmt="3mf", roles=None, open_role=None, ctx=None, *, write_reports=True):
    ctx = ctx or Context()
    folder = unique_folder(root, "batch")
    folder.mkdir(parents=True)
    entries = []
    try:
        for i, file in enumerate(files):
            ctx.check(int(i / max(len(files), 1)*100), f"批量 {i+1}/{len(files)} {Path(file).name}")
            dest = folder / f"{i+1:03}_{Path(file).stem}"
            dest.mkdir()
            try:
                result, paths = process_file(file, dest, options, fmt, roles, open_role, ctx=ctx, write_report=write_reports)
                entry = dict(source=str(file), status=result.report["status"], files=[str(p) for p in paths])
            except Cancelled:
                entries.append(dict(source=str(file), status="cancelled"))
                raise
            except Exception as e:
                entry = dict(source=str(file), status="failed", error=f"{type(e).__name__}: {e}")
                if write_reports:write_json(dest / "error.json", entry)
            entries.append(entry)
            if write_reports:write_json(folder / "batch_report.json", {"entries": entries, "completed": False})
    finally:
        if write_reports:write_json(folder / "batch_report.json", {"entries": entries, "completed": len(entries)==len(files) and not ctx.cancel.is_set(),
                   "remaining": [str(p) for p in files[len(entries):]], "output_folder": str(folder)})
    return {"entries": entries, "output_folder": str(folder)}

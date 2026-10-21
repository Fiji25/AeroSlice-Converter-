"""Geometry-only 3MF core / production-component reader. No archive extraction."""
from __future__ import annotations
from pathlib import Path, PurePosixPath
from urllib.parse import unquote
from tempfile import NamedTemporaryFile
import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from defusedxml import ElementTree as SafeET
import numpy as np
import trimesh
from .core import Model, Part, Context, GeometryError
from . import __version__
from .geometry import canonical, patches, topology, component_count

CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PROD = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
UNITS = dict(micron=.001, millimeter=1., centimeter=10., inch=25.4, foot=304.8, meter=1000.)
MAX_FILE = 512 * 1024 * 1024
MAX_XML = 384 * 1024 * 1024
MAX_UNPACKED = 768 * 1024 * 1024


def safe_member(name):
    name = unquote(name)
    p = PurePosixPath(name)
    if "\\" in name or ":" in name or name.startswith("/") or ".." in p.parts or not p.parts:
        raise GeometryError(f"3MF含非法路径：{name[:100]}")
    return p.as_posix()


def member_reference(path, parent=""):
    # OPC absolute part names begin with '/'; archive entry names may not.
    return safe_member(path[1:] if path.startswith("/") else str(PurePosixPath(parent).parent / path))


def _transform(text, scale):
    if not text:
        return np.eye(4)
    a = np.array([float(x) for x in text.split()])
    if a.size != 12 or not np.isfinite(a).all():
        raise GeometryError("3MF变换矩阵无效")
    m = np.eye(4)
    m[:3, :] = a.reshape(4, 3).T
    m[:3, 3] *= scale
    if abs(np.linalg.det(m[:3, :3])) < 1e-12:
        raise GeometryError("3MF含奇异变换")
    return m


def _xml(z, name):
    info = z.getinfo(name)
    if info.file_size > MAX_XML:
        raise GeometryError("单个XML超过384 MiB限制")
    return SafeET.fromstring(z.read(name), forbid_dtd=True, forbid_entities=True, forbid_external=True)


def read_3mf(path, ctx=None, max_faces=750_000):
    ctx = ctx or Context()
    warnings, parts, raw, cache = [], [], [], {}
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if len(infos) > 10000 or sum(i.file_size for i in infos) > MAX_UNPACKED:
            raise GeometryError("3MF展开大小或成员数超过安全限制")
        names = [safe_member(i.filename) for i in infos]
        for info in infos:
            safe_member(info.orig_filename)  # ZipInfo normalizes Windows backslashes in filename.
        if len(set(n.casefold() for n in names)) != len(names):
            raise GeometryError("3MF含重名成员")
        for info in infos:
            if info.flag_bits & 1 or (info.file_size > 1024 * 1024 and info.file_size / max(info.compress_size, 1) > 1000):
                raise GeometryError("加密或异常高压缩比的3MF不受支持")
        roots = []
        if "_rels/.rels" in names:
            rels = _xml(z, "_rels/.rels")
            for r in rels:
                if r.get("Type", "").endswith("/3dmodel"):
                    if r.get("TargetMode") == "External":
                        raise GeometryError("禁止外部3MF模型引用")
                    roots.append(member_reference(r.get("Target", "")))
        if not roots and "3D/3dmodel.model" in names:
            roots = ["3D/3dmodel.model"]
        if len(roots) != 1:
            raise GeometryError("无法唯一确定3MF主模型")
        proprietary = [n for n in names if n.lower().startswith("metadata/") and not n.lower().endswith((".png", ".jpg"))]
        if proprietary:
            warnings.append("检测到切片器工程数据，不会保留打印配置/盘号/支撑/涂色等：" + ", ".join(proprietary[:8]))

        def document(name):
            if name in cache:
                return cache[name]
            ctx.check()
            root = _xml(z, name)
            if root.tag != f"{{{CORE}}}model":
                raise GeometryError("不支持的3MF核心命名空间")
            # Resolve required extension prefixes, rejecting unknown required semantics.
            text = z.read(name)
            nsmap = {a.decode(): b.decode() for a, b in re.findall(rb'xmlns:([\w]+)=[\"\']([^\"\']+)[\"\']', text[:65536])}
            for prefix in root.get("requiredextensions", "").split():
                if nsmap.get(prefix) != PROD:
                    raise GeometryError(f"不能安全解释3MF必需扩展：{prefix}")
            unit = root.get("unit", "millimeter")
            if unit not in UNITS:
                raise GeometryError(f"未知3MF单位：{unit}")
            scale = UNITS[unit]
            if scale != 1:
                warnings.append(f"{name} 单位 {unit}，已按规范换算为mm（未改变物理尺寸）")
            objects = {}
            resources = root.find(f"{{{CORE}}}resources")
            if resources is None:
                raise GeometryError("3MF缺少resources")
            for obj in resources.findall(f"{{{CORE}}}object"):
                oid = obj.get("id")
                if oid in objects:
                    raise GeometryError("3MF对象ID重复")
                objects[oid] = obj
            if any(el.tag.split("}")[-1] not in ("object",) for el in resources):
                warnings.append("3MF材质/颜色/其他资源仅识别几何，不保留其语义")
            if any(any(k.startswith("{") for k in t.attrib) for t in root.iter(f"{{{CORE}}}triangle")):
                warnings.append("3MF三角面包含扩展属性；输出仅保留几何")
            cache[name] = (root, objects, scale)
            return cache[name]

        total_faces = 0
        def visit(name, oid, matrix, group, stack):
            nonlocal total_faces
            ctx.check()
            key = (name, oid)
            if key in stack or len(stack) > 64:
                raise GeometryError("3MF组件循环引用或嵌套过深")
            root, objects, scale = document(name)
            if oid not in objects:
                raise GeometryError(f"3MF对象引用不存在：{oid}")
            obj = objects[oid]
            mesh = obj.find(f"{{{CORE}}}mesh")
            if mesh is not None:
                ve, tr = mesh.find(f"{{{CORE}}}vertices"), mesh.find(f"{{{CORE}}}triangles")
                if ve is None or tr is None or len(tr) + total_faces > max_faces:
                    raise GeometryError("无效网格或展开实例后的面数超过限制")
                v = np.array([[float(e.get(a, "nan")) for a in ("x", "y", "z")] for e in ve]) * scale
                f = np.array([[int(e.get(a, "-1")) for a in ("v1", "v2", "v3")] for e in tr], dtype=np.int64)
                m = canonical(trimesh.Trimesh(v, f, process=False))
                m.apply_transform(matrix)
                raw.append(topology(m))
                parts.append(Part(obj.get("name", f"对象{oid}"), m, group, source_id=f"{name}#{oid}"))
                total_faces += len(f)
                if len(parts) > 10000:
                    raise GeometryError("展开实例数超过限制")
            components = obj.find(f"{{{CORE}}}components")
            if components is not None:
                for component in components:
                    target = component.get(f"{{{PROD}}}path")
                    child_name = member_reference(target, name) if target else name
                    visit(child_name, component.get("objectid"), matrix @ _transform(component.get("transform"), scale),
                          group, stack + [key])
            if mesh is None and components is None:
                raise GeometryError("3MF含不支持的非网格对象")

        root, _, scale = document(roots[0])
        layered=None
        for meta in root.findall(f'{{{CORE}}}metadata'):
            if meta.get('name')=='AeroSlice:layered_requirements':
                layered=json.loads(meta.text or '{}')
                warnings.append('逐层成品：请保持标注层高、原Z方向及Even-Odd；不要重复重建')
        build = root.find(f"{{{CORE}}}build")
        if build is None:
            raise GeometryError("3MF缺少build")
        for i, item in enumerate(build):
            if item.get("printable", "1") in ("0", "false"):
                warnings.append("非打印实例也已保留；请手动选择输出对象")
            visit(roots[0], item.get("objectid"), _transform(item.get("transform"), scale), f"build_{i}", [])
    if not parts:
        raise GeometryError("3MF没有可读取的构建实例")
    metadata={"raw_topology": raw, "geometry_only": True, "unit": "millimeter"}
    if layered:metadata['layered_requirements']=layered
    return Model(parts, str(Path(path).resolve()), list(dict.fromkeys(warnings)),metadata)


def load_model(path, ctx=None, max_faces=750_000, split=True):
    path = Path(path)
    ctx = ctx or Context()
    ctx.check(0, f"读取 {path.name}")
    if path.stat().st_size > MAX_FILE:
        raise GeometryError("输入文件超过512 MiB安全限制")
    if path.suffix.lower() == ".3mf":
        model = read_3mf(path, ctx, max_faces)
    elif path.suffix.lower() == ".stl":
        mesh = trimesh.load_mesh(path, file_type="stl", process=False)
        if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) > max_faces:
            raise GeometryError("STL面数超过限制或文件无效")
        mesh = canonical(mesh)
        model = Model([Part(path.stem, mesh, "stl", source_id=path.stem)], str(path.resolve()),
                      ["STL没有单位声明：按毫米读取；请核对尺寸，软件不会自动缩放"],
                      {"raw_topology": [topology(mesh)], "unit": "millimeter"})
    else:
        raise GeometryError("仅支持STL和3MF")
    if split:
        model.metadata['original_component_count']=sum(component_count(p.mesh) for p in model.parts)
        separated = []
        for p in model.parts:
            ctx.check()
            ps = patches(p.mesh, manifold_only=True)
            if len(ps) > 5000:
                raise GeometryError("网格分片超过5000个；需先人工处理破碎/非流形结构")
            separated.extend(Part(f"{p.name} / {i + 1}" if len(ps) > 1 else p.name,
                                  m, p.group, source_id=p.source_id) for i, m in enumerate(ps))
        model.parts = separated
    ctx.check(10, f"已读取 {len(model.parts)} 个网格分量")
    return model


def _tag(name):
    return f"{{{CORE}}}{name}"


def export_model(model, path, source_paths=(), ctx=None):
    """Exclusive, atomic publication; source paths and existing files cannot be overwritten."""
    ctx = ctx or Context()
    path = Path(path).resolve()
    sources = [Path(p).resolve() for p in source_paths if p]
    if model.source:
        sources.append(Path(model.source).resolve())
    if path in sources or path.exists():
        raise FileExistsError("禁止覆盖源文件或已有结果，请使用新的输出文件名")
    if path.suffix.lower() not in (".3mf", ".stl"):
        raise GeometryError("输出扩展名必须为.stl或.3mf")
    if not model.parts:
        raise GeometryError("未选择导出零件")
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, suffix=".aeroslice-tmp", delete=False) as f:
        tmp = Path(f.name)
    warnings = []
    try:
        if path.suffix.lower() == ".stl":
            warnings.append("STL按毫米坐标写出；不支持多对象语义、单位声明或切片器工程参数")
            tmp.write_bytes(trimesh.exchange.stl.export_stl(model.mesh))
        else:
            ET.register_namespace("", CORE)
            root = ET.Element(_tag("model"), unit="millimeter", attrib={"{http://www.w3.org/XML/1998/namespace}lang": "zh-CN"})
            ET.SubElement(root, _tag("metadata"), name="Application").text = f"AeroSlice Converter {__version__} geometry-only"
            if requirements:=model.metadata.get('layered_requirements'):
                ET.SubElement(root,_tag('metadata'),name='AeroSlice:layered_requirements').text=json.dumps(requirements,ensure_ascii=False)
            resources, build = ET.SubElement(root, _tag("resources")), ET.SubElement(root, _tag("build"))
            for i, part in enumerate(model.parts, 1):
                ctx.check()
                obj = ET.SubElement(resources, _tag("object"), id=str(i), type="model", name=part.name)
                mesh = ET.SubElement(obj, _tag("mesh"))
                vertices, triangles = ET.SubElement(mesh, _tag("vertices")), ET.SubElement(mesh, _tag("triangles"))
                for v in part.mesh.vertices:
                    ET.SubElement(vertices, _tag("vertex"), **{a: format(float(x), ".15g") for a, x in zip(("x", "y", "z"), v)})
                for face in part.mesh.faces:
                    ET.SubElement(triangles, _tag("triangle"), **{a: str(int(x)) for a, x in zip(("v1", "v2", "v3"), face)})
                ET.SubElement(build, _tag("item"), objectid=str(i))
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
                z.writestr("_rels/.rels", f'<?xml version="1.0"?><Relationships xmlns="{REL}"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
                z.writestr("3D/3dmodel.model", ET.tostring(root, encoding="utf-8", xml_declaration=True))
        ctx.check()
        if os.name == "nt":
            os.rename(tmp, path)  # Windows MoveFile refuses an existing destination.
        else:
            os.link(tmp, path)  # Atomic exclusive publication on POSIX.
    finally:
        tmp.unlink(missing_ok=True)
    return warnings

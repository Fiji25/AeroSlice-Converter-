from __future__ import annotations
import numpy as np
from .core import Context, Options
from .geometry import patches


def sample_points(mesh, limit=1800):
    # Deterministic vertices + centroids, no random maximum-deviation claims.
    points = np.vstack([mesh.vertices, mesh.triangles_center])
    return points[np.linspace(0, len(points) - 1, min(limit, len(points)), dtype=int)]


def distances(mesh, points, ctx=None):
    ctx = ctx or Context()
    if np.any(mesh.area_faces < 1e-14):
        mesh = mesh.submesh([np.flatnonzero(mesh.area_faces >= 1e-14)], append=True, repair=False)
    result = []
    for i in range(0, len(points), 128):
        ctx.check()
        _, dist, _ = mesh.nearest.on_surface(points[i:i + 128])
        result.extend(dist)
    result = np.array(result)
    if not np.isfinite(result).all():
        raise ValueError("表面距离计算出现非有限数值，不能确认几何覆盖")
    return result


def compare(source, output, roles, options=None, ctx=None):
    options, ctx = options or Options(), ctx or Context()
    out = output.mesh
    covered, exterior, records = [], [], []
    for i, (p, role) in enumerate(zip(source.parts, roles)):
        points = sample_points(p.mesh)
        ds = distances(out, points, ctx)
        # Center sheets lie inside a thin solid, so distance to surface can be t/2.
        allowance = options.thickness * (1.05 if role == "shell" else .65) if role in ("sheet", "shell") else options.tolerance * 10
        missed = int(np.sum(ds > max(allowance, options.tolerance * 10)))
        if missed:
            covered.append(i)
        record = dict(part=i, name=p.name, role=role, samples=len(points),
                      max_distance_mm=float(ds.max()), mean_distance_mm=float(ds.mean()),
                      samples_beyond_allowance=missed, allowance_mm=allowance)
        if role in ("shell", "solid", "keep"):
            exterior.extend(ds)
            record["deviation_samples"] = {"points": points[:1000].tolist(), "distance_mm": ds[:1000].tolist()}
        records.append(record)
    ext_max = float(max(exterior)) if exterior else 0.
    original_volume = sum(abs(p.mesh.volume) for p in source.parts if p.mesh.is_volume)
    all_closed = all(p.mesh.is_volume for p in output.parts)
    volume = float(sum(abs(p.mesh.volume) for p in output.parts)) if all_closed else None
    islands = sum(len(patches(p.mesh)) for p in output.parts)
    # A closed hollow shell has two disconnected oriented boundary surfaces; count
    # via Manifold decomposition instead of claiming those are detached physical parts.
    try:
        import manifold3d as md
        physical = 0
        for p in output.parts:
            manifold = md.Manifold(md.Mesh64(np.array(p.mesh.vertices, dtype=np.float64, order="C", copy=True), np.array(p.mesh.faces, dtype=np.uint64, order="C", copy=True)))
            physical += sum(component.volume() > 1e-10 for component in manifold.decompose())
    except Exception:
        physical = None
    return dict(original_bounds_mm=source.mesh.bounds.tolist(), output_bounds_mm=out.bounds.tolist(),
                original_closed_volume_mm3=float(original_volume), output_volume_mm3=volume,
                estimated_mass_g=volume / 1000 * options.density if volume is not None else None,
                mass_conditions=f"材料密度{options.density:g}g/cm³；按实体体积估算，不代表挤出耗材；原零厚度片无实体体积",
                sampled_exterior_max_mm=ext_max,
                sampled_exterior_mean_mm=float(np.mean(exterior)) if exterior else 0.,
                exterior_within_tolerance=bool(ext_max <= max(options.tolerance * 10, .0001)),
                deviation_scope="原表面顶点和面心的确定性抽样到输出表面的距离；不保证全局Hausdorff最大值、孔槽可通性或所有相邻面折叠",
                structure_samples=records, uncovered_source_parts=covered,
                boundary_components=islands, physical_solid_components=physical,
                connections_status="布尔合并仅在同一源对象组执行；孤立实体数量供检查，不能自动判断所有连接意图",
                unintended_fill_check="未执行孔洞填充；封闭包络仅在用户指定shell时转为薄壳；孔槽与耗材仍需切片检查")

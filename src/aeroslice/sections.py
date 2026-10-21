from __future__ import annotations
import numpy as np
import trimesh
from shapely.geometry import LineString
from shapely.ops import polygonize_full, unary_union
from shapely.strtree import STRtree
from .core import Context


def section_at(mesh, z, tolerance=1e-6):
    seg = trimesh.intersections.mesh_plane(mesh, (0, 0, 1), (0, 0, z))
    if not len(seg):
        return dict(z_mm=float(z), segments=0, closed_loops=0, open_nodes=0,
                    duplicate_edges=0, crossings=0, parity_anomalies=0, nesting_depths=[])
    quant = np.rint(seg[:, :, :2] / tolerance).astype(np.int64)
    points, inverse = np.unique(quant.reshape(-1, 2), axis=0, return_inverse=True)
    edges = np.sort(inverse.reshape(-1, 2), axis=1)
    edges = edges[edges[:, 0] != edges[:, 1]]
    unique = np.unique(edges, axis=0)
    degree = np.bincount(unique.ravel(), minlength=len(points))
    lines = [LineString(points[e].astype(float) * tolerance) for e in unique]
    if not lines:
        return dict(z_mm=float(z), segments=0, closed_loops=0, open_nodes=0,
                    duplicate_edges=0, crossings=0, parity_anomalies=0, nesting_depths=[])
    tree = STRtree(lines)
    crossings = sum(lines[i].crosses(lines[int(j)]) for i in range(len(lines))
                    for j in tree.query(lines[i]) if j > i)
    polygons, cuts, dangles, invalid = polygonize_full(unary_union(lines))
    # Polygonize returns annuli plus their holes: exterior polygons recover nesting loops.
    loops = [type(p)(p.exterior) for p in polygons.geoms]
    depths = [sum(q.contains(p.representative_point()) and q.area > p.area for q in loops) for p in loops]
    return dict(z_mm=float(z), segments=len(seg), closed_loops=len(loops),
                open_nodes=int(np.sum(degree == 1)), duplicate_edges=int(len(edges) - len(unique)),
                crossings=int(crossings), parity_anomalies=int(np.sum(degree % 2)),
                junction_nodes=int(np.sum(degree > 2)), nesting_depths=depths,
                unclosed_length_mm=float(cuts.length + dangles.length + invalid.length))


def sections(mesh, count=9, tolerance=1e-6, ctx=None):
    ctx = ctx or Context()
    low, high = mesh.bounds[:, 2]
    if high - low < tolerance:
        return {"status": "coplanar_z", "layers": [], "note": "几何平行于XY平面，Z截面无法表征该曲面"}
    layers = []
    for i,z in enumerate(np.linspace(low, high, count + 2)[1:-1]):
        ctx.check(int(i*100/count),f"分析截面 {i+1}/{count}，Z={z:.3f} mm")
        layers.append(section_at(mesh, z, tolerance))
    ctx.check(100,"截面分析完成")
    return {"status": "sampled", "layers": layers,
            "note": f"仅抽样{count}个Z高度，不能保证所有层的奇偶规则或实际切片结果"}

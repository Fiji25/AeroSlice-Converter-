"""Topology, conservative manifold patches, bounded triangle intersection checks."""
from __future__ import annotations
import numpy as np
import time
import trimesh
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from shapely.geometry import Polygon
from rtree import index
from .core import Context, GeometryError


def canonical(mesh):
    m = trimesh.Trimesh(np.asarray(mesh.vertices).copy(), np.asarray(mesh.faces).copy(), process=False)
    if len(m.faces) == 0 or not np.isfinite(m.vertices).all():
        raise GeometryError("空网格或坐标含 NaN/Inf")
    if m.faces.min() < 0 or m.faces.max() >= len(m.vertices):
        raise GeometryError("三角面索引越界")
    # Exact welding only: tolerance must not close narrow slots or move source vertices.
    _, unique, inverse = np.unique(m.vertices, axis=0, return_index=True, return_inverse=True)
    m = trimesh.Trimesh(m.vertices[unique], inverse[m.faces], process=False)
    m.remove_unreferenced_vertices()
    return m


def edge_table(mesh):
    directed = mesh.faces[:, [[0, 1], [1, 2], [2, 0]]].reshape(-1, 2)
    edges, inv, counts = np.unique(np.sort(directed, axis=1), axis=0,
                                   return_inverse=True, return_counts=True)
    return edges, inv, counts, directed


def _component_labels(m, manifold_only=False):
    _, inv, counts, _ = edge_table(m)
    order = np.argsort(inv, kind="stable")
    start = np.r_[0, np.cumsum(counts)[:-1]]
    rows, cols = [], []
    for edge in np.flatnonzero(counts == 2 if manifold_only else counts >= 2):
        faces = order[start[edge]:start[edge] + counts[edge]] // 3
        rows.extend([int(faces[0])] * (len(faces) - 1))
        cols.extend(faces[1:].tolist())
    adj = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(m.faces),) * 2)
    n, labels = connected_components(adj, directed=False)
    return n,labels


def component_count(mesh):
    return int(_component_labels(mesh)[0])


def patches(mesh, manifold_only=False):
    """Never discard faces, even those attached to a non-manifold junction."""
    m=canonical(mesh)
    n,labels=_component_labels(m,manifold_only)
    return [m.submesh([np.flatnonzero(labels == i)], append=True, repair=False) for i in range(n)]


def topology(mesh):
    edges, inv, counts, directed = edge_table(mesh)
    sorted_faces = np.sort(mesh.faces, axis=1)
    duplicate = len(sorted_faces) - len(np.unique(sorted_faces, axis=0))
    order = np.argsort(inv, kind="stable")
    start = np.r_[0, np.cumsum(counts)[:-1]]
    pair = np.flatnonzero(counts == 2)
    d1 = directed[order[start[pair]]]
    d2 = directed[order[start[pair] + 1]]
    conflicts = np.all(d1 == d2, axis=1)
    return dict(vertices=len(mesh.vertices), faces=len(mesh.faces),
                open_edges=int(np.sum(counts == 1)), nonmanifold_edges=int(np.sum(counts > 2)),
                duplicate_faces=int(duplicate), degenerate_faces=int(np.sum(mesh.area_faces < 1e-14)),
                winding_conflicts=int(conflicts.sum()), watertight=bool(mesh.is_watertight),
                winding_consistent=bool(mesh.is_winding_consistent),
                bounds_mm=mesh.bounds.tolist(), size_mm=mesh.extents.tolist(),
                area_mm2=float(mesh.area),
                volume_mm3=float(abs(mesh.volume)) if mesh.is_volume else None,
                error_edges=edges[counts != 2][:1000].tolist())


def _segment_triangle(p, q, tri, tol):
    d, e1, e2 = q - p, tri[1] - tri[0], tri[2] - tri[0]
    h = np.cross(d, e2)
    a = np.dot(e1, h)
    if abs(a) <= tol * max(np.linalg.norm(e1) * np.linalg.norm(e2) * np.linalg.norm(d), 1e-20):
        return False
    s = p - tri[0]
    u = np.dot(s, h) / a
    r = np.cross(s, e1)
    v, t = np.dot(d, r) / a, np.dot(e2, r) / a
    return -tol <= u <= 1 + tol and -tol <= v and u + v <= 1 + tol and -tol <= t <= 1 + tol


def triangles_intersect(a, b, tol=1e-7):
    na, nb = np.cross(a[1] - a[0], a[2] - a[0]), np.cross(b[1] - b[0], b[2] - b[0])
    la, lb = np.linalg.norm(na), np.linalg.norm(nb)
    if min(la, lb) < 1e-14:
        return False
    na, nb = na / la, nb / lb
    if np.linalg.norm(np.cross(na, nb)) < tol:
        if abs(np.dot(b[0] - a[0], na)) > tol:
            return False
        axes = [i for i in range(3) if i != np.argmax(abs(na))]
        return Polygon(a[:, axes]).intersection(Polygon(b[:, axes])).area > tol * tol
    return any(_segment_triangle(a[i], a[(i + 1) % 3], b, tol) or
               _segment_triangle(b[i], b[(i + 1) % 3], a, tol) for i in range(3))


def self_intersections(mesh, budget=200_000, ctx=None, time_budget=5.0):
    ctx = ctx or Context()
    started=time.monotonic()
    triangles = mesh.triangles
    lo, hi = triangles.min(axis=1), triangles.max(axis=1)
    props = index.Property(dimension=3)
    tree = index.Index(((i, tuple(np.r_[lo[i], hi[i]]), None) for i in range(len(lo))), properties=props)
    hits, checked, candidates = [], 0, 0
    for i in range(len(triangles)):
        if i % 256 == 0:
            ctx.check()
        for j in tree.intersection(tuple(np.r_[lo[i] - 1e-8, hi[i] + 1e-8])):
            candidates+=1
            if candidates%128==0 and time.monotonic()-started>time_budget:
                return dict(status="partial",tested_pairs=checked,pairs=hits,
                            note="达到相交检查时间预算；尚未遍历所有候选面，不能保证无自相交")
            if j <= i or np.intersect1d(mesh.faces[i], mesh.faces[j]).size:
                continue
            if checked >= budget:
                return dict(status="partial", tested_pairs=checked, pairs=hits,
                            note="达到相交检查预算；相邻面共享顶点的折叠不在此检查范围")
            checked += 1
            if triangles_intersect(triangles[i], triangles[j]):
                hits.append([i, j])
                if len(hits) >= 200:
                    return dict(status="partial", tested_pairs=checked, pairs=hits,
                                note="至少200处相交；相邻面的折叠未检查")
    return dict(status="complete_nonadjacent", tested_pairs=checked, pairs=hits,
                note="仅检查不共享顶点的三角面；不构成所有自相交的数学证明")


def infer_role(mesh):
    if mesh.is_watertight and mesh.is_winding_consistent:
        return "solid", "A", "闭合网格；若实际为航模外皮，请手动指定外壳，避免保留为实心体"
    _, s, _ = np.linalg.svd(mesh.vertices - mesh.vertices.mean(axis=0), full_matrices=False)
    if len(s) >= 3 and s[-1] <= max(s[0], 1) * 1e-7:
        return "sheet", "C", "平面零厚度曲面；位置不能单独证明其为内部加强片"
    return "unknown", "G", "开放曲面无法可靠区分外壳与加强片，请指定类型"


def orient(mesh):
    m = mesh.copy()
    trimesh.repair.fix_winding(m)
    trimesh.repair.fix_normals(m, multibody=True)
    return m

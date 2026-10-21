"""Shared-vertex normal-plane offsets; no independent triangle prisms or hole filling."""
from __future__ import annotations
import numpy as np
import trimesh
from .core import GeometryError, Context
from .geometry import canonical, edge_table, orient, topology, self_intersections


def solidify(mesh, thickness=.45, role="sheet", tolerance=1e-6, ctx=None, budget=200_000, reverse_normals=False):
    ctx = ctx or Context()
    if not np.isfinite(thickness) or not 0.01 <= thickness <= 10:
        raise GeometryError("无效的实体化厚度")
    m = orient(canonical(mesh))
    if reverse_normals:
        m.invert()
    top = topology(m)
    if top["nonmanifold_edges"] or top["duplicate_faces"] or top["degenerate_faces"]:
        raise GeometryError("实体化要求可定向的流形曲面片；存在非流形边、重复面或退化面")
    if not m.is_winding_consistent:
        raise GeometryError("曲面不可连续定向，需人工处理")
    original_intersections = self_intersections(m, budget, ctx)
    if original_intersections["pairs"] or original_intersections["status"] == "partial":
        raise GeometryError("源曲面存在自相交或相交检查未完成，拒绝盲目加厚")
    ctx.check()
    # Solve n_face · displacement = 1 at shared vertices. Smooth normals and
    # corners share the same offset vertex; weak singular directions are truncated.
    normals = m.face_normals
    a = np.zeros((len(m.vertices), 3, 3))
    b = np.zeros((len(m.vertices), 3))
    outer = normals[:, :, None] * normals[:, None, :]
    for k in range(3):
        np.add.at(a, m.faces[:, k], outer)
        np.add.at(b, m.faces[:, k], normals)
    offset = np.einsum("nij,nj->ni", np.linalg.pinv(a, rcond=1e-3), b)
    if not np.isfinite(offset).all() or np.linalg.norm(offset, axis=1).max() > 4:
        raise GeometryError("尖角偏移超过4倍壁厚，需减小壁厚或人工处理该区域")
    if role == "shell":
        top_vertices = m.vertices.copy()
        bottom_vertices = m.vertices - thickness * offset
    elif role == "sheet":
        top_vertices = m.vertices + thickness / 2 * offset
        bottom_vertices = m.vertices - thickness / 2 * offset
    else:
        raise GeometryError("实体化类型必须为shell或sheet")
    # Detect inverted/flattened inner or outer triangles before joining boundaries.
    for v in (top_vertices, bottom_vertices):
        tri = v[m.faces]
        cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        if np.any(np.einsum("ij,ij->i", cross, normals) <= tolerance * tolerance):
            raise GeometryError("偏移导致局部面翻转/塌缩，壁厚过大或局部曲率过高")
    _, inv, counts, directed = edge_table(m)
    boundary = directed[counts[inv] == 1]
    n = len(m.vertices)
    sides = []
    for a0, b0 in boundary:
        sides.extend([[b0, a0, a0 + n], [b0, a0 + n, b0 + n]])
    faces = np.vstack([m.faces, m.faces[:, ::-1] + n, np.array(sides, dtype=int).reshape(-1, 3)])
    result = trimesh.Trimesh(np.vstack([top_vertices, bottom_vertices]), faces, process=False)
    if result.volume < 0:
        result.invert()
    if not result.is_volume or not result.is_watertight:
        raise GeometryError("生成网格未形成定向封闭实体；原始数据已保留")
    check = self_intersections(result, budget, ctx)
    if check["pairs"] or check["status"] == "partial":
        raise GeometryError("偏移结果存在自相交或未完成检查；需人工处理")
    return result


def boolean(meshes, operation="union"):
    if not all(m.is_volume for m in meshes):
        raise GeometryError("布尔运算仅接受定向封闭实体")
    try:
        import manifold3d as md
        solids = [md.Manifold(md.Mesh64(np.array(m.vertices, dtype=np.float64, order="C", copy=True),
                                       np.array(m.faces, dtype=np.uint64, order="C", copy=True))) for m in meshes]
        if any(s.status() != md.Error.NoError for s in solids):
            raise GeometryError("Manifold拒绝了输入拓扑")
        while len(solids) > 1:
            joined = []
            for i in range(0, len(solids)-1, 2):
                joined.append(solids[i] + solids[i+1] if operation == "union" else solids[i] ^ solids[i+1])
            if len(solids) % 2: joined.append(solids[-1])
            solids = joined
        result_mesh = solids[0].to_mesh64()
        out = trimesh.Trimesh(result_mesh.vert_properties[:, :3], result_mesh.tri_verts, process=False)
    except Exception as e:
        raise GeometryError(f"Manifold布尔{operation}失败：{e}") from e
    if out is None or len(out.faces) == 0 or not out.is_volume:
        raise GeometryError("布尔运算未生成有效非空实体")
    return out

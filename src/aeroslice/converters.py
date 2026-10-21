from __future__ import annotations
from dataclasses import dataclass
from collections import defaultdict
import time
import numpy as np
from .core import Model, Options, Context, GeometryError, mesh_digest
from .analysis import analyze
from .geometry import canonical, topology, orient
from .solidify import solidify, boolean
from .validation import compare


@dataclass
class Conversion:
    model: Model
    report: dict


def convert(model, options=None, ctx=None):
    options, ctx = options or Options(), ctx or Context()
    options.validate()
    if options.reconstruction=='layered':
        from .layered import convert_layered
        return convert_layered(model,options,ctx)
    if sum(len(p.mesh.faces) for p in model.parts) > options.max_faces:
        raise GeometryError("总面数超过处理限制")
    started = time.monotonic()
    hashes = [mesh_digest(p.mesh) for p in model.parts]
    if options.mode == "regular" and len(model.parts)>100 and any(t.get('nonmanifold_edges',0) for t in model.metadata.get('raw_topology',[])):
        if sum(len(p.mesh.faces)<=2 for p in model.parts)>len(model.parts)*.5:
            raise GeometryError("非流形拓扑产生大量单三角形分片，拒绝逐三角形加厚；请先处理重复/分支拓扑并确认曲面分组")
    before = analyze(model, options, ctx.scaled(0,38))
    out, actions, problems = [], [], []
    roles = []
    for p, diagnostic in zip(model.parts, before["parts"]):
        role = p.role if p.role != "auto" else diagnostic["suggested_role"]
        if options.mode == "regular" and p.role == "auto" and diagnostic["category"] == "E":
            if not options.confirm_ambiguous:
                raise GeometryError(f"{p.name} 包围内部开放片：请明确指定外壳shell或实体solid，避免把机翼变成实心")
            role = "shell"
            actions.append(f"用户允许推断：{p.name} 按外壳向内加厚")
        if role == "unknown" and options.mode == "regular":
            raise GeometryError(f"{p.name} 无法判断外壳或加强片；请在零件树指定类型")
        roles.append(role)
    for i, (p, role) in enumerate(zip(model.parts, roles)):
        ctx.check(40 + int(30 * i / len(model.parts)), f"{options.mode}：{p.name}")
        m = p.mesh.copy()
        if options.mode == "even-odd":
            if role == "keep":
                out.append(p.copy(m))
                actions.append(f"{p.name} 按用户选择原样保留")
                continue
            if options.repair:
                # Remove same-orientation duplicates only; opposing coincident faces
                # can represent intended double surfaces and require manual review.
                cyc = np.stack([np.roll(m.faces, j, axis=1) for j in range(3)])
                start = np.argmin(m.faces, axis=1)
                canonical_faces = np.array([np.roll(f, -s) for f, s in zip(m.faces, start)])
                _, keep = np.unique(canonical_faces, axis=0, return_index=True)
                removed = len(m.faces) - len(keep)
                m.update_faces(np.sort(keep))
                m.remove_unreferenced_vertices()
                m = orient(m)
                if removed:
                    actions.append(f"{p.name} 删除{removed}个同向完全重复面，未移动顶点")
            if not m.is_watertight:
                problems.append(f"{p.name}：该结构无法直接通过Even-Odd规则保留，建议进行薄壁实体化")
            out.append(p.copy(m))
        elif role in ("sheet", "shell"):
            m = solidify(m, options.thickness, role, options.tolerance, ctx, options.intersection_budget,
                         options.reverse_shell_normals if role == "shell" else False)
            if role == "sheet":
                envelopes = [q.mesh for j, q in enumerate(model.parts)
                             if q.group == p.group and roles[j] == "shell" and q.mesh.is_volume]
                for envelope in envelopes:
                    if envelope.contains(p.mesh.centroid.reshape(1, 3))[0]:
                        m = boolean([m, orient(envelope)], "intersection")
                        actions.append(f"{p.name} 已用闭合外壳包络裁剪，防止外露；需检查孔槽")
                        break
            out.append(p.copy(m))
            actions.append(f"{p.name} {role} 实体化 {options.thickness:g} mm；原始面数 {len(p.mesh.faces)}")
        elif role in ("solid", "keep"):
            if role == "keep" and not m.is_volume:
                problems.append(f"{p.name} 按用户选择保留开放几何，Regular结果需要人工确认")
            out.append(p.copy(m))
            actions.append(f"{p.name} 原样保留")
        else:
            raise GeometryError(f"不支持的类型：{role}")
    ctx.check(72, "处理薄壁连接")
    if options.mode == "regular" and options.merge:
        groups = defaultdict(list)
        untouched = []
        for p in out:
            if p.role == "keep": untouched.append(p)
            else: groups[p.group].append(p)
        joined = untouched
        for group, parts in groups.items():
            ctx.check()
            if len(parts) > 1 and all(p.mesh.is_volume for p in parts):
                m = boolean([p.mesh for p in parts])
                joined.append(parts[0].copy(m))
                joined[-1].name = parts[0].name.split(" / ")[0] + " [薄壁组合]"
                joined[-1].role = "solid"
                actions.append(f"{group} 内 {len(parts)} 个实体布尔并集；未合并不同build实例")
            else:
                joined.extend(parts)
        out = joined
    result = Model(out, model.source, model.warnings.copy(), {"mode": options.mode})
    after = analyze(result, options, ctx.scaled(75,89))
    ctx.check(90, "比较原始几何与转换结果")
    comparison = compare(model, result, roles, options, ctx)
    bad = any(p["topology"]["nonmanifold_edges"] or p["topology"]["duplicate_faces"] or
              p["topology"]["degenerate_faces"] or not p["topology"]["winding_consistent"] or
              p["self_intersections"]["pairs"] or p["self_intersections"]["status"] == "partial"
              for p in after["parts"])
    complete = all(p["topology"]["watertight"] for p in after["parts"])
    if options.mode == "even-odd":
        recommended = complete and not bad and not any(l["open_nodes"] or l["crossings"] or l["duplicate_edges"]
                         for l in after["sections"]["layers"])
        problems.append("目标切片器仍需手动启用Even-Odd/奇偶切片规则；文件不能强制其生效。截面仅为抽样验证。")
    else:
        recommended = False
    if bad or (options.mode == "regular" and not complete):
        problems.append("输出仍有未解决网格异常或开放片，需人工确认")
    if comparison["uncovered_source_parts"]:
        problems.append("部分源结构偏离输出实体/表面超过允许范围，请检查结构保留情况")
    if not comparison["exterior_within_tolerance"]:
        problems.append("采样外表面偏差超出设定精度，请检查偏差颜色和报告")
    assert hashes == [mesh_digest(p.mesh) for p in model.parts], "转换修改了源网格"
    report = dict(mode=options.mode, thickness_mm=options.thickness, options=options.__dict__,
                  status="needs_review" if bad or not complete or comparison["uncovered_source_parts"] or not comparison["exterior_within_tolerance"] else "geometry_passed",
                  before=before, after=after, comparison=comparison, actions=actions,
                  issues=problems, even_odd_recommended=recommended,
                  source_mesh_sha256=hashes, source_mesh_unchanged=True,
                  structure_loss="未删除任何源分量；几何覆盖通过采样检查，非全局证明",
                  elapsed_seconds=round(time.monotonic() - started, 3),
                  slicer_validation={"status": "not_run", "note": "几何验证通过不等于切片或打印成功"})
    ctx.check(100, f"完成：{report['status']}")
    return Conversion(result, report)

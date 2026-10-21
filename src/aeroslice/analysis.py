from __future__ import annotations
import numpy as np
import time
from rtree import index
from .core import Context, Options
from .geometry import topology, infer_role, component_count, self_intersections
from .sections import sections


def analyze(model, options=None, ctx=None, quick=False):
    options, ctx = options or Options(), ctx or Context()
    reports = []
    intersection_deadline=time.monotonic()+30
    for i, part in enumerate(model.parts):
        ctx.check(int(60 * i / len(model.parts)), f"诊断 {part.name}")
        top = topology(part.mesh)
        role, category, reason = infer_role(part.mesh)
        remaining=intersection_deadline-time.monotonic()
        intersections = (dict(status='not_run_import',tested_pairs=0,pairs=[],note='导入仅快速诊断；导出时执行实体化与验证') if quick else
                         self_intersections(part.mesh, options.intersection_budget, ctx, min(5.,remaining))
                         if remaining>0 else dict(status="partial",tested_pairs=0,pairs=[],note="本次诊断的30秒相交检查预算已用完；本分量未完成自相交检查"))
        if top["nonmanifold_edges"] or intersections["pairs"]:
            category = "F"
        reports.append(dict(name=part.name, group=part.group, source_id=part.source_id,
                            selected_role=part.role, suggested_role=role, category=category,
                            reason=reason, topology=top, self_intersections=intersections))
    ctx.check(60,"分析对象位置与包含关系")
    relations = []
    boxes=[p.mesh.bounds for p in model.parts]
    props=index.Property(dimension=3)
    spatial=index.Index(((i,tuple(np.r_[b[0]-options.tolerance,b[1]+options.tolerance]),None) for i,b in enumerate(boxes)),properties=props)
    relationship_candidates=0
    relationship_complete=True
    for i, a in enumerate(model.parts):
        for j in spatial.intersection(tuple(np.r_[boxes[i][0]-options.tolerance,boxes[i][1]+options.tolerance])):
            if j<=i:continue
            relationship_candidates+=1
            if relationship_candidates%32==0:
                ctx.check(60+min(14,relationship_candidates*14//5000),f"分析对象关系：已检查 {relationship_candidates} 对")
            if relationship_candidates>5000:
                relationship_complete=False
                break
            b = model.parts[j]
            if np.all(np.minimum(a.mesh.bounds[1], b.mesh.bounds[1]) >= np.maximum(a.mesh.bounds[0], b.mesh.bounds[0]) - options.tolerance):
                relation = {"parts": [i, j], "relation": "bbox_overlap_unconfirmed"}
                # Bounding box overlap is never reported as a proven solid intersection.
                for outer, inner, oi in ((a, b, i), (b, a, j)):
                    if outer.mesh.is_volume and not quick:
                        try:
                            sample = inner.mesh.vertices[np.linspace(0, len(inner.mesh.vertices) - 1, min(100, len(inner.mesh.vertices)), dtype=int)]
                            if outer.mesh.contains(sample).any():
                                relation.update(relation="sampled_containment_or_overlap", enclosing_part=oi)
                                if not inner.mesh.is_watertight:
                                    reports[oi]["category"] = "E"
                                    reports[oi]["reason"] = "闭合表面包围开放片：若为薄壁外壳必须指定shell，不能按实心体处理"
                        except Exception as e:
                            relation["containment_error"] = str(e)
                relations.append(relation)
        if not relationship_complete:break
    ctx.check(75,"汇总连通分量与尺寸")
    mesh = model.mesh
    patch_open=sum(p["topology"]["open_edges"] for p in reports)
    patch_nonmanifold=sum(p["topology"]["nonmanifold_edges"] for p in reports)
    source_topology=model.metadata.get('raw_topology',[])
    connected=sum(component_count(p.mesh) for p in model.parts)
    section_report=sections(mesh,options.section_count,options.tolerance,ctx.scaled(80,99))
    ctx.check(100,"几何诊断完成")
    return dict(parts=reports, relationships=relations,
                component_count=model.metadata.get('original_component_count',connected),
                patch_component_count=len(model.parts),patch_open_edges=patch_open,patch_nonmanifold_edges=patch_nonmanifold,
                relationship_check='import_bbox_only' if quick else "bbox_candidates_sampled_contains" if relationship_complete else "partial_5000_pair_limit",
                connected_components=connected,
                open_edges=sum(t['open_edges'] for t in source_topology) if source_topology else patch_open,
                nonmanifold_edges=sum(t['nonmanifold_edges'] for t in source_topology) if source_topology else patch_nonmanifold,
                source_topology=model.metadata.get("raw_topology", []),
                bounds_mm=mesh.bounds.tolist(), sections=section_report,
                warnings=model.warnings)

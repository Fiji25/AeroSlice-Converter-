"""Fixed-Z Surface cross-sections buffered and extruded as closed layer slabs.

This is the initial StartUP route, not G-code inversion or a smooth 3D offset.
Layer interfaces deliberately touch. Never boolean-union the complete stack:
it costs time and changes the Even-Odd interpretation at the locked layer planes.
"""
from collections import defaultdict
import math,time
import numpy as np
import trimesh,shapely,manifold3d as md
from .core import Model,Part,Context,Options,GeometryError,mesh_digest
from .converters import Conversion
from .geometry import topology


def layer_region(segments,width,diagnostics=None):
    xy=np.round(np.asarray(segments)[:,:,:2],6)
    xy=xy[np.linalg.norm(xy[:,1]-xy[:,0],axis=1)>1e-7]
    if not len(xy):return None,None
    raw=shapely.multilinestrings(xy)
    lines=shapely.line_merge(raw)
    # Bound curve simplification well below one nozzle line, preserving branches.
    lines=shapely.simplify(lines,.005,preserve_topology=True)
    region=shapely.buffer(lines,width/2,quad_segs=2,cap_style='flat',join_style='mitre')
    region=shapely.simplify(region,.002,preserve_topology=True)
    if region.is_empty or not region.is_valid:
        raise GeometryError('截面缓冲未生成有效材料区域，已停止')
    # Every raw section segment is checked, rather than checking a few layers.
    coverage=shapely.buffer(region,.008,quad_segs=1)
    if not shapely.covers(coverage,raw):
        # Merged, nearly reversing short branches can cause a stroke buffer to
        # trim a neighbouring source segment. Restore only the original segment
        # strokes that failed coverage, at the same requested material width.
        # Union adds no material outside those strokes and removes none of the
        # existing region. The unchanged full-section check must pass afterward.
        original_segments=shapely.linestrings(xy)
        missing=~shapely.covers(coverage,original_segments)
        patches=shapely.buffer(shapely.multilinestrings(xy[missing]),width/2,
            quad_segs=2,cap_style='flat',join_style='mitre')
        repaired=shapely.union(region,patches)
        if repaired.is_empty or not repaired.is_valid or not shapely.covers(
                shapely.buffer(repaired,.008,quad_segs=1),raw):
            raise GeometryError('逐层轮廓覆盖核对失败，已停止导出')
        if diagnostics is not None:
            diagnostics.update(coverage_repaired=True,coverage_repair_segments=int(missing.sum()),
                coverage_repair_added_area_mm2=float(repaired.area-region.area))
        region=repaired
    return region,raw


def extrude_region(region,z0,height):
    polygons=[region] if region.geom_type=='Polygon' else list(region.geoms)
    contours=[]
    for polygon in polygons:
        if polygon.geom_type!='Polygon':raise GeometryError('截面含非多边形几何')
        polygon=shapely.geometry.polygon.orient(polygon,sign=1)
        contours.append(np.asarray(polygon.exterior.coords)[:-1])
        contours.extend(np.asarray(r.coords)[:-1] for r in polygon.interiors)
    solid=md.CrossSection(contours,md.FillRule.Positive).extrude(height)
    if solid.status()!=md.Error.NoError or solid.is_empty():
        raise GeometryError('单层材料区域挤出失败')
    data=solid.to_mesh64()
    vertices=np.array(data.vert_properties[:,:3],copy=True);vertices[:,2]+=z0
    result=trimesh.Trimesh(vertices,np.array(data.tri_verts,copy=True),process=False)
    if not result.is_volume:raise GeometryError('单层未形成封闭实体')
    return result


def _summary(parts,source=False):
    reports=[]
    for p in parts:
        t=topology(p.mesh)
        reports.append(dict(name=p.name,topology=t,self_intersections=dict(
            status='not_run_source' if source else 'valid_planar_extrusions',pairs=[],
            note='逐层有效多边形+正高度封闭挤出；相邻层接触面保留，未做整栈自交证明')))
    return dict(parts=reports,open_edges=sum(p['topology']['open_edges'] for p in reports),
        nonmanifold_edges=sum(p['topology']['nonmanifold_edges'] for p in reports),
        component_count=len(parts),connected_components=len(parts),
        component_count_scope='输入/输出对象数；未执行整栈连通分量搜索')


def convert_layered(model,options=None,ctx=None):
    options=options or Options(mode='even-odd',reconstruction='layered')
    options.validate();ctx=ctx or Context();started=time.monotonic()
    if model.metadata.get('layered_requirements'):
        raise GeometryError('这个3MF已经是逐层成品；请直接导入切片器，或重新导入原始模型转换')
    hashes=[mesh_digest(p.mesh) for p in model.parts]
    if sum(len(p.mesh.faces) for p in model.parts)>options.max_faces:
        raise GeometryError('输入总面数超过处理限制')
    h=options.layer_height;groups=defaultdict(list);output=[];records=[];total_faces=0
    for p in model.parts:
        if p.role in ('keep','solid'):
            # In the Surface-input workflow even a watertight mesh represents
            # printed surface paths, not necessarily a filled ordinary solid.
            # Preserve material volumes only after an explicit user selection.
            from .ready import _native
            from meshlib import mrmeshpy as mm
            if not p.mesh.is_volume or mm.findSelfCollidingTriangles(mm.MeshPart(_native(p.mesh))):
                action='请勾选该零件的转换复选框，并将结构类型改为“Surface 自动重建”（旧版“自动判断”），再导出。' if p.role=='keep' else '请将左侧结构类型改为“Surface 自动重建”（旧版“自动判断”），再导出。'
                raise GeometryError(f'{p.name} 无法作为有效封闭实体原样保留；当前设置会跳过Surface重建。{action}')
            output.append(p.copy())
        else:groups[p.group].append(p)
    base=float(model.mesh.bounds[0,2])
    for group_index,(group,parts) in enumerate(groups.items()):
        mesh=trimesh.util.concatenate([p.mesh for p in parts]);lo,hi=mesh.bounds[:,2]
        if hi-lo<1e-7:
            raise GeometryError('纯水平零厚度曲面无法用逐层轮廓重建，请选择连续曲面方式')
        first=max(0,int(math.floor((lo-base)/h)))
        # Only layers whose *centre* intersects the source can be printed at
        # this fixed height. Avoid tiny, unprintable remainder slabs at the top.
        last=int(math.ceil((hi-base)/h-.5-1e-7))
        if last-first>10000:raise GeometryError('重建超过10000层，请检查模型单位或提高层高')
        zverts=mesh.vertices[:,2];zf=zverts[mesh.faces]
        lower=zf.min(axis=1);upper=zf.max(axis=1)
        layers=[];meshes=[]
        for index in range(first,last):
            z0=base+index*h;z1=base+(index+1)*h;sample=z0+h/2
            ctx.check(int(5+80*(group_index+(index-first)/max(1,last-first))/len(groups)),
                f'逐层轮廓 {parts[0].name}：{index-first+1}/{last-first} 层')
            active=np.flatnonzero((lower<=sample)&(upper>=sample))
            if not len(active):continue
            segments=trimesh.intersections.mesh_plane(mesh,(0,0,1),(0,0,sample),
                local_faces=active,cached_dots=zverts-sample)
            if not len(segments):continue
            diagnostics={}
            try:region,raw=layer_region(segments,options.thickness,diagnostics)
            except GeometryError as error:
                raise GeometryError(f'{parts[0].name} 第{index+1}层（Z={sample:.6f} mm）：{error}') from error
            if region is None:continue
            slab=extrude_region(region,z0,z1-z0);total_faces+=len(slab.faces)
            if total_faces>3_000_000:
                raise GeometryError('逐层网格超过300万面限制；请提高重建层高或分件导出')
            meshes.append(slab)
            layer=dict(index=index+1,sample_z_mm=sample,z0_mm=z0,z1_mm=z1,
                segments=len(segments),source_length_mm=float(raw.length),material_area_mm2=float(region.area),
                raw_section_covered=True,closed_slab=True,faces=len(slab.faces),coverage_repaired=False)
            layer.update(diagnostics);layers.append(layer)
        if not meshes:raise GeometryError(f'{parts[0].name} 没有可重建的截线，请检查方向或选择连续曲面方式')
        result=trimesh.util.concatenate(meshes)
        output.append(Part(parts[0].name+' [逐层成品]',result,group,'solid'))
        records.append(dict(name=parts[0].name,group=group,layers=layers,layer_count=len(layers),
            faces=len(result.faces),all_sections_covered=True,xy_check_tolerance_mm=.008,
            coverage_repaired_layers=sum(layer['coverage_repaired'] for layer in layers)))
    ctx.check(87,'核对逐层结果与源文件')
    if hashes!=[mesh_digest(p.mesh) for p in model.parts]:raise GeometryError('源几何发生变化')
    result_model=Model(output,model.source,model.warnings.copy(),dict(layered_requirements=dict(
        method='layered_sections',layer_height_mm=h,z_origin_mm=base,line_width_mm=options.thickness,
        slicing_mode='even_odd',recommended_wall_generator='arachne',wall_loops=1,infill_percent=100,
        top_layers=0,bottom_layers=0,preserve_z_direction=True,adaptive_layers=False)))
    before=_summary(model.parts,True);after=_summary(output)
    volume=sum(abs(p.mesh.volume) for p in output)
    constraints=[f'必须使用Even-Odd、固定{h:g}mm层高及原Z方向；禁止自动旋转、缩放和自适应层高',
        '采用层中间截线重建，Z尺寸量化到整层（端部最多约半层偏差），表面有阶梯和相邻层接触面；小于层高的细节及水平薄片不保证保留',
        '整栈封顶面接触为本方法的预期结构；不要用自动修复/整栈布尔合并处理',
        '每层原始截线在0.008mm容差内覆盖检查通过；未证明真实切片刀路或物理打印完整']
    comparison=dict(original_bounds_mm=model.mesh.bounds.tolist(),output_bounds_mm=result_model.mesh.bounds.tolist(),
        sampled_exterior_max_mm=options.thickness/2,sampled_exterior_mean_mm=0.,
        exterior_deviation_scope='XY截线缓冲半宽；非3D外形距离统计',
        output_volume_mm3=volume,estimated_mass_g=volume/1000*options.density,
        mass_conditions=f'材料密度{options.density:g}g/cm³；按各层材料体积估算，实际耗材以切片为准',
        physical_solid_components=None,uncovered_source_parts=[],exterior_within_tolerance=None)
    report=dict(status='geometry_passed',method='layered_sections',mode='even-odd',
        options=options.__dict__,thickness_mm=options.thickness,layer_height_mm=h,
        elapsed_seconds=round(time.monotonic()-started,3),before=before,after=after,comparison=comparison,
        actions=['逐层截取外皮及筋板，缓冲为材料区域，再逐层封闭挤出；未填满机翼空腔'],
        issues=constraints,reconstruction=records,even_odd_recommended=True,
        source_mesh_sha256=hashes,source_mesh_unchanged=True,structure_loss=constraints[1],
        slicer_validation=dict(status='not_run',note='逐层几何通过不等于实际切片通过'),
        validation_scope='逐层截线覆盖、有效多边形、封闭挤出；允许相邻层接触面')
    repaired_count=sum(record['coverage_repaired_layers'] for record in records)
    if repaired_count:
        report['actions'].append(f'{repaired_count}层局部短截线以原始线段缓冲补回；壁厚及0.008mm覆盖检查容差保持不变，全部截线复核通过')
    ctx.check(100,'逐层重建完成')
    return Conversion(result_model,report)

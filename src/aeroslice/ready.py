"""One-click export: exact closed meshes or bounded unsigned-distance thin walls.

Unsigned distance thickens the original surfaces, including internal sheets. It
does not classify the enclosed aircraft cavity as material or cap its openings.
Reconstruction is approximate and moves exterior surfaces by half the thickness.
"""
from collections import defaultdict
import itertools
import time
import numpy as np
import trimesh
from .core import Context,Options,Model,Part,GeometryError,mesh_digest
from .geometry import canonical,infer_role,topology
from .analysis import analyze
from .converters import convert,Conversion


def _native(mesh):
    from meshlib import mrmeshnumpy as mn
    result=mn.meshFromFacesVerts(np.array(mesh.faces,dtype=np.int32,order='C',copy=True),
                                np.array(mesh.vertices,dtype=np.float32,order='C',copy=True))
    if result.topology.numValidFaces()!=len(mesh.faces):
        raise GeometryError('几何引擎未接收全部源三角面，已停止导出')
    return result


def _callback(ctx):
    last=[-1,0.]
    def callback(p):
        if ctx.cancel.is_set():return False
        value=int(p*100);now=time.monotonic()
        if value>last[0] or now-last[1]>.5:
            last[:]=[value,now];ctx.check(value,'处理连续曲面薄壁')
        return True
    return callback


def _clean_surface(mesh):
    m=canonical(mesh)
    cyclic=np.array([np.roll(f,-np.argmin(f)) for f in m.faces])
    _,keep=np.unique(cyclic,axis=0,return_index=True)
    removed=len(m.faces)-len(keep)
    m.update_faces(np.sort(keep));m.remove_unreferenced_vertices()
    return m,removed


def _voxel_size(area,thickness,resolution):
    voxel=min(resolution,thickness/4)
    required=np.sqrt(area/10_000_000)
    # Allow a small, reported precision adjustment when a larger aircraft part
    # only slightly exceeds the working-grid budget. Never exceed t/4.
    if voxel<required<=min(voxel*1.1,thickness/4):
        voxel=float(np.ceil(required*10000)/10000)
    if voxel<.02 or area/voxel**2>10_000_000:
        raise GeometryError('该壁厚/精度会产生过大的重建网格，请提高曲面重建精度数值或增加壁厚')
    return voxel


def _repair_generated_surface(mesh,ctx):
    """Replace only local self-intersecting patches on the generated solid."""
    from meshlib import mrmeshpy as mm
    pairs=mm.findSelfCollidingTriangles(mm.MeshPart(mesh));initial=len(pairs)
    for expand in (3,4):
        if not len(pairs):break
        ctx.check(71,f'修复生成薄壁的局部交叠：{len(pairs)} 对')
        settings=mm.SelfIntersections.Settings()
        settings.method=mm.FixSelfIntersectionMethod.CutAndFill
        settings.maxExpand=expand;settings.touchIsIntersection=False
        mm.localFixSelfIntersections(mesh,settings);ctx.check()
        pairs=mm.findSelfCollidingTriangles(mm.MeshPart(mesh))
    if len(pairs):raise GeometryError(f'生成薄壁仍有{len(pairs)}对自相交面，未导出')
    mesh.pack()
    return initial


def _rebuild(mesh,thickness,resolution,ctx):
    from meshlib import mrmeshpy as mm,mrmeshnumpy as mn
    source,duplicates=_clean_surface(mesh)
    voxel=_voxel_size(source.area,thickness,resolution)
    if voxel>resolution:ctx.check(0,f'模型较大，重建精度自适应为{voxel:.4f} mm')
    native=_native(source)
    params=mm.OffsetParameters();params.voxelSize=voxel
    params.signDetectionMode=mm.SignDetectionMode.Unsigned
    params.callBack=_callback(ctx.scaled(0,25))
    try:out=mm.offsetMesh(mm.MeshPart(native),thickness/2,params)
    except RuntimeError:
        ctx.check();raise
    ctx.check(25,'压缩曲面网格')
    # First reduce the dense distance grid conservatively. An aggressive single
    # collapse pass can fold tiny cells at intersecting walls.
    first=mm.DecimateSettings();first.maxError=min(.015,voxel*.15,thickness*.04);first.packMesh=True
    first.progressCallback=_callback(ctx.scaled(25,55))
    mm.decimateMesh(out,first);ctx.check()
    settings=mm.DecimateSettings();settings.maxError=min(.03,voxel*.3,thickness*.08)
    settings.stabilizer=.00001;settings.maxTriangleAspectRatio=40
    settings.maxAngleChange=.2;settings.minFacesInPart=12;settings.packMesh=True
    settings.progressCallback=_callback(ctx.scaled(55,70))
    mm.decimateMesh(out,settings);ctx.check()
    # Larger parts can retain many tiny cells after the first two passes. Apply
    # bounded extra reduction, then repeat the same geometry checks below.
    for error,angle in ((.04,.25),(.05,.3)):
        count=out.topology.numValidFaces()
        if count<=1_500_000:break
        ctx.check(70,f'大模型网格压缩：{count:,}面')
        settings.maxError=min(error,voxel*.5,thickness*.12)
        settings.maxAngleChange=angle
        settings.maxDeletedFaces=count-1_350_000
        settings.progressCallback=_callback(ctx.scaled(70,71))
        mm.decimateMesh(out,settings);ctx.check()
    pairs=mm.findSelfCollidingTriangles(mm.MeshPart(out))
    relaxed_pairs=len(pairs)
    if pairs:
        relaxation=mm.SelfIntersections.Settings();relaxation.method=mm.FixSelfIntersectionMethod.Relax
        relaxation.relaxIterations=5;relaxation.maxExpand=2
        mm.localFixSelfIntersections(out,relaxation);ctx.check()
    # A collapse can leave two coincident opposite triangles enclosing zero volume.
    # Remove only these generated null boundaries, never an input component.
    removed_null=0
    for component in mm.MeshComponents.getAllComponents(mm.MeshPart(out)):
        if component.count()<=2 and abs(out.volume(component))<1e-8:
            removed_null+=component.count();out.deleteFaces(component)
    out.pack()
    repaired_pairs=_repair_generated_surface(out,ctx)
    mesh_out=trimesh.Trimesh(np.array(mn.getNumpyVerts(out),copy=True),
                             np.array(mn.getNumpyFaces(out.topology),copy=True),process=False)
    # Optional local QA artifact, disabled in normal application runs.
    import os
    if cache:=os.environ.get('AEROSLICE_QA_CACHE'):
        np.savez(cache,vertices=mesh_out.vertices,faces=mesh_out.faces)
    if len(mesh_out.faces)>1_500_000:
        raise GeometryError(f'重建网格仍有{len(mesh_out.faces):,}面，超过150万面限制，未导出')
    mp,sp=mm.MeshPart(out),mm.MeshPart(native)
    ctx.check(72,'核对全部源顶点及面心')
    points=np.vstack([source.vertices,source.triangles_center])
    signed=[]
    for i,point in enumerate(points):
        if i%2048==0:ctx.check(72+int(8*i/len(points)),'核对原始结构覆盖')
        signed.append(mm.findSignedDistance(mm.Vector3f(*point),mp).dist)
    signed=np.array(signed)
    # Check the reverse direction too: surface proximity alone cannot prove that
    # a closed aircraft cavity has remained empty, so probe remote void locations.
    sample=mesh_out.vertices[np.linspace(0,len(mesh_out.vertices)-1,min(20000,len(mesh_out.vertices)),dtype=int)]
    distance=np.sqrt([mm.findProjection(mm.Vector3f(*p),sp).distSq for p in sample])
    limit=thickness/2+np.sqrt(3)*voxel+settings.maxError
    voids=[]
    for point in itertools.product(*(np.linspace(a,b,9)[1:-1] for a,b in zip(*source.bounds))):
        if mm.findProjection(mm.Vector3f(*point),sp).distSq>limit**2:
            voids.append(mm.findSignedDistance(mm.Vector3f(*point),mp).dist)
    if np.any(signed>voxel*.2):raise GeometryError('重建未覆盖全部源顶点/面心，拒绝导出缺失结构的模型')
    if distance.max()>limit or any(d<-voxel*.2 for d in voids):
        raise GeometryError('重建偏差或空腔抽样检查失败，拒绝导出')
    if abs(mesh_out.volume)>source.area*thickness*1.5:
        raise GeometryError('实体体积异常增大，拒绝导出可能实心化的模型')
    return mesh_out,dict(voxel_mm=voxel,requested_resolution_mm=resolution,precision_adjusted=bool(voxel>resolution),decimation_error_mm=settings.maxError,
        duplicate_source_faces_removed=duplicates,generated_zero_volume_faces_removed=removed_null,
        generated_intersection_pairs_relaxed=relaxed_pairs,
        generated_intersection_pairs_repaired=repaired_pairs,
        source_points_checked=len(points),source_points_outside=0,output_surface_samples=len(distance),
        max_surface_distance_mm=float(distance.max()),mean_surface_distance_mm=float(distance.mean()),
        allowed_surface_distance_mm=limit,void_probes=len(voids),unexpected_filled_voids=0,
        caveat='双侧薄壁近似重建；外轮廓增加约半个壁厚；小于壁厚/网格精度的间隙可能变化；空腔为抽样检查')


def _certify(source,output,options,ctx,started,method,records,hashes):
    from meshlib import mrmeshpy as mm
    ctx.check(80,'检查封闭实体及全部三角面自相交')
    natives=[];physical=0
    for part in output.parts:
        t=topology(part.mesh)
        if not part.mesh.is_volume or any(t[k] for k in ('open_edges','nonmanifold_edges','duplicate_faces','degenerate_faces')):
            raise GeometryError(f'{part.name} 未形成有效封闭薄壁实体')
        native=_native(part.mesh);natives.append(native)
        pairs=mm.findSelfCollidingTriangles(mm.MeshPart(native),_callback(ctx.scaled(80,85)))
        ctx.check()
        if len(pairs):raise GeometryError(f'{part.name} 仍有{len(pairs)}对自相交面，拒绝导出')
        physical+=sum(native.volume(c)>1e-8 for c in mm.MeshComponents.getAllComponents(mm.MeshPart(native)))
    before=analyze(source,options,ctx.scaled(85,88),quick=True)
    after=analyze(output,options,ctx.scaled(88,97),quick=True)
    for p in after['parts']:
        p['self_intersections']=dict(status='complete_native',tested_pairs=None,pairs=[],note='MeshLib BVH全网格相交检查；排除仅接触')
    volume=sum(abs(p.mesh.volume) for p in output.parts)
    maximum=max((r.get('max_surface_distance_mm',0.) for r in records),default=0.)
    mean=float(np.mean([r.get('mean_surface_distance_mm',0.) for r in records])) if records else 0.
    comparison=dict(original_bounds_mm=source.mesh.bounds.tolist(),output_bounds_mm=output.mesh.bounds.tolist(),
        original_closed_volume_mm3=sum(abs(p.mesh.volume) for p in source.parts if p.mesh.is_volume),
        output_volume_mm3=volume,estimated_mass_g=volume/1000*options.density,
        mass_conditions=f'材料密度{options.density:g}g/cm³；按实体体积估算，实际耗材以切片为准',
        sampled_exterior_max_mm=maximum,sampled_exterior_mean_mm=mean,exterior_within_tolerance=True,
        deviation_scope='距离场模式：输出表面2万点到源曲面的距离；源全部顶点及面心须位于实体内。闭合网格保留模式：坐标未改变。非全局Hausdorff证明。',
        structure_samples=records,uncovered_source_parts=[],physical_solid_components=physical,
        boundary_components=after['connected_components'],connections_status='仅同一源组内合并；不同build实例保持独立',
        unintended_fill_check='未执行开放边封孔；无符号距离只对曲面周围建立薄壁，空腔另做抽样检查')
    unchanged=hashes==[mesh_digest(p.mesh) for p in source.parts]
    if not unchanged:raise GeometryError('源网格发生变化')
    actions=['原有封闭实体原尺寸导出'] if method=='preserved_closed_mesh' else [
        f'复杂曲面以{options.thickness:g}mm双侧薄壁实体化；外轮廓约向外偏移{options.thickness/2:g}mm',
        '核对全部源顶点/面心、输出表面抽样距离及空腔抽样；未逐三角形单独加厚或填实空腔']
    return Conversion(output,dict(mode=options.mode,method=method,thickness_mm=options.thickness,
        options=options.__dict__,status='geometry_passed',before=before,after=after,comparison=comparison,
        actions=actions,issues=[],reconstruction=records,even_odd_recommended=False,
        source_mesh_sha256=hashes,source_mesh_unchanged=True,
        structure_loss='全部源顶点及面心覆盖检查通过；孔槽细节受壁厚与重建精度影响，非无损转换',
        elapsed_seconds=round(time.monotonic()-started,3),
        slicer_validation={'status':'not_run','note':'几何通过不等于实际切片/打印通过'}))


def convert_ready(model,options=None,ctx=None,auto_surface=True,resolution=.1):
    options,ctx=options or Options(),ctx or Context();options.validate()
    if options.reconstruction=='layered':
        from .layered import convert_layered
        return convert_layered(model,options,ctx)
    if not np.isfinite(resolution) or not .04<=resolution<=.2:raise GeometryError('曲面重建精度必须为0.04–0.20 mm')
    if sum(len(p.mesh.faces) for p in model.parts)>options.max_faces:raise GeometryError('输入总面数超过处理限制')
    started=time.monotonic();hashes=[mesh_digest(p.mesh) for p in model.parts]
    if options.mode!='regular':
        if any(not p.mesh.is_volume for p in model.parts):
            raise GeometryError('此模型含开放曲面，Even-Odd不能生成可直接切片的薄壁实体。请将模式切换为Regular，再点击一键转换并导出。')
        return convert(model,options,ctx)
    if all(p.mesh.is_volume and p.role in ('auto','solid','keep') for p in model.parts):
        output=Model([p.copy() for p in model.parts],model.source,model.warnings.copy())
        return _certify(model,output,options,ctx,started,'preserved_closed_mesh',[],hashes)
    automatic=auto_surface and all(p.role in ('auto','solid','keep') for p in model.parts)
    requires_rebuild=any(p.role=='auto' and not p.mesh.is_volume and infer_role(p.mesh)[0]=='unknown' for p in model.parts)
    if not (automatic and requires_rebuild):
        try:return convert(model,options,ctx)
        except GeometryError:
            if not automatic:raise
    groups=defaultdict(list)
    for i,p in enumerate(model.parts):groups[p.group if options.merge else str(i)].append(p)
    out=[];records=[]
    for i,(group,parts) in enumerate(groups.items()):
        if all(p.mesh.is_volume for p in parts):out.extend(p.copy() for p in parts);continue
        kept=[p for p in parts if p.role in ('solid','keep')]
        if any(not p.mesh.is_volume for p in kept):raise GeometryError('待保留零件仍为开放曲面，请勾选转换或指定正确结构类型')
        out.extend(p.copy() for p in kept)
        surfaces=[p for p in parts if p.role=='auto']
        if not surfaces:continue
        joined=trimesh.util.concatenate([p.mesh for p in surfaces])
        result,record=_rebuild(joined,options.thickness,resolution,ctx.scaled(int(75*i/len(groups)),int(75*(i+1)/len(groups))))
        record.update(name=surfaces[0].name,group=group,source_parts=[p.name for p in surfaces])
        records.append(record);out.append(Part(surfaces[0].name+' [薄壁成品]',result,group,'solid'))
    return _certify(model,Model(out,model.source,model.warnings.copy()),options,ctx,started,'unsigned_distance_thinwall',records,hashes)

from pathlib import Path
from threading import Event
import numpy as np,pytest,trimesh,shapely
from aeroslice.core import Model,Part,Options,Context,Cancelled,GeometryError,mesh_digest
from aeroslice.fixtures import sheet,holed_sheet,wing
from aeroslice.layered import convert_layered,layer_region
from aeroslice.fileio import export_model,load_model
from aeroslice.ready import convert_ready

def options(**kw):return Options(mode='even-odd',reconstruction='layered',**kw)


@pytest.mark.parametrize('shift',[[0,0],[-40,-134]])
def test_near_reversing_short_branch_restores_original_stroke(shift):
    from aeroslice.layered import extrude_region
    xy=np.array([[[0,0],[-1.08,-1.08]],[[-.93,-.93],[-.932,-.922]],
                 [[-.922,-.932],[-.93,-.93]]])+shift
    segments=np.dstack([xy,np.zeros(xy.shape[:2])]);raw=shapely.multilinestrings(xy)
    merged=shapely.simplify(shapely.line_merge(raw),.005,preserve_topology=True)
    old_region=shapely.simplify(shapely.buffer(merged,.225,quad_segs=2,cap_style='flat',join_style='mitre'),.002,preserve_topology=True)
    assert not shapely.covers(shapely.buffer(old_region,.008,quad_segs=1),raw)
    diagnostics={};region,actual_raw=layer_region(segments,.45,diagnostics)
    assert diagnostics['coverage_repaired'] and diagnostics['coverage_repair_segments']>0
    assert shapely.covers(shapely.buffer(region,.008,quad_segs=1),actual_raw)
    # Restore source strokes without removing any material already constructed.
    assert old_region.difference(region).area<1e-10
    nominal_strokes=shapely.buffer(raw,.225,quad_segs=2,cap_style='flat',join_style='mitre')
    assert region.difference(old_region).difference(nominal_strokes).area<1e-10
    slab=extrude_region(region,0,.2)
    assert slab.is_volume and slab.volume==pytest.approx(region.area*.2,abs=1e-6)


def test_covered_section_is_left_exactly_unchanged():
    xy=np.array([[[0,0],[10,0]],[[10,0],[10,10]],[[10,10],[0,10]],[[0,10],[0,0]]])
    raw=shapely.multilinestrings(xy)
    expected=shapely.simplify(shapely.buffer(shapely.simplify(shapely.line_merge(raw),.005,preserve_topology=True),
        .225,quad_segs=2,cap_style='flat',join_style='mitre'),.002,preserve_topology=True)
    diagnostics={};region,_=layer_region(np.dstack([xy,np.zeros(xy.shape[:2])]),.45,diagnostics)
    assert region.equals_exact(expected,0) and diagnostics=={}
    assert not region.covers(shapely.Point(5,5))


def test_failed_repair_still_stops_export(monkeypatch):
    monkeypatch.setattr(shapely,'covers',lambda a,b:np.zeros(len(b),dtype=bool) if isinstance(b,np.ndarray) else False)
    segments=np.array([[[0,0,0],[1,0,0]]])
    with pytest.raises(GeometryError,match='覆盖核对失败'):layer_region(segments,.45)


def test_layer_error_includes_source_plane(monkeypatch):
    import aeroslice.layered as layered
    def fail(*args):raise GeometryError('coverage failure')
    monkeypatch.setattr(layered,'layer_region',fail)
    with pytest.raises(GeometryError,match='test-part 第1层.*Z='):
        convert_layered(Model([Part('test-part',sheet())]),options())

def test_closed_ring_keeps_void_and_internal_branch():
    segments=np.array([[[0,0,0],[20,0,0]],[[20,0,0],[20,10,0]],[[20,10,0],[0,10,0]],[[0,10,0],[0,0,0]],[[10,0,0],[10,10,0]]])
    region,raw=layer_region(segments,.45)
    assert not region.covers(shapely.Point(5,5))
    assert region.covers(shapely.Point(10,5))
    assert region.buffer(.008).covers(raw)

def test_layer_planes_branches_source_and_metadata_roundtrip(tmp_path):
    a=sheet(10,2);b=sheet(10,2);b.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2,[0,0,1]))
    model=Model([Part('a',a,'one'),Part('b',b,'one')]);digests=[mesh_digest(p.mesh) for p in model.parts]
    values=[];result=convert_ready(model,options(),Context(progress=lambda v,t:values.append(v)))
    report=result.report;assert report['method']=='layered_sections' and report['status']=='geometry_passed'
    layers=report['reconstruction'][0]['layers'];assert len(layers)==10
    assert all(x['closed_slab'] and x['raw_section_covered'] for x in layers)
    assert [mesh_digest(p.mesh) for p in model.parts]==digests
    assert min(values)==5 and max(values)==100
    mesh=result.model.mesh;assert mesh.is_volume
    section=trimesh.intersections.mesh_plane(mesh,[0,0,1],[0,0,.1])
    assert len(section)>0
    # Two 10mm ribbons crossing once, extruded through 2mm; no cavity fill.
    assert mesh.volume==pytest.approx((2*10*.45-.45**2)*2,abs=.001)
    out=tmp_path/'layered.3mf';export_model(result.model,out)
    reread=load_model(out,split=False)
    assert reread.metadata['layered_requirements']['layer_height_mm']==.2
    np.testing.assert_allclose(reread.mesh.bounds,mesh.bounds)
    with pytest.raises(GeometryError,match='已经是逐层'):convert_ready(reread,options())

def test_layered_cancels_during_layer_loop():
    event=Event()
    def progress(v,t):
        if v>=10:event.set()
    with pytest.raises(Cancelled):convert_layered(Model([Part('sheet',sheet())]),options(),Context(event,progress))

def test_horizontal_sheet_and_regular_mode_fail_explicitly():
    with pytest.raises(GeometryError,match='水平'):convert_layered(Model([Part('horizontal',holed_sheet())]),options())
    with pytest.raises(ValueError,match='Even-Odd'):Options(reconstruction='layered').validate()

def test_closed_surface_input_is_converted_to_hollow_surface_material():
    source=wing(chord=20,span=2,samples=16)
    result=convert_layered(Model([Part('closed Surface wing',source)]),options())
    assert result.report['reconstruction'][0]['layer_count']==10
    assert result.model.mesh.volume<source.volume*.6
    mid=trimesh.intersections.mesh_plane(result.model.mesh,[0,0,1],[0,0,1.1])
    assert len(mid)>0
    # Centre of the original wing must stay in its empty cavity.
    xy=np.array([8.,0.])
    assert np.linalg.norm(mid[:,:,:2]-xy,axis=2).min()>.5

def test_explicit_solid_is_preserved_and_original_3mf_surface_is_converted(tmp_path):
    source=wing(chord=20,span=2,samples=16)
    kept=convert_layered(Model([Part('normal',source,role='solid')]),options())
    assert mesh_digest(kept.model.parts[0].mesh)==mesh_digest(source)
    assert not kept.report['reconstruction']
    path=tmp_path/'original_surface.3mf';export_model(Model([Part('surface',source)]),path)
    loaded=load_model(path,split=False);result=convert_layered(loaded,options())
    assert result.report['reconstruction'][0]['layer_count']==10
    assert result.model.mesh.volume==pytest.approx(convert_layered(Model([Part('surface',source)]),options()).model.mesh.volume)

def test_gui_defaults_to_initial_route_and_buttons_capture_settings(app,monkeypatch,tmp_path):
    from aeroslice.gui import Window
    window=Window();old_output=window.output_path.text();window.models=[Model([Part('sheet',sheet())])]
    window.add_model(window.models[0],{'parts':[{'reason':'test','self_intersections':{'pairs':[]}}]})
    assert window.reconstruction.currentIndex()==0 and window.mode.currentIndex()==1
    assert not window.mode.isEnabled() and window.layer_height.isEnabled()
    jobs=[];monkeypatch.setattr(window,'start_job',lambda name,args:jobs.append((name,args)))
    window.output_path.setText(str(tmp_path));window.layer_height.setValue(.25)
    window.quick_export_btn.click()
    assert jobs[0][1]['options'].reconstruction=='layered'
    assert jobs[0][1]['options'].layer_height==.25
    window.reconstruction.setCurrentIndex(1)
    assert window.mode.currentIndex()==0 and not window.layer_height.isEnabled()
    window.output_path.setText(old_output);window.close()


@pytest.mark.parametrize('role,action',[('solid','结构类型'),('keep','勾选')])
def test_invalid_preserved_surface_explains_recovery(role,action):
    model=Model([Part('surface',sheet(),role=role)])
    with pytest.raises(GeometryError,match='Surface 自动重建') as raised:convert_layered(model,options())
    assert action in str(raised.value)
    assert '跳过Surface重建' in str(raised.value)


def test_gui_rejects_open_surface_solid_role_without_losing_valid_cache(app,monkeypatch):
    from aeroslice.gui import Window
    from aeroslice.converters import Conversion
    window=Window();monkeypatch.setattr(window,'refresh_views',lambda:None)
    part=Part('open Surface',sheet());model=Model([part]);window.models=[model]
    window.add_model(model,{'parts':[{'reason':'test','self_intersections':{'pairs':[]}}]})
    before=mesh_digest(part.mesh)
    cached=Conversion(model,{'status':'geometry_passed'});window.result=cached;window.result_key='valid'
    combo=window.tree.itemWidget(window.rows[0],2)
    combo.setCurrentIndex(combo.findData('solid'))
    assert combo.currentData()=='auto' and part.role=='auto'
    assert '已改回' in window.feedback.text() and '导出' in window.feedback.text()
    assert window.result is cached and window.result_key=='valid'
    assert mesh_digest(part.mesh)==before
    window.close()


def test_gui_can_still_preserve_a_valid_closed_solid(app,monkeypatch):
    from aeroslice.gui import Window
    window=Window();monkeypatch.setattr(window,'refresh_views',lambda:None)
    part=Part('closed',wing(chord=20,span=2,samples=16));model=Model([part]);window.models=[model]
    window.add_model(model,{'parts':[{'reason':'test','self_intersections':{'pairs':[]}}]})
    combo=window.tree.itemWidget(window.rows[0],2);combo.setCurrentIndex(combo.findData('solid'))
    assert combo.currentData()=='solid' and part.role=='solid'
    assert window.selected_model().parts[0].role=='solid'
    window.close()


def test_gui_role_labels_follow_method_without_changing_selection(app):
    from aeroslice.gui import Window
    window=Window();part=Part('surface',sheet());model=Model([part]);window.models=[model]
    window.add_model(model,{'parts':[{'reason':'test','self_intersections':{'pairs':[]}}]})
    combo=window.tree.itemWidget(window.rows[0],2)
    assert combo.currentText()=='Surface 自动重建'
    assert '不重建' in combo.itemText(combo.findData('solid'))
    window.reconstruction.setCurrentIndex(1)
    assert combo.currentData()=='auto' and combo.currentText()=='自动判断' and part.role=='auto'
    window.reconstruction.setCurrentIndex(0)
    assert combo.currentText()=='Surface 自动重建'
    window.close()

@pytest.fixture(scope='module')
def app():
    from PySide6 import QtWidgets as W
    return W.QApplication.instance() or W.QApplication([])

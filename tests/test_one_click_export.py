from pathlib import Path
from threading import Event
import pytest
from PySide6 import QtCore as C,QtWidgets as W
from aeroslice.core import Model,Part,Options,sha256
from aeroslice.fixtures import wing
from aeroslice.fileio import export_model,load_model
from aeroslice.workers import execute_job
from aeroslice.gui import Window


class Messages:
    def __init__(self):self.items=[]
    def put(self,item):self.items.append(item)
    def close(self):pass
    def join_thread(self):pass


@pytest.mark.parametrize('input_fmt,output_fmt',[('stl','3mf'),('3mf','stl')])
def test_import_then_export_writes_readable_closed_result(tmp_path,input_fmt,output_fmt):
    source=tmp_path/f'input.{input_fmt}'
    export_model(Model([Part('airfoil',wing(),role='solid')]),source)
    digest=sha256(source)
    loaded=load_model(source,split=False)
    messages=Messages()
    execute_job('export',{'model':loaded,'options':Options(section_count=2),
        'folder':str(tmp_path/'out'),'format':output_fmt,'separate':False},messages,Event())
    kind,payload=messages.items[-1]
    assert kind=='done',payload
    saved=Path(payload['paths'][0])
    assert saved.is_file() and saved.suffix==f'.{output_fmt}'
    assert load_model(saved,split=False).mesh.is_volume
    assert not list(saved.parent.glob('*.json'))
    assert sha256(source)==digest


@pytest.fixture(scope='module')
def app():
    C.QCoreApplication.setAttribute(C.Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    return W.QApplication.instance() or W.QApplication([])


@pytest.mark.parametrize('button',['save_btn','quick_export_btn'])
def test_export_button_starts_conversion_with_current_settings(app,monkeypatch,tmp_path,button):
    window=Window()
    old_output=window.output_path.text()
    model=Model([Part('airfoil',wing(),role='solid')])
    window.models.append(model)
    window.add_model(model,{'parts':[{'reason':'test','self_intersections':{'pairs':[]}}]})
    assert window.result is None
    window.output_path.setText(str(tmp_path));window.thickness.setValue(.6)
    jobs=[];monkeypatch.setattr(window,'start_job',lambda name,args:jobs.append((name,args)))
    getattr(window,button).click()
    assert len(jobs)==1 and jobs[0][0]=='export'
    assert jobs[0][1]['options'].thickness==.6
    assert len(jobs[0][1]['model'].parts)==1
    assert Path(jobs[0][1]['folder'])==tmp_path
    window.output_path.setText(old_output);window.close()


def test_missing_input_and_worker_error_are_prominent(app):
    window=Window();errors=[];window.operationFailed.connect(errors.append)
    window.save_btn.click()
    assert errors and '导入' in window.feedback.text()
    window.on_error('GeometryError: 测试失败\ntraceback')
    assert '未导出' in window.feedback.text() and '测试失败' in window.feedback.text()
    assert window.save_btn.isEnabled()
    window.close()


@pytest.fixture
def converted_window(app,monkeypatch,tmp_path):
    from aeroslice.converters import Conversion
    window=Window();old_output=window.output_path.text()
    monkeypatch.setattr(window,'refresh_views',lambda:None)
    monkeypatch.setattr(window,'render_report',lambda report:None)
    model=Model([Part('airfoil',wing(),role='solid'),Part('second',wing(),role='solid')])
    window.models.append(model)
    window.add_model(model,{'parts':[{'reason':'test','self_intersections':{'pairs':[]}} for _ in model.parts]})
    window.output_path.setText(str(tmp_path))
    jobs=[];monkeypatch.setattr(window.job,'start',lambda name,args:jobs.append((name,args)))
    window.convert_btn.click()
    assert jobs[-1][0]=='convert'
    snapshot=Conversion(jobs[-1][1]['model'],{'status':'geometry_passed','after':{'parts':[]}})
    window.on_done(snapshot)
    jobs.clear()
    yield window,jobs,snapshot
    window.output_path.setText(old_output);window.close()


@pytest.mark.parametrize('button',['save_btn','quick_export_btn'])
def test_convert_then_export_reuses_result_and_output_preferences(converted_window,tmp_path,button):
    window,jobs,snapshot=converted_window
    # Output preferences and preview visibility do not alter the converted geometry.
    folder=tmp_path/'new folder'
    window.output_path.setText(str(folder));window.output_format.setCurrentIndex(0)
    window.separate.setChecked(True)
    window.rows[0].setCheckState(1,C.Qt.CheckState.Unchecked)
    getattr(window,button).click()
    assert [name for name,args in jobs]==['save']
    assert jobs[0][1]['result'] is snapshot
    assert Path(jobs[0][1]['folder'])==folder
    assert jobs[0][1]['format']=='3mf' and jobs[0][1]['separate']


@pytest.mark.parametrize('change',[
    lambda w:w.thickness.setValue(.6),
    lambda w:w.layer_height.setValue(.25),
    lambda w:w.reconstruction.setCurrentIndex(1),
    lambda w:w.precision.setCurrentIndex(1),
    lambda w:w.merge.setChecked(False),
    lambda w:w.surface_resolution.setValue(.12),
    lambda w:w.rows[0].setCheckState(0,C.Qt.CheckState.Unchecked),
    lambda w:w.tree.itemWidget(w.rows[0],2).setCurrentIndex(1),
    lambda w:w.parts[0].mesh.apply_translation([.1,0,0]),
])
def test_changed_conversion_inputs_do_not_reuse_old_result(converted_window,change):
    window,jobs,_=converted_window
    change(window);window.save_btn.click()
    assert [name for name,args in jobs]==['export']


def test_completed_result_uses_start_snapshot_not_later_settings(converted_window):
    from aeroslice.converters import Conversion
    window,jobs,_=converted_window
    window.convert_btn.click()
    captured=jobs[-1][1]
    # Simulates a programmatic edit during a background task.
    window.thickness.setValue(.7)
    window.on_done(Conversion(captured['model'],{'status':'geometry_passed','after':{'parts':[]}}))
    jobs.clear();window.save_btn.click()
    assert jobs[-1][0]=='export'


def test_one_click_completed_result_can_be_exported_again(converted_window,tmp_path):
    window,jobs,snapshot=converted_window
    window.result=None
    window.save_btn.click();assert jobs[-1][0]=='export'
    window.on_done({'result':snapshot,'paths':[str(tmp_path/'first.stl')]})
    jobs.clear();window.quick_export_btn.click()
    assert jobs[-1][0]=='save'


def test_failed_preview_is_not_reused(converted_window):
    window,jobs,snapshot=converted_window
    snapshot.report['status']='geometry_failed'
    window.save_btn.click()
    assert jobs[-1][0]=='export'


def test_preview_save_worker_skips_conversion_and_writes_only_models(tmp_path,monkeypatch):
    import aeroslice.ready as ready
    from aeroslice.core import mesh_digest
    actual=ready.convert_ready;calls=[]
    def counted(*args,**kwargs):
        calls.append(1)
        return actual(*args,**kwargs)
    monkeypatch.setattr(ready,'convert_ready',counted)
    source=tmp_path/'original.stl'
    export_model(Model([Part('airfoil',wing(),role='solid')]),source)
    digest=sha256(source)
    queue=Messages()
    execute_job('convert',{'model':load_model(source,split=False),
                         'options':Options(section_count=2)},queue,Event())
    kind,converted=queue.items[-1];assert kind=='done',converted
    before=mesh_digest(converted.model.mesh)
    folder=tmp_path/'chosen'/'new folder'
    for index in range(2):
        queue=Messages()
        execute_job('save',{'result':converted,'folder':str(folder),'format':'stl',
                           'separate':False,'output_name':'original_converted'},queue,Event())
        kind,payload=queue.items[-1];assert kind=='done',payload
        path=Path(payload['paths'][0])
        assert path.parent==folder
        assert path.name==('original_converted.stl' if index==0 else 'original_converted_2.stl')
        reread=load_model(path,split=False)
        assert len(reread.mesh.faces)==len(converted.model.mesh.faces)
        assert reread.mesh.is_volume
    assert calls==[1]
    assert mesh_digest(converted.model.mesh)==before
    assert sha256(source)==digest
    assert sorted(p.suffix for p in folder.iterdir())==['.stl','.stl']


def test_failed_result_cannot_be_saved(tmp_path):
    from aeroslice.converters import Conversion
    queue=Messages()
    execute_job('save',{'result':Conversion(Model([]),{'status':'geometry_failed'}),
                       'folder':str(tmp_path/'out'),'format':'stl','separate':False},queue,Event())
    assert queue.items[-1][0]=='error'
    assert not (tmp_path/'out').exists()


def test_failed_gui_export_does_not_write_json(tmp_path,monkeypatch):
    from aeroslice.batch import save_conversion
    from aeroslice.converters import Conversion
    import aeroslice.batch as batch
    def fail(*args,**kwargs):raise OSError('test write failed')
    monkeypatch.setattr(batch,'export_model',fail)
    result=Conversion(Model([Part('airfoil',wing())]),{'status':'geometry_passed'})
    with pytest.raises(OSError):save_conversion(result,tmp_path/'out','stl',write_report=False)
    assert list((tmp_path/'out').iterdir())==[]

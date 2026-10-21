"""In-process application QA, also usable inside the frozen Windows build."""
from pathlib import Path
import time
import sys
from PySide6 import QtCore as C, QtWidgets as W
from .core import write_json,sha256
from .fixtures import wing_with_ribs
from .analysis import analyze
from .gui import Window


def run_reuse(output,source,recover_surface_role=False):
    """Exercise the actual GUI buttons and spawned workers in the shipped EXE."""
    from .core import mesh_digest
    from .fileio import load_model
    import numpy as np
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    source=Path(source).resolve();source_hash=sha256(source)
    C.QCoreApplication.setAttribute(C.Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app=W.QApplication.instance() or W.QApplication([])
    window=Window();window.resize(1500,940);window.reconstruction.setCurrentIndex(0)
    window.output_format.setCurrentIndex(1)
    if recover_surface_role:
        window.layer_height.setValue(.25);window.thickness.setValue(.42);window.separate.setChecked(True)
    old_output=window.output_path.text()
    folder=output/'selected_directory'/'new_folder';window.output_path.setText(str(folder))
    window.show()
    started=time.monotonic();checks={};jobs=[]
    state={'stage':0,'heartbeat':0,'error':None,'completed':None}
    def done(_):
        jobs.append(window.job_name);state['completed']=window.job_name
    window.job.done.connect(done)
    window.operationFailed.connect(lambda message:state.update(error=message))

    def finish(code):
        checks.update(passed=code==0,source=str(source),source_sha256=source_hash,
                      source_unchanged=sha256(source)==source_hash,completed_jobs=jobs,
                      executable_sha256=sha256(sys.executable),
                      elapsed_seconds=time.monotonic()-started,ui_heartbeat=state['heartbeat'])
        write_json(output/'selftest.json',checks)
        window.output_path.setText(old_output);window.close();app.exit(code)

    def tick():
        state['heartbeat']+=1
        try:
            if time.monotonic()-started>600:raise TimeoutError('转换结果复用测试超时')
            if state['stage']==0:
                state['stage']=1;window.import_paths([source]);return
            if window.job.running:return
            if state['error']:raise AssertionError(state['error'])
            if state['stage']==1 and state['completed']=='load':
                if recover_surface_role:
                    from .core import GeometryError
                    from .ready import convert_ready
                    model=window.selected_model();model.parts[0].role='solid'
                    try:convert_ready(model,window.options())
                    except GeometryError as error:
                        assert '无法作为有效封闭实体原样保留' in str(error)
                        assert '自动重建' in str(error)
                        checks['original_selection_error_reproduced']=str(error)
                    else:raise AssertionError('测试输入未复现截图中的保留实体错误')
                    combo=window.tree.itemWidget(window.rows[0],2)
                    combo.setCurrentIndex(combo.findData('solid'))
                    assert combo.currentData()=='auto' and window.parts[0].role=='auto'
                    assert '已改回' in window.feedback.text()
                    checks.update(invalid_solid_role_recovered=True,role_feedback=window.feedback.text(),
                        layer_height_mm=window.layer_height.value(),thickness_mm=window.thickness.value(),
                        separate=window.separate.isChecked())
                state.update(stage=2,completed=None,conversion_start=time.monotonic())
                window.convert_btn.click();assert window.job_name=='convert';return
            if state['stage']==2 and state['completed']=='convert':
                assert window.result.report['status']=='geometry_passed'
                checks.update(conversion_seconds=time.monotonic()-state['conversion_start'],
                              method=window.result.report['method'])
                if window.result.report['method']=='layered_sections':
                    records=window.result.report['reconstruction']
                    checks.update(layer_height_mm=window.layer_height.value(),thickness_mm=window.thickness.value(),
                        covered_layers=sum(len(record['layers']) for record in records),
                        repaired_layers=[dict(name=record['name'],**layer) for record in records
                                         for layer in record['layers'] if layer.get('coverage_repaired')],
                        all_sections_covered=all(record['all_sections_covered'] for record in records))
                state['geometry_digest']=mesh_digest(window.result.model.mesh)
                state['cached_result']=window.result
                state.update(stage=3,completed=None,save_start=time.monotonic())
                window.save_btn.click();assert window.job_name=='save';return
            if state['stage']==3 and state['completed']=='save':
                path=Path(window.last_output)
                assert path.is_file() and path.parent==folder
                assert path.suffix=='.stl'
                assert list(folder.iterdir())==[path],list(folder.iterdir())
                original=window.result.model.mesh
                saved=load_model(path,split=False,max_faces=max(1_500_000,len(original.faces)*2)).mesh
                assert len(saved.faces)==len(original.faces)
                assert np.allclose(saved.bounds,original.bounds,atol=1e-6,rtol=np.finfo(np.float32).eps)
                checks.update(first_save_seconds=time.monotonic()-state['save_start'],
                              saved_model=str(path),faces=len(saved.faces),stl_sha256=sha256(path),
                              direct_selected_directory=True,no_json_in_model_directory=True)
                state['first_path']=path
                state.update(stage=4,completed=None,save_start=time.monotonic())
                window.quick_export_btn.click();assert window.job_name=='save';return
            if state['stage']==4 and state['completed']=='save':
                path=Path(window.last_output)
                assert path!=state['first_path'] and path.parent==folder
                assert sha256(path)==checks['stl_sha256']
                assert len(list(folder.iterdir()))==2 and not list(folder.glob('*.json'))
                assert window.result is state['cached_result']
                assert mesh_digest(window.result.model.mesh)==state['geometry_digest']
                assert jobs==['load','convert','save','save'],jobs
                assert sha256(source)==source_hash
                checks.update(second_save_seconds=time.monotonic()-state['save_start'],
                              duplicate_saved_model=str(path),conversion_count=jobs.count('convert'),
                              cache_reused=True,existing_file_preserved=True)
                window.grab().save(str(output/'window.png'));finish(0)
        except Exception as e:
            checks['error']=str(e);finish(1)

    timer=C.QTimer();timer.timeout.connect(tick);timer.start(100)
    return app.exec()


def run(output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    C.QCoreApplication.setAttribute(C.Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app=W.QApplication.instance() or W.QApplication([])
    window=Window();window.reconstruction.setCurrentIndex(1);window.output_format.setCurrentIndex(0);window.resize(1680,1000)
    old_output=window.output_path.text()
    window.output_path.setText(str(output))
    model=wing_with_ribs()
    diagnostic=analyze(model)
    window.models.append(model);window.add_model(model,diagnostic)
    window.refresh_views();window.fit_views();window.show()
    state={'stage':0,'heartbeat':0};start=time.monotonic();checks={}

    def finish(code):
        checks.update(elapsed_seconds=time.monotonic()-start,ui_heartbeat=state['heartbeat'],passed=code==0)
        checks['executable_sha256']=sha256(sys.executable)
        write_json(output/'selftest.json',checks)
        window.output_path.setText(old_output)
        window.close();app.exit(code)

    def tick():
        state['heartbeat']+=1
        try:
            if time.monotonic()-start>120:raise TimeoutError('打包GUI测试超时')
            if window.job.running:return
            if state['stage']==0:
                window.save_btn.click();state['stage']=1
            elif state['stage']==1:
                assert window.result is not None,window.report_box.toPlainText()
                assert window.result.report['status']=='geometry_passed'
                checks['regular_airfoil_ribs']='geometry_passed'
                window.style_combo.setCurrentIndex(1)
                window.camera(-60,22)
                checks['one_click_export']=True;state['stage']=2
            elif state['stage']==2:
                assert window.last_output and Path(window.last_output).exists(),window.report_box.toPlainText()
                checks['saved_model']=window.last_output
                window.grab().save(str(output/'window.png'))
                for label,view in [('original',window.original_view),('converted',window.converted_view)]:
                    im=view.grabFramebuffer()
                    assert not im.isNull(),'OpenGL渲染帧为空'
                    im.save(str(output/f'{label}.png'))
                checks['opengl_framebuffers']=True
                state['stage']=3;finish(0)
        except Exception as e:
            checks['error']=str(e);state['stage']=-1;finish(1)

    timer=C.QTimer();timer.timeout.connect(tick);timer.start(120)
    return app.exec()


def run_import(output,source,reconstruction='layered'):
    from .core import sha256
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    source=Path(source).resolve();source_hash=sha256(source)
    C.QCoreApplication.setAttribute(C.Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app=W.QApplication.instance() or W.QApplication([])
    window=Window();window.reconstruction.setCurrentIndex(0 if reconstruction=='layered' else 1);window.resize(1500,940)
    if reconstruction=='layered':window.output_format.setCurrentIndex(1)
    old_output=window.output_path.text();window.output_path.setText(str(output));window.show()
    started=time.monotonic();state={'stage':0,'heartbeat':0,'completed_job':None,'error':None};checks={}
    window.job.done.connect(lambda _:state.update(completed_job=window.job_name))
    window.operationFailed.connect(lambda message:state.update(error=message))

    def finish(code):
        checks.update(passed=code==0,source=str(source),source_sha256=source_hash,
                      source_unchanged=sha256(source)==source_hash,elapsed_seconds=time.monotonic()-started,
                      ui_heartbeat=state['heartbeat'])
        checks['executable_sha256']=sha256(sys.executable)
        write_json(output/'selftest.json',checks)
        window.output_path.setText(old_output);window.close();app.exit(code)

    def tick():
        state['heartbeat']+=1
        try:
            if time.monotonic()-started>600:raise TimeoutError('真实模型GUI导入导出超时')
            if state['heartbeat']%10==0:
                write_json(output/'live.json',dict(stage=state['stage'],progress=window.progress.value(),
                    status=window.status.text(),elapsed_seconds=time.monotonic()-started))
            if state['stage']==0:
                state['stage']=1;window.import_paths([source]);return
            if window.job.running:return
            if state['error']:raise AssertionError(state['error'])
            expected='load' if state['stage'] in (1,3) else 'export'
            if state['completed_job']!=expected:return
            if state['stage']==2:
                assert window.last_output and Path(window.last_output).is_file(),window.report_box.toPlainText()
                first=Path(window.last_output)
                checks.update(one_click_export=True,saved_model=str(first),
                              export_status=window.result.report['status'],
                              first_export_seconds=time.monotonic()-started)
                assert window.result.report['status']=='geometry_passed'
                assert window.result.model.mesh.is_volume
                window.grab().save(str(output/'exported.png'))
                if reconstruction=='layered':
                    assert window.result.report['method']=='layered_sections'
                    checks['method']='layered_sections';finish(0);return
                state['completed_job']=None
                window.clear_models();window.import_paths([first]);state['stage']=3;return
            if state['stage']==3:
                assert window.models,window.report_box.toPlainText()
                window.output_format.setCurrentIndex(1);window.last_output=None
                state['completed_job']=None
                window.save_btn.click();state['stage']=4;return
            if state['stage']==4:
                assert window.last_output and Path(window.last_output).is_file(),window.report_box.toPlainText()
                assert Path(window.last_output).suffix=='.stl'
                checks.update(reimport_3mf_export_stl=True,saved_stl=window.last_output)
                finish(0);return
            assert window.models,window.report_box.toPlainText()
            model=window.models[0]
            faces=sum(len(p.mesh.faces) for p in model.parts)
            rendered_faces=window.original_view.items[0].opts['meshdata'].faceCount()
            assert rendered_faces==faces,'显示合批丢失三角面'
            checks.update(parts=len(model.parts),faces=faces,rendered_faces=rendered_faces,
                          scene_rebuilds=window._scene_rebuilds,gl_items=len(window.original_view.items),
                          progress=window.progress.value())
            assert checks['scene_rebuilds']==1,'零件树初始化触发重复重画'
            assert checks['progress']==100
            checks['loaded_seconds']=time.monotonic()-started
            window.grab().save(str(output/'window.png'))
            assert not window.original_view.grabFramebuffer().isNull()
            # A real visibility toggle remains functional after signals are restored.
            window.rows[0].setCheckState(1,C.Qt.CheckState.Unchecked)
            remaining=sum(item.opts['meshdata'].faceCount() for item in window.original_view.items if item.opts.get('meshdata') is not None)
            assert remaining==faces-len(model.parts[0].mesh.faces)
            checks['visibility_toggle']=True
            window.rows[0].setCheckState(1,C.Qt.CheckState.Checked)
            state['completed_job']=None
            window.save_btn.click();state['stage']=2
        except Exception as e:
            checks['error']=str(e);finish(1)

    timer=C.QTimer();timer.timeout.connect(tick);timer.start(100)
    return app.exec()

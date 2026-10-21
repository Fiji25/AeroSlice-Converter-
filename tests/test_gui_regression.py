import pytest
from PySide6 import QtCore as C,QtWidgets as W
from aeroslice.gui import Window
from aeroslice.core import Model,Part,mesh_digest,Context
from aeroslice.fixtures import sheet


@pytest.fixture(scope='module')
def app():
    C.QCoreApplication.setAttribute(C.Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    return W.QApplication.instance() or W.QApplication([])


def test_populating_355_parts_does_not_redraw_per_checkbox(app,monkeypatch):
    redraws=[]
    monkeypatch.setattr(Window,'refresh_views',lambda *args:redraws.append(1))
    window=Window()
    model=Model([Part(str(i),sheet()) for i in range(355)])
    diag={'parts':[{'reason':'test','self_intersections':{'pairs':[]}} for _ in model.parts]}
    redraws.clear()
    window.add_model(model,diag)
    assert len(window.parts)==355
    assert redraws==[]
    assert window.tree.updatesEnabled() and not window.tree.signalsBlocked()
    # User changes still trigger redraws after initialization is finished.
    window.rows[0].setCheckState(1,C.Qt.CheckState.Unchecked)
    assert redraws==[1]
    window.close()


def test_render_batch_keeps_all_faces_and_respects_visibility(app):
    window=Window()
    model=Model([Part(str(i),sheet()) for i in range(30)])
    diag={'parts':[{'reason':'test','self_intersections':{'pairs':[]}} for _ in model.parts]}
    hashes=[mesh_digest(p.mesh) for p in model.parts]
    window.add_model(model,diag);window.refresh_views()
    assert window.original_view.items[0].opts['meshdata'].faceCount()==60
    assert len(window.original_view.items)==2
    window.rows[0].setCheckState(1,C.Qt.CheckState.Unchecked)
    assert window.original_view.items[0].opts['meshdata'].faceCount()==58
    assert hashes==[mesh_digest(p.mesh) for p in model.parts]
    window.close()


def test_child_progress_is_mapped_to_its_stage():
    observed=[]
    parent=Context(progress=lambda v,t:observed.append(v))
    child=parent.scaled(10,90)
    child.check(0);child.check(50);child.check(100)
    assert observed==[10,50,90]


def test_completed_worker_terminal_message_survives_progress_backlog(app):
    from collections import deque
    from aeroslice.gui import Job
    class Messages:
        def __init__(self):self.messages=deque([('progress',(i,'step')) for i in range(51)]+[('done','exported')])
        def get_nowait(self):
            if not self.messages:
                import queue
                raise queue.Empty
            return self.messages.popleft()
        def close(self):pass
    class CompletedProcess:
        exitcode=0
        def is_alive(self):return False
        def join(self,timeout):pass
    job=Job();job.queue=Messages();job.process=CompletedProcess()
    done=[];failed=[];job.done.connect(done.append);job.failed.connect(failed.append)
    job.poll()
    assert job.running and not done and not failed
    job.poll()
    assert done==['exported'] and not failed and not job.running

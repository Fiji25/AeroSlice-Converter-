from __future__ import annotations
import json
import multiprocessing as mp
from pathlib import Path
import queue
import sys
import time
import traceback
from collections import defaultdict
import numpy as np
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
import pyqtgraph.opengl as gl
from . import __version__
from .core import Model, Options, write_json, conversion_digest
from .converters import Conversion
from .batch import unique_folder
from .workers import execute_job

ROLE_NAMES = {"auto":"自动判断", "shell":"外壳（向内加厚）", "sheet":"加强片（双侧加厚）", "solid":"保留闭合实体", "keep":"原样保留/待确认"}
COLORS = {"auto":(.42,.67,.86,1), "shell":(.21,.65,.96,1), "sheet":(1,.65,.22,1),
          "solid":(.32,.82,.61,1), "keep":(.83,.48,.91,1), "result":(.28,.88,.67,1)}


class View(gl.GLViewWidget):
    cameraChanged = C.Signal(dict)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        self.cameraChanged.emit({k:self.opts[k] for k in ("distance","elevation","azimuth","center","fov")})

    def wheelEvent(self, event):
        super().wheelEvent(event)
        self.cameraChanged.emit({k:self.opts[k] for k in ("distance","elevation","azimuth","center","fov")})

    def sync(self, state):
        self.opts.update(state)
        self.update()


class Job(C.QObject):
    progress=C.Signal(int,str)
    done=C.Signal(object)
    failed=C.Signal(str)
    stopped=C.Signal(str)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.process=None
        self.timer=C.QTimer(self);self.timer.setInterval(80);self.timer.timeout.connect(self.poll)
        self.cancel_time=None

    @property
    def running(self):return self.process is not None

    def start(self,name,args):
        if self.running:raise RuntimeError("已有后台任务")
        context=mp.get_context("spawn")
        self.queue=context.Queue()
        self.event=context.Event()
        self.process=context.Process(target=execute_job,args=(name,args,self.queue,self.event),daemon=True)
        self.process.start()
        self.cancel_time=None
        self.timer.start()

    def cancel(self):
        if self.running:
            self.event.set();self.cancel_time=time.monotonic()

    def finish(self):
        self.timer.stop()
        self.process.join(timeout=.1)
        if self.process.is_alive():self.process.terminate();self.process.join(timeout=.5)
        self.process=None
        self.queue.close()

    def poll(self):
        try:
            for _ in range(50):
                kind,payload=self.queue.get_nowait()
                if kind=="progress":self.progress.emit(*payload)
                else:
                    self.finish()
                    if kind=="done":self.done.emit(payload)
                    elif kind=="error":self.failed.emit(payload["message"]+"\n"+payload["traceback"])
                    else:self.stopped.emit(payload)
                    return
            # A dead worker may still have its terminal message behind queued
            # progress updates. Drain the next batch before checking its exit.
            return
        except queue.Empty:pass
        if self.cancel_time and time.monotonic()-self.cancel_time>3:
            self.finish();self.stopped.emit("已取消后台进程；源文件保持不变，已写出的结果请查看日志")
        elif self.process is not None and not self.process.is_alive():
            code=self.process.exitcode
            self.finish();self.failed.emit(f"后台进程意外退出（{code}），本次未生成已验证结果。请检查安装目录是否完整；源文件保持不变。")


class Window(W.QMainWindow):
    exportCompleted=C.Signal(object)
    operationFailed=C.Signal(str)
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"AeroSlice Converter · 航模切片兼容转换器 {__version__}")
        self.resize(1500,940)
        self.models=[];self.parts=[];self.rows=[];self.result=None;self.last_output=None;self.pending=[];self.problem_faces={}
        self.result_key=None;self._job_result_key=None
        self._edge_cache={}
        self._scene_rebuilds=0
        self.job=Job(self);self.job.progress.connect(self.on_progress);self.job.done.connect(self.on_done)
        self.job.failed.connect(self.on_error);self.job.stopped.connect(self.on_stopped)
        self.settings=C.QSettings("AeroSlice","Converter")
        self.job_name="";self.start_time=0
        self.elapsed=C.QTimer(self);self.elapsed.setInterval(500);self.elapsed.timeout.connect(self.tick)
        self._build()
        self.setStyleSheet("""
        QMainWindow,QWidget{background:#101c2e;color:#dfebfa;font-family:'Microsoft YaHei UI';font-size:12px}
        QTreeWidget,QTextBrowser,QLineEdit,QDoubleSpinBox,QSpinBox,QComboBox{background:#192940;border:1px solid #314660;border-radius:5px;padding:5px}
        QPushButton{background:#223b58;border:1px solid #355674;border-radius:5px;padding:8px 10px}
        QPushButton:hover{background:#315979} QPushButton:disabled{color:#64788e;background:#1b2b3e}
        QPushButton#primary{background:#147eae;color:white;font-weight:bold;padding:12px}
        QGroupBox{border:1px solid #314660;border-radius:7px;margin-top:12px;padding-top:15px;font-weight:bold}
        QGroupBox::title{subcontrol-origin:margin;left:10px}
        QHeaderView::section{background:#223750;color:#c7def6;padding:6px;border:0}
        QProgressBar{border:1px solid #314660;border-radius:4px;text-align:center;height:18px}
        QProgressBar::chunk{background:#159bb5} QSplitter::handle{background:#253850}
        QToolBar{spacing:7px;border:0;padding:8px} QLabel#title{font-size:21px;font-weight:bold;color:#59c4eb}
        """)

    def _button(self,text,slot,layout=None):
        b=W.QPushButton(text);b.clicked.connect(slot)
        if layout:layout.addWidget(b)
        return b

    def _build(self):
        central=W.QWidget();self.setCentralWidget(central)
        outer=W.QVBoxLayout(central)
        header=W.QHBoxLayout();outer.addLayout(header)
        title=W.QLabel("AEROSLICE  /  航模切片兼容转换器");title.setObjectName("title");header.addWidget(title)
        header.addStretch();header.addWidget(W.QLabel("离线处理 · 毫米坐标 · 原始文件保护"))
        self.quick_export_btn=self._button('一键转换并导出',self.save_result,header);self.quick_export_btn.setObjectName('primary')
        self.feedback=W.QLabel("导入 STL / 3MF 后，点击“一键转换并导出”。")
        self.feedback.setWordWrap(True);self.feedback.setTextInteractionFlags(C.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.feedback.setStyleSheet('background:#192940;padding:10px;border-radius:5px')
        outer.addWidget(self.feedback)
        split=W.QSplitter();outer.addWidget(split,1)
        left=W.QWidget();ll=W.QVBoxLayout(left);ll.setContentsMargins(0,0,3,0)
        line=W.QHBoxLayout();ll.addLayout(line)
        self.open_btn=self._button("导入模型",self.open_files,line)
        self.folder_btn=self._button("导入文件夹",self.open_folder,line)
        self.clear_btn=self._button("清空列表",self.clear_models,ll)
        ll.addWidget(W.QLabel("勾选转换对象及显示对象，逐件指定结构类型"))
        self.tree=W.QTreeWidget();self.tree.setHeaderLabels(["零件 / 转换","显示","结构类型"])
        self.tree.setColumnWidth(0,160);self.tree.setColumnWidth(1,45);self.tree.setColumnWidth(2,160)
        self.tree.itemChanged.connect(self.tree_changed);ll.addWidget(self.tree,1)
        hint=W.QLabel("蓝色：外壳　橙色：加强片\n绿色：实体/结果　红色：开放边/错误\n复杂曲面可自动重建，手动角色用于精确偏移。")
        hint.setWordWrap(True);ll.addWidget(hint)
        split.addWidget(left)
        center=W.QWidget();cl=W.QVBoxLayout(center);cl.setContentsMargins(0,0,0,0)
        toolbar=W.QHBoxLayout();cl.addLayout(toolbar)
        self.compare_combo=W.QComboBox();self.compare_combo.addItems(["左右比较（同步视角）","半透明叠加","仅转换结果","表面偏差颜色"])
        self.compare_combo.currentIndexChanged.connect(self.refresh_views);toolbar.addWidget(self.compare_combo)
        self.style_combo=W.QComboBox();self.style_combo.addItems(["实体","网格边","线框","透明"])
        self.style_combo.currentIndexChanged.connect(self.refresh_views);toolbar.addWidget(self.style_combo)
        for text,az,el in (("等轴",-45,25),("正视",-90,0),("侧视",0,0),("俯视",-90,90)):
            self._button(text,lambda _=False,a=az,e=el:self.camera(a,e),toolbar)
        views=W.QSplitter();cl.addWidget(views,1)
        self.original_view=View();self.converted_view=View()
        for v in (self.original_view,self.converted_view):v.setBackgroundColor((11,21,36));v.setMinimumHeight(300);views.addWidget(v)
        self.original_view.cameraChanged.connect(self.converted_view.sync)
        self.converted_view.cameraChanged.connect(self.original_view.sync)
        self.view_note=W.QLabel("原始模型                                      转换结果  ·  左键旋转 / 中键平移 / 滚轮缩放")
        cl.addWidget(self.view_note)
        self.report_box=W.QTextBrowser();self.report_box.setMinimumHeight(190);self.report_box.setMaximumHeight(270)
        self.report_box.setPlainText('导入原始STL或3MF后，点击顶部“一键转换并导出”。\n默认采用原方案：逐层轮廓重建。切片须保持所选层高、原Z方向和Even-Odd。\n需要连续外形时，可选择连续曲面方式。')
        cl.addWidget(self.report_box)
        split.addWidget(center)
        right=W.QWidget();rl=W.QVBoxLayout(right);rl.setContentsMargins(3,0,0,0)
        group=W.QGroupBox("转换设置");form=W.QFormLayout(group)
        self.reconstruction=W.QComboBox();self.reconstruction.addItems(['Surface → 拓竹奇偶切片','连续曲面（高级）','手动结构转换（高级）'])
        form.addRow('重建方式',self.reconstruction)
        self.layer_height=W.QDoubleSpinBox();self.layer_height.setRange(.05,.4);self.layer_height.setDecimals(3)
        self.layer_height.setValue(.2);self.layer_height.setSingleStep(.05);self.layer_height.setSuffix(' mm');form.addRow('重建 / 切片层高',self.layer_height)
        self.mode=W.QComboBox();self.mode.addItems(["Regular 实体化转换","Even-Odd 转换"]);form.addRow("模式",self.mode)
        self.thickness=W.QDoubleSpinBox();self.thickness.setRange(.01,10);self.thickness.setDecimals(3);self.thickness.setValue(.45);self.thickness.setSuffix(" mm");form.addRow("目标壁厚",self.thickness)
        presets=W.QComboBox();presets.addItems(["壁厚预设","0.40","0.42","0.45","0.50","0.60","0.80"])
        presets.currentTextChanged.connect(lambda t:self.thickness.setValue(float(t)) if t!="壁厚预设" else None);form.addRow(presets)
        self.precision=W.QComboBox();self.precision.addItems(["标准 0.000001 mm","精细 0.0000001 mm","宽松 0.00001 mm"]);form.addRow("判断精度",self.precision)
        self.section_count=W.QSpinBox();self.section_count.setRange(1,100);self.section_count.setValue(9);form.addRow("截面抽样数",self.section_count)
        self.merge=W.QCheckBox("同源对象相交薄壁布尔合并");self.merge.setChecked(True);form.addRow(self.merge)
        self.repair=W.QCheckBox("整理法线及同向重复面");self.repair.setChecked(True);form.addRow(self.repair)
        self.confirm=W.QCheckBox("自动识别包围加强片的薄壳");self.confirm.setChecked(True);form.addRow(self.confirm)
        self.reverse_shell=W.QCheckBox("反转外壳偏移方向（需核对预览）");form.addRow(self.reverse_shell)
        self.auto_surface=W.QCheckBox("复杂曲面自动转为双侧薄壁");self.auto_surface.setChecked(True);form.addRow(self.auto_surface)
        self.surface_resolution=W.QDoubleSpinBox();self.surface_resolution.setRange(.04,.2);self.surface_resolution.setDecimals(2)
        self.surface_resolution.setValue(.1);self.surface_resolution.setSingleStep(.02);self.surface_resolution.setSuffix(' mm')
        form.addRow('曲面重建精度',self.surface_resolution)
        self.surface_resolution_label=form.labelForField(self.surface_resolution)
        self.method_note=W.QLabel();self.method_note.setWordWrap(True);form.addRow(self.method_note)
        self.reconstruction.currentIndexChanged.connect(self.reconstruction_changed)
        self.reconstruction_changed()
        form.addRow(W.QLabel("有疑问的几何会保留并报告，禁止自动填孔。"));rl.addWidget(group)
        self.convert_btn=self._button("开始转换所选对象",self.start_conversion,rl);self.convert_btn.setObjectName("primary")
        self.cancel_btn=self._button("取消任务",self.job.cancel,rl);self.cancel_btn.setEnabled(False)
        output=W.QGroupBox("输出与批量");ol=W.QVBoxLayout(output)
        self.output_path=W.QLineEdit(self.settings.value("output","") or str(Path.home()/"Documents"/"AeroSliceOutput"))
        ol.addWidget(self.output_path);self._button("选择输出目录",self.choose_output,ol)
        self.output_format=W.QComboBox();self.output_format.addItems(["3MF（多对象毫米模型）","STL（无对象/单位语义）"]);ol.addWidget(self.output_format)
        self.output_format.setCurrentIndex(1)
        self.separate=W.QCheckBox("分别导出转换后的独立零件");ol.addWidget(self.separate)
        self.save_btn=self._button("一键转换并导出",self.save_result,ol);self.save_btn.setObjectName("primary")
        self.save_btn.setToolTip("已有匹配的转换结果时直接保存；否则自动转换并导出。模型文件直接写入所选目录。")
        self.batch_btn=self._button("批量转换列表中的源文件",self.start_batch,ol)
        self._button("打开输出文件夹",self.reveal_output,ol);rl.addWidget(output)
        slice_group=W.QGroupBox("切片验证");sl=W.QVBoxLayout(slice_group)
        self._button("配置切片器并验证已导出模型",self.slice_dialog,sl)
        self._button("导入文本 G-code 检查路径",self.import_gcode,sl)
        self._button("比较 Cura 与目标 G-code",self.compare_gcode,sl)
        self._button("使用说明 / 已知限制",self.show_help,sl);rl.addWidget(slice_group);rl.addStretch()
        right_scroll=W.QScrollArea();right_scroll.setWidgetResizable(True);right_scroll.setWidget(right)
        right_scroll.setMinimumWidth(285)
        split.addWidget(right_scroll);split.setSizes([350,860,290])
        status=W.QHBoxLayout();outer.addLayout(status)
        self.status=W.QLabel("就绪");self.status.setMinimumWidth(300);status.addWidget(self.status,1)
        self.progress=W.QProgressBar();self.progress.setRange(0,100);self.progress.setMinimumWidth(250);status.addWidget(self.progress)
        self.duration=W.QLabel("0.0 s");status.addWidget(self.duration)
        self._controls=[self.open_btn,self.folder_btn,self.clear_btn,self.convert_btn,self.save_btn,self.quick_export_btn,self.batch_btn,self.tree,
                        group,output]

    def reconstruction_changed(self):
        layered=self.reconstruction.currentIndex()==0
        self.layer_height.setEnabled(layered);self.mode.setEnabled(not layered)
        self.auto_surface.setEnabled(self.reconstruction.currentIndex()==1)
        self.surface_resolution.setEnabled(self.reconstruction.currentIndex()==1)
        for field in (self.auto_surface,self.surface_resolution,self.surface_resolution_label,
                      self.reverse_shell,self.confirm,self.merge,self.repair):field.setVisible(not layered)
        if layered:self.mode.setCurrentIndex(1)
        else:self.mode.setCurrentIndex(0)
        self.method_note.setText('输入原本需Surface模式的模型，输出供拓竹奇偶切片。按所选层高重建，保留外皮和筋板截线；保持原Z方向。' if layered else
            '连续曲面沿原面双侧加厚；外轮廓会增加约半个壁厚。' if self.reconstruction.currentIndex()==1 else '按零件树结构类型执行精确偏移；复杂开放曲面可能需要手动指定。')
        for row in self.rows:
            combo=self.tree.itemWidget(row,2)
            if combo:
                with C.QSignalBlocker(combo):
                    for key in ROLE_NAMES:combo.setItemText(combo.findData(key),self.role_text(key))

    def role_text(self,key):
        if self.reconstruction.currentIndex()==0:
            if key=='auto':return 'Surface 自动重建'
            if key=='solid':return '保留实体（不重建）'
        return ROLE_NAMES[key]

    def options(self):
        return Options(mode="regular" if self.mode.currentIndex()==0 else "even-odd", thickness=self.thickness.value(),
                       tolerance=[1e-6,1e-7,1e-5][self.precision.currentIndex()],merge=self.merge.isChecked(),
                       repair=self.repair.isChecked(),confirm_ambiguous=self.confirm.isChecked(),section_count=self.section_count.value(),
                       reverse_shell_normals=self.reverse_shell.isChecked(),
                       reconstruction=['layered','continuous','manual'][self.reconstruction.currentIndex()],layer_height=self.layer_height.value())

    def start_job(self,name,args):
        if self.job.running:return
        self._job_result_key=conversion_digest(args['model'],args['options'],args['auto_surface'],args['resolution']) if name in ('convert','export') else None
        self.job_name=name;self.start_time=time.monotonic();self.progress.setValue(0)
        for control in self._controls:control.setEnabled(False)
        self.cancel_btn.setEnabled(True);self.status.setText("后台处理中…")
        self.feedback.setText("正在转换、验证并导出，请稍候…" if name=="export" else
                              "复用已转换结果，正在保存到所选目录…" if name=="save" else "正在处理模型…")
        self.feedback.setStyleSheet('background:#193c53;padding:10px;border-radius:5px')
        self.elapsed.start();self.job.start(name,args)

    def finished(self):
        self.elapsed.stop();self.tick()
        for control in self._controls:control.setEnabled(True)
        self.cancel_btn.setEnabled(False)

    def tick(self):self.duration.setText(f"{time.monotonic()-self.start_time:.1f} s")
    def on_progress(self,v,t):self.progress.setValue(v);self.status.setText(t)

    def on_done(self,payload):
        name=self.job_name;self.finished()
        if name!='load':self.progress.setValue(100);self.status.setText("任务完成")
        if name=="load":
            model,report=payload
            self.on_progress(92,"建立零件列表")
            self.progress.repaint();self.status.repaint()
            prefix=f"source{len(self.models)}:"
            for part in model.parts:part.group=prefix+part.group
            self.models.append(model);self.add_model(model,report);self.result=None;self.result_key=None;self.last_output=None
            self.diagnostic_report(report)
            self.on_progress(96,"准备三维预览")
            self.progress.repaint();self.status.repaint()
            self.refresh_views();self.fit_views()
            self.on_progress(100,f"读取完成：{len(model.parts)} 个分量")
            self.feedback.setText("模型已导入。点击“一键转换并导出”即可生成模型，输出目录可在右侧修改。")
            self.tick()
            if self.pending:self.start_job("load",{"path":self.pending.pop(0)})
        elif name in ("convert","export"):
            self.result=payload['result'] if name=="export" else payload
            self.result_key=self._job_result_key
            for p,diag in zip(self.result.model.parts,self.result.report['after']['parts']):
                self.problem_faces[id(p)]=list({f for pair in diag['self_intersections']['pairs'] for f in pair})
            self.render_report(self.result.report);self.refresh_views()
            if name=="export":self.export_done(payload['paths'])
            else:self.feedback.setText("转换完成。点击“一键转换并导出”直接保存当前结果；修改转换参数后会重新转换。")
        elif name=="save":
            self.result.report=payload['report'];self.render_report(self.result.report)
            self.export_done(payload['paths'])
        elif name=="batch":
            self.last_output=payload["output_folder"]
            self.report_box.setPlainText(json.dumps(payload,ensure_ascii=False,indent=2))
        elif name in ("slice","gcode"):
            view={k:v for k,v in payload.items() if k not in ("segments","statistics")}
            if "statistics" in payload:view["statistics"]={k:v for k,v in payload["statistics"].items() if k not in ("segments","layers")}
            self.report_box.setPlainText(json.dumps(view,ensure_ascii=False,indent=2))

    def on_error(self,message):
        self.finished();self.status.setText("任务失败；源文件已保留")
        self.report_box.setPlainText(message)
        self.pending=[]
        self.feedback.setText("未导出："+message.split('\n')[0])
        self.feedback.setStyleSheet('background:#67313c;padding:10px;border-radius:5px;color:#fff')
        self.operationFailed.emit(message)
        # A non-modal report remains visible and permits immediate recovery.
        self.error_markers=True;self.refresh_views()

    def on_stopped(self,message):
        self.finished();self.status.setText(message);self.pending=[]
        self.report_box.append(message)
        self.feedback.setText(message)

    def export_done(self,paths):
        self.last_output=paths[0] if paths else None
        self.status.setText("导出成功")
        self.feedback.setText("导出成功："+"；".join(paths)+"\n可点击右侧“打开输出文件夹”查看。")
        self.feedback.setStyleSheet('background:#15513f;padding:10px;border-radius:5px;color:#fff')
        self.report_box.append("\n输出文件：\n"+"\n".join(paths)+"\n检查结果保留在本窗口；输出目录仅保存模型文件。")
        self.exportCompleted.emit(paths)

    def import_paths(self,paths):
        if not paths or self.job.running:return
        self.pending=list(dict.fromkeys(str(Path(p).resolve()) for p in paths))
        self.start_job("load",{"path":self.pending.pop(0)})

    def open_files(self):
        paths,_=W.QFileDialog.getOpenFileNames(self,"导入航模", "", "模型 (*.stl *.3mf)")
        self.import_paths(paths)

    def open_folder(self):
        folder=W.QFileDialog.getExistingDirectory(self,"导入文件夹")
        if folder:self.import_paths(sorted(p for p in Path(folder).rglob("*") if p.suffix.lower() in (".stl",".3mf")))

    def clear_models(self):
        if self.job.running:return
        self.models=[];self.parts=[];self.rows=[];self.tree.clear();self.result=None;self.result_key=None;self.last_output=None;self._edge_cache.clear();self.refresh_views()
        self.feedback.setText('导入 STL / 3MF 后，点击“一键转换并导出”。')

    def add_model(self,model,diagnostic):
        # QTreeWidget emits itemChanged even for programmatic flags/tooltips/checks.
        # Blocking during initialization avoids O(parts^2) whole-scene rebuilds.
        self.tree.setUpdatesEnabled(False)
        try:
            with C.QSignalBlocker(self.tree):
                parent=W.QTreeWidgetItem(self.tree,[Path(model.source).name or "合成模型"]);parent.setExpanded(True)
                for part,diag in zip(model.parts,diagnostic["parts"]):
                    self.problem_faces[id(part)]=list({f for pair in diag['self_intersections']['pairs'] for f in pair})
                    row=W.QTreeWidgetItem(parent,[part.name,"",""])
                    row.setFlags(row.flags()|C.Qt.ItemFlag.ItemIsUserCheckable)
                    row.setCheckState(0,C.Qt.CheckState.Checked);row.setCheckState(1,C.Qt.CheckState.Checked)
                    row.setToolTip(0,diag["reason"])
                    role=W.QComboBox()
                    for key in ROLE_NAMES:role.addItem(self.role_text(key),key)
                    role.setItemData(role.findData('auto'),'Surface输入请选择此项：重建外皮和筋板，生成可供奇偶切片的模型。',C.Qt.ItemDataRole.ToolTipRole)
                    role.setItemData(role.findData('solid'),'仅适用于无需重建的有效闭合实体。此项会跳过Surface重建，开放曲面不能原样保留。',C.Qt.ItemDataRole.ToolTipRole)
                    if part.role!="auto":role.setCurrentIndex(role.findData(part.role))
                    role.currentIndexChanged.connect(lambda _=0,p=part,c=role:self.role_changed(p,c))
                    self.tree.setItemWidget(row,2,role)
                    self.parts.append(part);self.rows.append(row)
        finally:
            self.tree.setUpdatesEnabled(True)

    def role_changed(self,part,combo):
        role=combo.currentData()
        if self.reconstruction.currentIndex()==0 and role=='solid' and not part.mesh.is_volume:
            role='auto'
            with C.QSignalBlocker(combo):combo.setCurrentIndex(combo.findData(role))
            message=f'“{part.name}”不是有效闭合实体，不能选择“不重建”。已改回“Surface 自动重建”，可直接点击“一键转换并导出”。'
            self.feedback.setText(message)
            self.feedback.setStyleSheet('background:#193c53;padding:10px;border-radius:5px')
            self.report_box.setPlainText(message)
        if part.role!=role:
            part.role=role;self.result=None;self.result_key=None;self.refresh_views()

    def tree_changed(self,item,column):
        if column==0:self.result=None
        self.refresh_views()

    def selected_model(self):
        if not any(row.checkState(0)==C.Qt.CheckState.Checked for row in self.rows):
            raise ValueError("请勾选要转换的零件")
        parts=[]
        for i,(p,row) in enumerate(zip(self.parts,self.rows)):
            copy=p.copy()
            if row.checkState(0)!=C.Qt.CheckState.Checked:
                copy.role="keep";copy.group=f"untouched:{i}:{copy.group}"
            parts.append(copy)
        metadata={'raw_topology':[t for m in self.models for t in m.metadata.get('raw_topology',[])]}
        if all('original_component_count' in m.metadata for m in self.models):
            metadata['original_component_count']=sum(m.metadata['original_component_count'] for m in self.models)
        return Model(parts,self.models[0].source if len(self.models)==1 else "",[w for m in self.models for w in m.warnings],metadata)

    def start_conversion(self):
        try:self.start_job("convert",{"model":self.selected_model(),"options":self.options(),
            'auto_surface':self.auto_surface.isChecked() and self.reconstruction.currentIndex()==1,'resolution':self.surface_resolution.value()})
        except Exception as e:self.report_box.setPlainText(str(e))

    def choose_output(self):
        folder=W.QFileDialog.getExistingDirectory(self,"输出目录",self.output_path.text())
        if folder:self.output_path.setText(folder);self.settings.setValue("output",folder)

    def save_result(self):
        if self.job.running:return
        try:
            if not self.models:raise ValueError("请先导入 STL 或 3MF 模型。")
            if not self.output_path.text().strip():raise ValueError("请选择输出目录。")
            model=self.selected_model();options=self.options()
            auto_surface=self.auto_surface.isChecked() and self.reconstruction.currentIndex()==1
            resolution=self.surface_resolution.value()
            key=conversion_digest(model,options,auto_surface,resolution)
            args={"folder":self.output_path.text().strip(),
                "format":"3mf" if self.output_format.currentIndex()==0 else "stl","separate":self.separate.isChecked(),
                "output_name":Path(model.source).stem+"_converted" if model.source else "converted"}
            if self.result is not None and self.result.report.get('status')=='geometry_passed' and self.result_key==key:
                self.start_job('save',dict(args,result=self.result))
            else:
                self.start_job('export',dict(args,model=model,options=options,auto_surface=auto_surface,resolution=resolution))
        except Exception as e:self.on_error(str(e))

    def start_batch(self):
        if not self.models:return
        # Roles are per-file and cannot be blindly reused for an unrelated folder.
        self.report_box.setPlainText("批量使用自动诊断；无法确认的曲面会逐文件失败并在窗口显示原因。手动角色请用逐文件转换或CLI角色JSON。")
        self.start_job("batch",{"files":[m.source for m in self.models],"folder":self.output_path.text(),
                                 "options":self.options(),"format":"3mf" if self.output_format.currentIndex()==0 else "stl"})

    def reveal_output(self):
        path=Path(self.last_output or self.output_path.text())
        if path.is_file():path=path.parent
        path.mkdir(parents=True,exist_ok=True)
        G.QDesktopServices.openUrl(C.QUrl.fromLocalFile(str(path)))

    def camera(self,az,el):
        self.original_view.setCameraPosition(azimuth=az,elevation=el)
        self.converted_view.sync({k:self.original_view.opts[k] for k in ("distance","elevation","azimuth","center")})

    def fit_views(self):
        if not self.parts:return
        bounds=np.array([p.mesh.bounds for p in self.parts]);low=bounds[:,0].min(axis=0);high=bounds[:,1].max(axis=0)
        center=(low+high)/2
        for view in (self.original_view,self.converted_view):
            view.opts["center"]=G.QVector3D(*center)
            view.setCameraPosition(distance=max(float(np.linalg.norm(high-low))*1.5,1),elevation=25,azimuth=-45)

    def _draw_parts(self,view,parts,color=None,alpha=1):
        from .geometry import edge_table
        groups=defaultdict(list);error_lines=[];error_triangles=[]
        style=self.style_combo.currentIndex()
        for part in parts:
            rgba=list(color or COLORS.get(part.role,COLORS['auto']))
            rgba[3]=.35 if style==3 else alpha
            groups[tuple(rgba)].append(part.mesh)
            marked=self.problem_faces.get(id(part),[])
            if marked:error_triangles.append(part.mesh.triangles[marked].reshape(-1,3))
            if alpha==1:
                cached=self._edge_cache.get(id(part.mesh))
                if cached is None or cached[0] is not part.mesh:
                    edges,_,counts,_=edge_table(part.mesh)
                    points=part.mesh.vertices[edges[counts!=2][:5000]].reshape(-1,3)
                    cached=(part.mesh,points);self._edge_cache[id(part.mesh)]=cached
                if len(cached[1]):error_lines.append(cached[1])
        for rgba,meshes in groups.items():
            vertices=[];faces=[];offset=0
            for mesh in meshes:
                vertices.append(mesh.vertices);faces.append(mesh.faces+offset);offset+=len(mesh.vertices)
            item=gl.GLMeshItem(vertexes=np.asarray(np.vstack(vertices),dtype=np.float32),
                               faces=np.asarray(np.vstack(faces),dtype=np.uint32),color=rgba,
                               smooth=False,shader='shaded',drawFaces=style!=2,drawEdges=style in (1,2),edgeColor=(.2,.32,.45,.8))
            if rgba[3]<1:item.setGLOptions('translucent')
            view.addItem(item)
        if error_triangles:
            points=np.vstack(error_triangles)
            view.addItem(gl.GLMeshItem(vertexes=np.asarray(points,dtype=np.float32),faces=np.arange(len(points),dtype=np.uint32).reshape(-1,3),
                                       color=(1,.12,.2,1),smooth=False,shader='shaded'))
        if error_lines:
            view.addItem(gl.GLLinePlotItem(pos=np.vstack(error_lines),color=(1,.25,.3,1),width=2,mode='lines',antialias=True))

    def refresh_views(self,*_):
        if not hasattr(self,"original_view"):return
        self._scene_rebuilds+=1
        active={id(p.mesh) for p in self.parts}
        if self.result:active.update(id(p.mesh) for p in self.result.model.parts)
        self._edge_cache={k:v for k,v in self._edge_cache.items() if k in active}
        for view in (self.original_view,self.converted_view):view.clear()
        mode=self.compare_combo.currentIndex()
        self.original_view.setVisible(mode==0)
        visible=[p for p,row in zip(self.parts,self.rows) if row.checkState(1)==C.Qt.CheckState.Checked]
        if mode==0:self._draw_parts(self.original_view,visible)
        elif mode==1 or not self.result:self._draw_parts(self.converted_view,visible,alpha=.22 if self.result else 1)
        if self.result:
            self._draw_parts(self.converted_view,self.result.model.parts,COLORS["result"],.75 if mode==1 else 1)
            if mode==3:
                for record in self.result.report["comparison"]["structure_samples"]:
                    data=record.get("deviation_samples")
                    if not data:continue
                    d=np.array(data["distance_mm"]);points=np.array(data["points"])
                    scale=np.clip(d/max(self.result.report["comparison"]["sampled_exterior_max_mm"],1e-6),0,1)
                    colors=np.c_[scale,1-scale,np.zeros(len(d)),np.ones(len(d))]
                    self.converted_view.addItem(gl.GLScatterPlotItem(pos=points,color=colors,size=5,pxMode=True))

    def diagnostic_report(self,report):
        lines=[f"读取 {len(report['parts'])} 个分量；开放边 {report['open_edges']}；非流形边 {report['nonmanifold_edges']}"]
        for i,p in enumerate(report["parts"]):
            t=p["topology"];lines.append(f"[{i}] {p['name']}  类型 {p['category']}  {t['faces']:,}面  开放边{t['open_edges']}\n{p['reason']}")
        lines+=report["warnings"]
        lines.append("已完成导入快速诊断。点击“一键转换并导出”自动执行几何转换、验证及保存。实体化壁厚不等于打印线宽。")
        self.report_box.setPlainText("\n".join(lines))

    def render_report(self,r):
        c=r["comparison"]
        lines=[f"状态：{r['status']}；耗时 {r['elapsed_seconds']} s；模式 {r['mode']}",
               f"开放边 {r['before']['open_edges']} → {r['after']['open_edges']}；分量 {r['before']['component_count']} → {r['after']['component_count']}",
               f"采样外表面偏差 最大 {c['sampled_exterior_max_mm']:.6g} mm / 平均 {c['sampled_exterior_mean_mm']:.6g} mm",
               f"原尺寸范围 {np.round(c['original_bounds_mm'],3).tolist()}\n输出范围 {np.round(c['output_bounds_mm'],3).tolist()}",
               f"输出材料体积 {c['output_volume_mm3']:.3f} mm³；估算质量 {c['estimated_mass_g']:.3f} g；"+
               ('逐层结构' if c['physical_solid_components'] is None else f"独立实体 {c['physical_solid_components']}"),
               c['mass_conditions'],"实际切片验证：未运行。几何通过不等于切片/打印通过。"]
        if r.get('method')=='unsigned_distance_thinwall':
            lines.insert(1,f"复杂曲面近似重建：外轮廓向外增加约 {r['thickness_mm']/2:g} mm；偏差按输出表面到源曲面统计。")
        if r.get('method')=='layered_sections':
            lines[2]=f"逐层截线覆盖检查：全部处理层，XY容差0.008mm；层高 {r['layer_height_mm']:g}mm。相邻层接触面保留。"
            lines.insert(1,'原方案逐层轮廓重建：必须用Even-Odd、Arachne和原Z方向；关闭自适应层高。')
        lines+=r["actions"]+r["issues"]
        self.report_box.setPlainText("\n".join(lines))

    def slice_dialog(self):
        if self.job.running:return
        if not self.last_output or not Path(self.last_output).is_file():
            self.report_box.append("请先导出一个测试模型，再运行切片验证。");return
        exe,_=W.QFileDialog.getOpenFileName(self,"选择切片器可执行文件",self.settings.value("slicer",""),"程序 (*.exe)")
        if not exe:return
        self.settings.setValue("slicer",exe)
        dialog=W.QDialog(self);dialog.setWindowTitle("切片配置");form=W.QFormLayout(dialog)
        fields=[]
        for label in ("机器JSON / Prusa完整INI","工艺JSON（Prusa可留空）","耗材JSON（Prusa可留空）"):
            row=W.QHBoxLayout();field=W.QLineEdit();row.addWidget(field)
            button=W.QPushButton("选择");row.addWidget(button)
            button.clicked.connect(lambda _=False,f=field:f.setText(W.QFileDialog.getOpenFileName(dialog,"选择完整切片配置","","配置 (*.json *.ini)")[0]))
            form.addRow(label,row);fields.append(field)
        form.addRow(W.QLabel("软件会检查CLI帮助；无法确认接口时改为手动验证。"))
        buttons=W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Ok|W.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);form.addRow(buttons)
        if dialog.exec()!=W.QDialog.DialogCode.Accepted:return
        self.start_job("slice",{"exe":exe,"model_path":self.last_output,"folder":str(unique_folder(self.output_path.text(),"slice")),
                                "settings":[f.text() for f in fields[:2] if f.text()],"filament":fields[2].text() or None})

    def import_gcode(self):
        path,_=W.QFileDialog.getOpenFileName(self,"导入文本G-code","","G-code (*.gcode *.gco)")
        if path:self.start_job("gcode",{"path":path})

    def compare_gcode(self):
        reference,_=W.QFileDialog.getOpenFileName(self,"选择原始Cura G-code","","G-code (*.gcode *.gco)")
        if not reference:return
        path,_=W.QFileDialog.getOpenFileName(self,"选择转换后目标G-code","","G-code (*.gcode *.gco)")
        if path:self.start_job("gcode",{"path":path,"reference":reference})

    def show_help(self):
        self.report_box.setPlainText('1. 导入原始STL/3MF（毫米），选择重建方式和输出格式，点击“一键转换并导出”。\n2. 默认逐层轮廓：沿原始曲面每层截线生成封闭薄层，保留外皮及筋板的截线，不填满空腔。\n3. 切片使用Even-Odd、Arachne、与重建相同的固定层高、1墙、100%材料区域填充、顶底0层。保持原Z方向，关闭自适应层高及自动旋转。\n4. 逐层成品有层状纹理、相邻层接触面；小于层高的细节及水平薄片不保证保留。不要对整栈自动修复或布尔合并。\n5. 连续曲面方式仍可选：双侧薄壁重建，外轮廓约增加半个壁厚，使用普通实体切片。\n3MF仅保存几何及约束提示；切片机型、耗材需另设。STL切片约束请在本窗口查看。导出直接写入所选目录，仅保存模型文件。已有匹配转换结果时直接保存；修改转换参数后会重新转换。几何通过不等于实际切片或物理打印通过。\n源文件不覆盖。MeshLib许可与再分发限制详见随包licenses和README。')

    def closeEvent(self,event):
        if self.job.running:
            self.job.event.set();self.job.finish()
        self.settings.setValue("output",self.output_path.text())
        event.accept()


def launch():
    mp.freeze_support()
    C.QCoreApplication.setAttribute(C.Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app=W.QApplication.instance() or W.QApplication(sys.argv[:1])
    app.setApplicationName("AeroSlice Converter")
    window=Window();window.show()
    return app.exec()

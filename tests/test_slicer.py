import json
from aeroslice.slicer import run_slicer


def test_gcode_generation_and_project_export_failure_are_distinguished(tmp_path,monkeypatch):
    monkeypatch.setattr('aeroslice.slicer.probe',lambda *args:{'kind':'bambu','detection':'test'})
    class Process:
        returncode=4294967283
        def __init__(self,args,**kwargs):
            folder=kwargs['cwd']
            (folder/'plate_1.gcode').write_text('G21\nG90\nM83\nG1 Z0.2\nG1 Y20 E1\n')
            (folder/'result.json').write_text(json.dumps({'return_code':-13,'error_string':'Failed exporting 3mf files.'}))
        def poll(self):return self.returncode
    monkeypatch.setattr('aeroslice.slicer.subprocess.Popen',Process)
    report=run_slicer('bambu-studio.exe',tmp_path/'input.stl',tmp_path/'result',
                       [tmp_path/'machine.json',tmp_path/'process.json'],tmp_path/'filament.json')
    assert report['status']=='paths_detected_project_export_failed'
    assert report['statistics']['extrusion_moves']==1
    assert report['project_export_error']['returncode']==4294967283

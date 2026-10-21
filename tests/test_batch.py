from pathlib import Path
from aeroslice.batch import run_batch
from aeroslice.core import Options, Model, Part, sha256
from aeroslice.fixtures import sheet
from aeroslice.fileio import export_model


def test_batch_one_failure_does_not_abort_and_source_protected(tmp_path):
    good=tmp_path/'good.stl';bad=tmp_path/'bad.stl'
    export_model(Model([Part('sheet',sheet())]),good)
    original=sha256(good)
    bad.write_bytes(b'invalid')
    result=run_batch([bad,good],tmp_path/'out',Options(section_count=1))
    assert [e['status'] for e in result['entries']]==['failed','geometry_passed']
    assert sha256(good)==original
    assert (Path(result['output_folder'])/'001_bad'/'error.json').exists()
    assert (Path(result['output_folder'])/'002_good'/'conversion_report.json').exists()


def test_gui_batch_reports_remain_in_memory(tmp_path):
    good=tmp_path/'good.stl';bad=tmp_path/'bad.stl'
    export_model(Model([Part('sheet',sheet())]),good);bad.write_bytes(b'invalid')
    result=run_batch([bad,good],tmp_path/'out',Options(section_count=1),fmt='stl',write_reports=False)
    assert [e['status'] for e in result['entries']]==['failed','geometry_passed']
    assert result['entries'][0]['error']
    assert not list(Path(result['output_folder']).rglob('*.json'))
    assert len(list(Path(result['output_folder']).rglob('*.stl')))==1

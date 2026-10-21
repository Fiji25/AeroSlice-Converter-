import numpy as np
import trimesh
from aeroslice.core import Part,Model,Options
from aeroslice.fileio import export_model,load_model
from aeroslice.fixtures import sheet
from aeroslice.analysis import analyze


def test_input_nonmanifold_counts_survive_manifold_patch_extraction(tmp_path):
    original=sheet()
    mesh=trimesh.Trimesh(np.vstack([original.vertices,[2,0,12]]),np.vstack([original.faces,[0,2,4]]),process=False)
    path=tmp_path/'junction.stl'
    export_model(Model([Part('junction',mesh)]),path)
    result=analyze(load_model(path),Options(section_count=1))
    assert result['nonmanifold_edges']==1
    assert result['open_edges']==6
    assert result['component_count']==1
    assert result['patch_component_count']==3
    assert result['patch_open_edges']==9

import pytest
import numpy as np
import trimesh
from aeroslice.core import Model,Part,Options,Context,GeometryError,mesh_digest
from aeroslice.fixtures import sheet
from aeroslice.converters import convert
from aeroslice.ready import convert_ready,_voxel_size


def test_even_odd_repairs_inconsistent_winding_with_required_dependency():
    original=sheet();faces=original.faces.copy();faces[1]=faces[1,::-1]
    mesh=trimesh.Trimesh(original.vertices,faces,process=False)
    digest=mesh_digest(mesh)
    assert not mesh.is_winding_consistent
    result=convert(Model([Part('反向面',mesh)]),Options(mode='even-odd',section_count=1))
    assert result.model.mesh.is_winding_consistent
    assert result.report['status']=='needs_review'  # Repairing normals does not thicken a sheet.
    assert mesh_digest(mesh)==digest


def test_one_click_even_odd_open_surfaces_give_actionable_mode_error():
    with pytest.raises(GeometryError,match='Regular'):
        convert_ready(Model([Part('开放加强片',sheet())]),Options(mode='even-odd'))


def test_large_part_keeps_four_cells_across_wall_when_grid_adjusts():
    voxel=_voxel_size(103182.6847,.45,.1)
    assert .1<voxel<=.11
    assert .45/voxel>=4
    assert 103182.6847/voxel**2<=10_000_000

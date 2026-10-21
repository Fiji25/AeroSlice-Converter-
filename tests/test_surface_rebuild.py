import numpy as np
import trimesh
from aeroslice.core import Context,Model,Part,Options,mesh_digest
from aeroslice.fixtures import sheet,holed_sheet
from aeroslice.ready import _rebuild,convert_ready,_native,_repair_generated_surface
from aeroslice.geometry import topology


def test_distance_surface_preserves_through_hole_and_source():
    source=holed_sheet();digest=mesh_digest(source)
    output,record=_rebuild(source,.45,.1,Context())
    assert output.is_volume and topology(output)['duplicate_faces']==0
    assert not output.contains([[0,0,0]])[0]
    assert output.contains([[6,0,0]])[0]
    assert record['source_points_outside']==0 and record['unexpected_filled_voids']==0
    assert record['source_points_checked']==len(source.vertices)+len(source.faces)
    assert mesh_digest(source)==digest


def test_generated_fold_is_repaired_without_changing_source():
    from meshlib import mrmeshpy as mm
    source=trimesh.creation.box();vertices=source.vertices.copy()
    vertices[7]=[-.7,-.7,-.7];source.vertices=vertices
    digest=mesh_digest(source);native=_native(source)
    assert len(mm.findSelfCollidingTriangles(mm.MeshPart(native)))>0
    assert _repair_generated_surface(native,Context())>0
    assert native.topology.isClosed()
    assert len(mm.findSelfCollidingTriangles(mm.MeshPart(native)))==0
    assert mesh_digest(source)==digest


def test_nonmanifold_crossed_aircraft_sheets_become_joined_volume():
    a=sheet(8,10);b=a.copy();b.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2,[0,0,1]))
    source=trimesh.util.concatenate([a,b]);digest=mesh_digest(source)
    result=convert_ready(Model([Part('交叉加强片',source)]),Options(section_count=2))
    assert result.report['method']=='unsigned_distance_thinwall'
    assert result.report['status']=='geometry_passed'
    assert result.model.mesh.is_volume
    assert result.report['comparison']['physical_solid_components']==1
    assert result.report['after']['open_edges']==0
    assert mesh_digest(source)==digest

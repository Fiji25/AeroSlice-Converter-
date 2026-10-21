import numpy as np
import pytest
import trimesh
from threading import Event
from aeroslice.core import Model, Part, Options, Context, Cancelled, GeometryError, mesh_digest
from aeroslice.geometry import topology, patches, self_intersections
from aeroslice.fixtures import wing, wing_with_ribs, sheet, holed_sheet
from aeroslice.solidify import solidify
from aeroslice.converters import convert
from aeroslice.sections import sections


def test_open_and_nonmanifold_detection():
    m=sheet()
    assert topology(m)["open_edges"]==4
    v=np.vstack([m.vertices,[2,0,12]])
    bad=trimesh.Trimesh(v,np.vstack([m.faces,[0,2,4]]),process=False)
    assert topology(bad)["nonmanifold_edges"]==1
    ps=patches(bad,manifold_only=True)
    assert sum(len(p.faces) for p in ps)==3
    assert len(ps)==3


@pytest.mark.parametrize("thickness",[.4,.42,.45,.5,.6,.8])
def test_sheet_solidify_preserves_center_and_thickness(thickness):
    original=sheet()
    before=mesh_digest(original)
    result=solidify(original,thickness)
    assert result.is_volume and topology(result)["open_edges"]==0
    assert result.extents[0]==pytest.approx(thickness)
    assert result.volume==pytest.approx(20*25*thickness)
    assert result.centroid[0]==pytest.approx(0)
    assert mesh_digest(original)==before


def test_hole_is_not_filled():
    result=solidify(holed_sheet(),.45)
    assert result.is_volume
    assert result.volume==pytest.approx((24*20-6*4)*.45)
    assert not result.contains([[0,0,0]])[0]
    assert result.contains([[6,0,0]])[0]


def test_user_can_reverse_open_shell_offset_direction():
    forward=solidify(sheet(),.45,'shell')
    reverse=solidify(sheet(),.45,'shell',reverse_normals=True)
    np.testing.assert_allclose(forward.bounds[:,0],[-.45,0])
    np.testing.assert_allclose(reverse.bounds[:,0],[0,.45])


def test_open_wing_inward_offset_preserves_outer_vertices():
    m=wing(caps=False)
    result=solidify(m,.45,"shell")
    assert result.is_volume
    # The original external vertices occur exactly in the output.
    from scipy.spatial import cKDTree
    assert cKDTree(result.vertices).query(m.vertices)[0].max() == 0
    assert result.volume < 2*m.area*.45


def test_synthetic_airfoil_internal_crossed_ribs_regular():
    source=wing_with_ribs()
    hashes=[mesh_digest(p.mesh) for p in source.parts]
    result=convert(source,Options(section_count=5))
    assert result.report["status"]=="geometry_passed"
    assert all(p.mesh.is_volume for p in result.model.parts)
    assert len(result.model.parts)==1
    assert result.report["after"]["open_edges"]==0
    assert result.report["comparison"]["sampled_exterior_max_mm"]<.0001
    assert result.report["comparison"]["uncovered_source_parts"]==[]
    assert result.report["comparison"]["physical_solid_components"]==1
    assert result.model.mesh.volume < source.parts[0].mesh.volume * .4
    assert [mesh_digest(p.mesh) for p in source.parts]==hashes


def test_closed_envelope_cannot_be_silently_solid():
    source=wing_with_ribs()
    for p in source.parts:p.role="auto"
    with pytest.raises(GeometryError,match="实心"):convert(source,Options(section_count=2))


def test_self_intersection_detected_and_rejected():
    a=sheet()
    b=sheet();b.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2,[0,0,1]))
    m=trimesh.util.concatenate([a,b])
    assert self_intersections(m)["pairs"]
    with pytest.raises(GeometryError,match="自相交"):solidify(m)


def test_intersection_deadline_cannot_be_reported_complete():
    result=self_intersections(wing(),time_budget=-1)
    assert result['status']=='partial'


def test_even_odd_open_structure_not_claimed_compatible():
    result=convert(Model([Part("open",sheet())]),Options(mode="even-odd",section_count=3))
    assert not result.report["even_odd_recommended"]
    assert any("薄壁" in issue for issue in result.report["issues"])
    assert result.report["after"]["open_edges"]==4


def test_even_odd_closed_airfoil_and_duplicate_cleanup():
    m=wing()
    # Input orientation remains intact after removing an identical face.
    m=trimesh.Trimesh(m.vertices,np.vstack([m.faces,m.faces[:1]]),process=False)
    result=convert(Model([Part("wing",m)]),Options(mode="even-odd",section_count=3))
    assert result.report["after"]["parts"][0]["topology"]["duplicate_faces"]==0
    assert result.report["even_odd_recommended"]


def test_sections_include_internal_open_and_crossing_lines():
    source=wing_with_ribs()
    report=sections(source.mesh,3)
    assert any(layer["crossings"] or layer["junction_nodes"] for layer in report["layers"])


def test_cancel_does_not_modify_source():
    source=Model([Part("sheet",sheet())])
    original=mesh_digest(source.mesh)
    event=Event();event.set()
    with pytest.raises(Cancelled):convert(source,ctx=Context(event))
    assert mesh_digest(source.mesh)==original


def test_ambiguous_curved_open_requires_role():
    with pytest.raises(GeometryError,match="无法判断"):convert(Model([Part("wing",wing(caps=False))]))


def test_independent_assembly_groups_are_not_glued():
    a=sheet();b=sheet();b.apply_translation([0.1,0,0])
    result=convert(Model([Part("a",a,"a","sheet"),Part("b",b,"b","sheet")]),Options(section_count=1))
    assert len(result.model.parts)==2


def test_keep_role_never_unions_or_reorients_the_part():
    outer=wing()
    original=mesh_digest(outer)
    scene=Model([Part('keep',outer,'same','keep'),Part('sheet',sheet(),'same','sheet')])
    result=convert(scene,Options(section_count=1))
    kept=next(p for p in result.model.parts if p.name=='keep')
    assert mesh_digest(kept.mesh)==original
    assert len(result.model.parts)==2

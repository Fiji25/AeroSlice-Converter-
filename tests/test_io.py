from pathlib import Path
import zipfile
import numpy as np
import pytest
import trimesh
from aeroslice.core import Model, Part, GeometryError
from aeroslice.fixtures import wing, sheet
from aeroslice.fileio import load_model, read_3mf, export_model, CORE, PROD


@pytest.mark.parametrize("binary", [True, False])
def test_stl_round_trip(tmp_path, binary):
    m = wing()
    path = tmp_path / "wing.stl"
    path.write_bytes(trimesh.exchange.stl.export_stl(m) if binary else trimesh.exchange.stl.export_stl_ascii(m).encode())
    scene = load_model(path)
    np.testing.assert_allclose(scene.mesh.bounds, m.bounds, atol=1e-5)
    assert len(scene.mesh.faces) == len(m.faces)
    out = tmp_path / "result.stl"
    assert export_model(scene, out)
    assert load_model(out).mesh.is_watertight


def test_multi_3mf_roundtrip(tmp_path):
    m = wing()
    other = sheet(); other.apply_translation([100, 5, 3])
    model = Model([Part("机翼", m), Part("加强片", other)])
    path = tmp_path / "multi.3mf"
    export_model(model, path)
    result = load_model(path)
    assert len(result.parts) == 2
    np.testing.assert_allclose(result.mesh.bounds, model.mesh.bounds)
    assert result.parts[0].name == "机翼"


def package(path, xml, extra=None):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("3D/3dmodel.model", xml)
        for n,b in (extra or {}).items():
            info=zipfile.ZipInfo(n)
            info.filename=n  # Preserve malicious backslash instead of Windows normalizing it.
            z.writestr(info,b)


def base_model(unit="millimeter", component="", build='objectid="1"'):
    return f'''<model xmlns="{CORE}" xmlns:p="{PROD}" unit="{unit}"><resources>
    <object id="1"><mesh><vertices><vertex x="0" y="0" z="0"/><vertex x="1" y="0" z="0"/><vertex x="0" y="1" z="0"/></vertices><triangles><triangle v1="0" v2="1" v3="2"/></triangles></mesh></object>
    {component}</resources><build><item {build}/></build></model>'''


def test_units_instances_nested_rotation(tmp_path):
    component = '<object id="2"><components><component objectid="1" transform="0 1 0 -1 0 0 0 0 1 2 3 4"/><component objectid="1" transform="1 0 0 0 1 0 0 0 1 5 0 0"/></components></object>'
    path = tmp_path / "instances.3mf"
    package(path, base_model("inch", component, 'objectid="2" transform="1 0 0 0 1 0 0 0 1 10 0 0"'))
    model = read_3mf(path)
    assert len(model.parts) == 2
    np.testing.assert_allclose(model.parts[0].mesh.bounds, [[11*25.4,3*25.4,4*25.4],[12*25.4,4*25.4,4*25.4]])
    np.testing.assert_allclose(model.parts[1].mesh.bounds[:,0], [15*25.4,16*25.4])


def test_production_external_embedded_component(tmp_path):
    main = f'<model xmlns="{CORE}" xmlns:p="{PROD}" requiredextensions="p"><resources><object id="5"><components><component objectid="1" p:path="/3D/Objects/a.model" transform="1 0 0 0 1 0 0 0 1 4 0 0"/></components></object></resources><build><item objectid="5"/></build></model>'
    path=tmp_path/"production.3mf"
    package(path, main, {"3D/Objects/a.model":base_model()})
    result=read_3mf(path)
    np.testing.assert_allclose(result.mesh.bounds[:,0], [4,5])


@pytest.mark.parametrize("payload", ["../escape", "C:/bad", "3D/../../bad", "3D\\evil", "%2e%2e/evil"])
def test_zip_path_safety(tmp_path,payload):
    path=tmp_path/"bad.3mf"
    package(path,base_model(),{payload:"x"})
    with pytest.raises(GeometryError): load_model(path)


def test_evil_xml_and_cycles(tmp_path):
    path=tmp_path/"evil.3mf"
    package(path, '<!DOCTYPE model [<!ENTITY x "BAD">]>' + base_model())
    with pytest.raises(Exception): load_model(path)
    component='<object id="2"><components><component objectid="2"/></components></object>'
    package(path,base_model(component=component,build='objectid="2"'))
    with pytest.raises(GeometryError,match="循环"): load_model(path)


def test_metadata_warning_and_exclusive_output(tmp_path):
    path=tmp_path/"source.3mf"
    package(path,base_model(),{"Metadata/project_settings.config":"{}"})
    result=load_model(path)
    assert any("工程" in w for w in result.warnings)
    source=path.read_bytes()
    with pytest.raises(FileExistsError): export_model(result,path)
    assert path.read_bytes()==source


def test_unknown_required_extension_rejected(tmp_path):
    path=tmp_path/"required.3mf"
    package(path,base_model().replace('unit="millimeter"','xmlns:q="http://example.invalid" requiredextensions="q"'))
    with pytest.raises(GeometryError,match="必需扩展"): load_model(path)

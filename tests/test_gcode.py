import pytest
from aeroslice.gcode import parse_gcode, compare_paths


def test_gcode_absolute_relative_retraction_reset(tmp_path):
    path=tmp_path/"test.gcode"
    path.write_text("G21\nG90\nM82\nG1 Z0.2\nG1 X10 E1\nG1 E0.5\nG1 E1\nG92 E0\nG1 Y10 E1\nM83\nG1 X0 E1\nG1 E-1\nG1 E1\nG1 Z0.4\nG1 X10 E1\n")
    report=parse_gcode(path)
    assert report["layer_count"]==2
    assert report["extrusion_moves"]==4
    assert report["deposited_filament_mm"]==pytest.approx(4)
    assert compare_paths(report,report)["sampled_nearby_fraction"]==1

"""Original synthetic aircraft-like fixtures, freely redistributable (CC0)."""
from pathlib import Path
import numpy as np
import trimesh
from .core import Part, Model, write_json
from .fileio import export_model
from .solidify import boolean


def sheet(width=20., height=25., x=0.):
    return trimesh.Trimesh([[x, -width/2, 0], [x, width/2, 0], [x, width/2, height], [x, -width/2, height]],
                          [[0, 1, 2], [0, 2, 3]], process=False)


def wing(chord=80., span=32., samples=72, caps=True):
    # NACA0018 profile truncated at 92% chord, retaining a finite trailing edge
    # for meaningful inward offset tests. This is not a full trailing-edge test.
    x = (1 - np.cos(np.linspace(0, np.arccos(1 - 2*.92), samples))) / 2
    y = 5*.18*(.2969*np.sqrt(x) - .126*x - .3516*x**2 + .2843*x**3 - .1015*x**4)
    ring = np.vstack([np.c_[x, y], np.c_[x[1:][::-1], -y[1:][::-1]]]) * chord
    n = len(ring)
    vertices = np.vstack([np.c_[ring, np.zeros(n)], np.c_[ring, np.full(n, span)]])
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces.extend([[i, j, j+n], [i, j+n, i+n]])
    if caps:
        vertices = np.vstack([vertices, [chord*.4, 0, 0], [chord*.4, 0, span]])
        for i in range(n):
            j = (i+1) % n
            faces.extend([[2*n, j, i], [2*n+1, i+n, j+n]])
    m = trimesh.Trimesh(vertices, faces, process=False)
    trimesh.repair.fix_normals(m)
    return m


def wing_with_ribs():
    envelope = wing()
    # Both ribs reach the envelope's side surfaces and run almost spanwise;
    # clipping after symmetric offset preserves the outer airfoil.
    ribs = []
    for x in (24., 44.):
        y = 5*.18*(.2969*np.sqrt(x/80) - .126*x/80 - .3516*(x/80)**2 + .2843*(x/80)**3 - .1015*(x/80)**4)*80
        r = sheet(y*2, 31., x)
        r.apply_translation([0, 0, .5])
        ribs.append(r)
    center = trimesh.Trimesh([[10, 0, .5], [66, 0, .5], [66, 0, 31.5], [10, 0, 31.5]], [[0,1,2],[0,2,3]], process=False)
    return Model([Part("NACA0018外皮", envelope, "wing", "shell"),
                  Part("前加强片", ribs[0], "wing", "sheet"),
                  Part("后加强片", ribs[1], "wing", "sheet"),
                  Part("交叉加强片", center, "wing", "sheet")])


def holed_sheet():
    # Rectangular annulus in XY, open central through-channel stays open after offset.
    v = np.array([[-12,-10,0],[12,-10,0],[12,10,0],[-12,10,0],[-3,-2,0],[3,-2,0],[3,2,0],[-3,2,0]], float)
    f = []
    for i in range(4):
        j=(i+1)%4
        f.extend([[i,j,j+4],[i,j+4,i+4]])
    return trimesh.Trimesh(v, f, process=False)


def generate(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    models = {
        "closed_wing": Model([Part("闭合翼型", wing(), role="solid")]),
        "open_wing": Model([Part("开放翼型外壳", wing(caps=False), role="shell")]),
        "wing_internal_cross_ribs": wing_with_ribs(),
        "open_sheet": Model([Part("零厚度加强片", sheet(), role="sheet")]),
        "through_hole": Model([Part("带贯通孔的片", holed_sheet(), role="sheet")]),
    }
    a, b = wing(chord=40., span=15.), wing(chord=40., span=15.)
    b.apply_translation([8, 0, 0])
    models["overlap_wings"] = Model([Part("重叠翼型1", a, "one", "solid"), Part("重叠翼型2", b, "two", "solid")])
    multi = wing_with_ribs()
    other = wing(chord=25, span=12)
    other.apply_translation([90, 10, 4])
    multi.parts.append(Part("独立舵面", other, "control_surface", "solid"))
    models["multi_parts"] = multi
    nonmanifold = sheet()
    v = np.vstack([nonmanifold.vertices, [5, 0, 12]])
    f = np.vstack([nonmanifold.faces, [0, 2, 4]])
    models["nonmanifold"] = Model([Part("非流形T接", trimesh.Trimesh(v, f, process=False))])
    for name, model in models.items():
        for ext in ("stl", "3mf"):
            path = folder / f"{name}.{ext}"
            if not path.exists():
                export_model(model, path)
        write_json(folder / f"{name}.roles.json", {str(i): p.role for i,p in enumerate(model.parts)})
    write_json(folder / "fixture_manifest.json", {"license": "CC0-1.0", "models": list(models),
                "notes": "自主生成；NACA0018外皮采用有限尾缘；不代表商业模型验收"})
    return models

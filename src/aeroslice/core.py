from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from threading import Event
from typing import Callable
import hashlib
import json
import numpy as np
import trimesh


class GeometryError(ValueError):
    """An operation cannot safely produce the requested geometry."""


class Cancelled(Exception):
    pass


@dataclass
class Context:
    cancel: Event = field(default_factory=Event)
    progress: Callable[[int, str], None] = lambda value, text: None

    def check(self, value: int | None = None, text: str = ""):
        if self.cancel.is_set():
            raise Cancelled("任务已取消；源文件保持不变")
        if value is not None:
            self.progress(value, text)

    def scaled(self, low, high):
        """Map a child task's local progress into its parent's stage."""
        return Context(self.cancel,lambda value,text:self.check(
            int(low+(high-low)*max(0,min(100,value))/100),text))


@dataclass
class Part:
    name: str
    mesh: trimesh.Trimesh
    group: str = "object"
    role: str = "auto"  # auto / solid / shell / sheet / keep
    source_id: str = ""

    def copy(self, mesh=None):
        return Part(self.name, self.mesh.copy() if mesh is None else mesh,
                    self.group, self.role, self.source_id)


@dataclass
class Model:
    parts: list[Part]
    source: str = ""
    warnings: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def mesh(self):
        return trimesh.util.concatenate([p.mesh for p in self.parts])


@dataclass
class Options:
    mode: str = "regular"
    thickness: float = 0.45
    tolerance: float = 1e-6
    merge: bool = True
    repair: bool = True
    confirm_ambiguous: bool = False
    section_count: int = 9
    max_faces: int = 1_500_000
    intersection_budget: int = 200_000
    density: float = 1.24
    reverse_shell_normals: bool = False
    reconstruction: str = "continuous"  # continuous / layered / manual
    layer_height: float = .2

    def validate(self):
        if self.reconstruction not in ('continuous','layered','manual'):
            raise ValueError('未知重建方式')
        if not np.isfinite(self.layer_height) or not .05 <= self.layer_height <= .4:
            raise ValueError('重建层高必须为0.05–0.40 mm')
        if self.reconstruction == 'layered' and self.mode != 'even-odd':
            raise ValueError('逐层轮廓重建需要Even-Odd模式；请保持重建层高和原Z方向')
        if self.mode not in ("regular", "even-odd"):
            raise ValueError("未知转换模式")
        if not np.isfinite(self.thickness) or not 0.01 <= self.thickness <= 10:
            raise ValueError("壁厚必须在 0.01–10 mm 之间")
        if not np.isfinite(self.tolerance) or not 1e-9 <= self.tolerance <= 0.01:
            raise ValueError("精度必须在 1e-9–0.01 mm 之间")
        if not 1 <= self.section_count <= 100 or self.max_faces < 1:
            raise ValueError("无效的截面数量或面数上限")


def mesh_digest(mesh):
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(mesh.vertices, dtype="<f8").tobytes())
    h.update(np.ascontiguousarray(mesh.faces, dtype="<i8").tobytes())
    return h.hexdigest()


def conversion_digest(model, options, auto_surface, resolution):
    """Identify the input of a conversion, independent of its output location."""
    state = dict(options=asdict(options), auto_surface=bool(auto_surface), resolution=resolution,
                 source=model.source, metadata=model.metadata, warnings=model.warnings,
                 parts=[dict(name=p.name, group=p.group, role=p.role, source_id=p.source_id,
                             geometry=mesh_digest(p.mesh)) for p in model.parts])
    return hashlib.sha256(json.dumps(state, sort_keys=True, default=jsonable,
                                    allow_nan=False).encode('utf-8')).hexdigest()


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for data in iter(lambda: f.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


def jsonable(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    raise TypeError(type(value).__name__)


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2,
                                    default=jsonable, allow_nan=False), encoding="utf-8")

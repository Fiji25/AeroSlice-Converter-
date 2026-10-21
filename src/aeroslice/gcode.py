"""Streaming analysis of text G-code; relative E, G92, retract debt, units, tools."""
from pathlib import Path
import math
import re
from collections import defaultdict
import numpy as np


def parse_gcode(path, max_segments=250000):
    with Path(path).open("rb") as f:
        if b"\x00" in f.read(256):
            raise ValueError("不支持二进制BGCODE；请导出文本G-code")
    xyz = np.zeros(3)
    absolute, absolute_e, unit, tool = True, True, 1., 0
    epos, retract = defaultdict(float), defaultdict(float)
    layers, segments, filament, extrusion_moves = defaultdict(int), [], defaultdict(float), 0
    unsupported = set()
    for raw in Path(path).open(encoding="utf-8", errors="replace"):
        code = raw.split(";", 1)[0].strip().upper()
        code = re.sub(r"\([^)]*\)", "", code)
        if not code:
            continue
        tokens = re.findall(r"([A-Z])\s*([-+]?(?:\d*\.\d+|\d+\.?\d*))", code)
        if not tokens:
            continue
        command = tokens[0][0] + str(int(float(tokens[0][1])))
        values = {k: float(v) for k, v in tokens[1:]}
        if command == "G90": absolute = True
        elif command == "G91": absolute = False
        elif command == "M82": absolute_e = True
        elif command == "M83": absolute_e = False
        elif command == "G20": unit = 25.4
        elif command == "G21": unit = 1.
        elif command.startswith("T"): tool = int(float(tokens[0][1]))
        elif command == "G92":
            for i,k in enumerate("XYZ"):
                if k in values: xyz[i] = values[k] * unit
            if "E" in values: epos[tool] = values["E"] * unit
        elif command in ("G0", "G1", "G2", "G3"):
            end = xyz.copy()
            for i,k in enumerate("XYZ"):
                if k in values: end[i] = values[k] * unit + (0 if absolute else xyz[i])
            delta = 0.
            if "E" in values:
                delta = values["E"] * unit - (epos[tool] if absolute_e else 0.)
                epos[tool] = values["E"] * unit if absolute_e else epos[tool] + delta
            if delta < 0:
                retract[tool] += -delta
            elif delta > 0:
                repaid = min(retract[tool], delta)
                retract[tool] -= repaid
                deposited = delta - repaid
                if np.linalg.norm(end[:2] - xyz[:2]) > 1e-8 and deposited > 0:
                    extrusion_moves += 1
                    filament[tool] += deposited
                    z = round(float(end[2]), 4)
                    layers[z] += 1
                    if len(segments) < max_segments:
                        segments.append([*xyz, *end, deposited])
            if command in ("G2", "G3"):
                unsupported.add("G2/G3圆弧仅记录端点，覆盖比较不适用于圆弧")
            xyz = end
        elif command in ("G10", "G11"):
            unsupported.add("固件回抽G10/G11无法量化")
    return dict(status="analyzed", layer_count=len(layers), layers={str(k):v for k,v in sorted(layers.items())},
                extrusion_moves=extrusion_moves, deposited_filament_mm=sum(filament.values()),
                filament_by_tool=dict(filament), segments=segments,
                segment_sample_truncated=extrusion_moves > max_segments, warnings=sorted(unsupported),
                note="只表示检测到挤出运动，不能单独证明所有加强片路径完整；耗材统计不含启动排料")


def compare_paths(a, b, xy_tolerance=.5, z_tolerance=.05):
    from scipy.spatial import cKDTree
    def midpoints(report):
        x = np.array(report["segments"])
        return (x[:, :3] + x[:, 3:6]) / 2 if len(x) else np.empty((0,3))
    aa, bb = midpoints(a), midpoints(b)
    if not len(aa) or not len(bb):
        raise ValueError("两份G-code均需有挤出路径")
    scale = np.array([1/xy_tolerance, 1/xy_tolerance, 1/z_tolerance])
    d = cKDTree(bb * scale).query(aa * scale)[0]
    return dict(reference_moves=len(aa), candidate_moves=len(bb), sampled_nearby_fraction=float(np.mean(d <= 1)),
                xy_tolerance_mm=xy_tolerance, z_tolerance_mm=z_tolerance,
                note="挤出段中点邻近率；层高/摆放/线宽不同会影响结果，不是等价打印证明")

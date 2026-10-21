from __future__ import annotations
from pathlib import Path
import json
import os
import subprocess
import time
import zipfile
from .core import Context, Cancelled, GeometryError, write_json
from .gcode import parse_gcode


def _flags():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def probe(executable, artifact_model=None, directory=None):
    path = Path(executable)
    if not path.is_file():
        raise FileNotFoundError("切片器路径无效")
    try:
        p = subprocess.run([str(path), "--help"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=20, **_flags())
        helptext = p.stdout.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"kind": "manual", "help": "--help在20秒内未返回，未确认CLI能力"}
    kind = "prusa" if "--export-gcode" in helptext else "bambu" if "--slice" in helptext and "--export-3mf" in helptext else "manual"
    if kind == "manual" and artifact_model and path.name.lower() in ("bambu-studio.exe", "orca-slicer.exe"):
        # Windows GUI launchers sometimes discard --help stdout. Confirm a real
        # documented export operation, rather than inferring CLI support from a name.
        work=Path(directory)
        work.mkdir(parents=True,exist_ok=True)
        artifact=work/"capability_export.3mf"
        try:
            import trimesh
            input_probe=work/'capability_input.stl'
            input_probe.write_bytes(trimesh.exchange.stl.export_stl(trimesh.creation.box([1,1,1])))
            trial=subprocess.run([str(path.resolve()),"--debug","2","--export-3mf",str(artifact),str(input_probe)],
                                 cwd=work,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30,**_flags())
            if trial.returncode==0 and artifact.is_file() and zipfile.is_zipfile(artifact):
                with zipfile.ZipFile(artifact) as z:
                    valid=any(n.endswith('.model') for n in z.namelist())
                if valid:
                    return {"kind":"bambu","help":helptext,"returncode":p.returncode,
                            "detection":"actual_3mf_export_verified",
                            "note":"Windows帮助无输出；已确认实际3MF导出。--slice使用官方文档参数，切片能力以本次实际结果为准",
                            "documentation":"https://github.com/bambulab/BambuStudio/wiki/Command-Line-Usage"}
        except (OSError,subprocess.TimeoutExpired):
            pass
        return {"kind":"bambu","help":helptext,"returncode":p.returncode,
                "detection":"documented_cli_candidate_unconfirmed",
                "note":"帮助/导出探测未确认接口；将尝试官方文档参数，只有实际G-code输出才能通过验证",
                "documentation":"https://github.com/bambulab/BambuStudio/wiki/Command-Line-Usage"}
    return {"kind": kind, "help": helptext[:40000], "returncode": p.returncode}


def run_slicer(executable, model_path, output_dir, settings=(), filament=None, ctx=None, timeout=240):
    ctx = ctx or Context()
    folder = Path(output_dir).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    capability = probe(executable, model_path, folder/'probe')
    write_json(folder / "capability.json", capability)
    if capability["kind"] == "manual":
        report = {"status": "not_verified", "reason": "未检测到可确认的CLI，请手动切片并导入G-code", "capability": capability}
        write_json(folder / "slicer_report.json", report)
        return report
    model_path = Path(model_path).resolve()
    if capability["kind"] == "prusa":
        out = folder / "test.gcode"
        args = [str(Path(executable).resolve()), "--export-gcode", "--output", str(out)]
        for setting in settings: args += ["--load", str(Path(setting).resolve())]
    else:
        if len(settings) != 2 or filament is None:
            raise GeometryError("Bambu/Orca CLI需要完整机器、工艺JSON及耗材JSON，不会猜测打印机配置")
        out = folder / "test.gcode.3mf"
        args = [str(Path(executable).resolve()), "--debug", "5", "--arrange", "1",
                "--outputdir", str(folder),
                "--load-settings", ";".join(str(Path(p).resolve()) for p in settings),
                "--load-filaments", str(Path(filament).resolve()), "--slice", "0", "--export-3mf", str(out)]
    args.append(str(model_path))
    write_json(folder / "invocation.json", {"args": args, "input": str(model_path)})
    start = time.monotonic()
    try:
        with (folder / "console.log").open("wb") as log:
            proc = subprocess.Popen(args, cwd=folder, stdout=log, stderr=subprocess.STDOUT, **_flags())
            try:
                while proc.poll() is None:
                    ctx.check(60, f"切片验证运行中 {int(time.monotonic()-start)}s")
                    if time.monotonic() - start > timeout:
                        raise TimeoutError("切片器超时")
                    time.sleep(.2)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try: proc.wait(timeout=3)
                    except subprocess.TimeoutExpired: proc.kill(); proc.wait()
        transport_error=None
        fallback_gcode=folder/'plate_1.gcode'
        if proc.returncode != 0 or not out.exists():
            # Bambu may successfully write G-code, then fail exporting the project.
            # Keep that distinction explicit instead of discarding genuine path evidence.
            details={}
            result_json=folder/'result.json'
            if result_json.exists():
                try:details=json.loads(result_json.read_text(encoding='utf-8'))
                except (ValueError,OSError):pass
            if details.get('return_code')==-13 and fallback_gcode.is_file() and fallback_gcode.stat().st_size>0:
                transport_error={'returncode':proc.returncode,'error':details.get('error_string'),
                                 'note':'切片已写出文本G-code，但切片工程3MF导出失败；不报告工程保存成功'}
                gcode=fallback_gcode
            else:
                raise GeometryError(f"切片器退出码{proc.returncode}或未生成输出，请查看console.log和result.json")
        elif out.suffix == ".3mf":
            with zipfile.ZipFile(out) as z:
                names = [n for n in z.namelist() if n.endswith(".gcode")]
                if not names:
                    raise GeometryError("切片工程未包含文本G-code")
                gcode = folder / "plate_1.gcode"
                gcode.write_bytes(z.read(names[0]))
        else:
            gcode = out
        stats = parse_gcode(gcode)
        report = {"status": "paths_detected" if stats["extrusion_moves"] else "no_extrusion", "gcode": str(gcode),
                  "statistics": stats, "elapsed_seconds": time.monotonic()-start,
                  "note": "实际调用切片器并检测挤出；主要结构保留需按区域与逐层路径进一步核查"}
        if transport_error:
            report['project_export_error']=transport_error
            report['status']='paths_detected_project_export_failed'
    except Cancelled:
        raise
    except Exception as e:
        report = {"status": "failed", "error": str(e), "elapsed_seconds": time.monotonic()-start}
    write_json(folder / "slicer_report.json", report)
    return report

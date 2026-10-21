"""Spawn-isolated jobs: a native boolean may be terminated without locking Qt."""
import traceback
from .core import Context, Cancelled, Model, Options


def execute_job(job, args, queue, cancel):
    ctx = Context(cancel, lambda v,t: queue.put(("progress", (v,t))))
    try:
        if job == "load":
            from .fileio import load_model
            from .analysis import analyze
            model = load_model(args["path"], ctx, max_faces=Options().max_faces,split=False)
            result = (model, analyze(model, ctx=ctx.scaled(10,90),quick=True))
        elif job == "convert":
            from .ready import convert_ready
            result = convert_ready(args['model'],args['options'],ctx,
                args.get('auto_surface',True) and args['options'].reconstruction!='manual',args.get('resolution',.1))
        elif job == "save":
            from .batch import save_conversion
            from .core import GeometryError
            converted=args['result']
            if converted.report.get('status')!='geometry_passed':
                raise GeometryError('转换结果未通过成品检查，不能直接导出')
            ctx.check(0,'复用已转换结果，正在保存模型')
            paths=save_conversion(converted,args['folder'],args['format'],args['separate'],ctx,
                write_report=False,output_name=args.get('output_name','converted'),auto_number=True)
            result={'paths':[str(p) for p in paths],'report':converted.report}
        elif job == "export":
            from .ready import convert_ready
            from .batch import save_conversion
            from .core import GeometryError
            from .core import sha256
            from pathlib import Path
            source=args['model'].source
            source_hash=sha256(source) if source and Path(source).is_file() else None
            converted = convert_ready(args["model"], args["options"], ctx.scaled(0,90),
                                      args.get('auto_surface',True) and args['options'].reconstruction!='manual',args.get('resolution',.1))
            if converted.report['status']!='geometry_passed':
                raise GeometryError('转换结果未通过成品检查：'+'；'.join(converted.report['issues']))
            if source_hash:
                if sha256(source)!=source_hash:raise GeometryError('源文件校验值发生变化')
                converted.report.update(source_file=source,source_file_sha256=source_hash,source_file_unchanged=True)
            ctx.check(92,'写出模型文件')
            paths=save_conversion(converted,args['folder'],args['format'],args['separate'],ctx.scaled(93,99),
                write_report=False,output_name=args.get('output_name','converted'),auto_number=True)
            result={'result':converted,'paths':[str(p) for p in paths]}
        elif job == "batch":
            from .batch import run_batch
            result = run_batch(args["files"], args["folder"], args["options"], args["format"],
                               open_role=args.get("open_role"), ctx=ctx,write_reports=False)
        elif job == "slice":
            from .slicer import run_slicer
            result = run_slicer(args["exe"], args["model_path"], args["folder"], args["settings"], args["filament"], ctx)
        elif job == "gcode":
            from .gcode import parse_gcode, compare_paths
            result = parse_gcode(args["path"])
            if args.get("reference"):
                result["comparison"] = compare_paths(parse_gcode(args["reference"]), result)
        else:
            raise ValueError("未知后台任务")
        ctx.check()
        # Trimesh's derived triangle/edge caches can dwarf its vertices/faces.
        # Send only geometry and reports across the process boundary.
        if job in ('export','convert'):
            conversion=result['result'] if job=='export' else result
            for part in conversion.model.parts:part.mesh._cache.clear()
        elif job=='load':
            for part in result[0].parts:part.mesh._cache.clear()
        queue.put(("done", result))
    except Cancelled as e:
        queue.put(("cancelled", str(e)))
    except Exception as e:
        queue.put(("error", {"message": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()}))
    finally:
        queue.close()
        queue.join_thread()

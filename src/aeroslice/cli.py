from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from .core import Options, Context, Cancelled, write_json
from . import __version__


def parser():
    p = argparse.ArgumentParser(prog="AeroSliceConverter", description="航模切片兼容转换器；无参数启动图形界面")
    p.add_argument('--version',action='version',version=f'AeroSlice Converter {__version__}')
    sub = p.add_subparsers(dest="command")
    sub.add_parser("gui")
    selftest=sub.add_parser("self-test",help="自动检查桌面渲染、后台转换和导出")
    selftest.add_argument("--output",required=True,type=Path)
    selftest.add_argument("--input",type=Path,help="使用指定真实模型检查导入、零件树与三维渲染")
    selftest.add_argument('--reconstruction',choices=['layered','continuous'],default='layered')
    selftest.add_argument('--reuse-converted',action='store_true',help='检查先转换再直接导出的GUI流程，需指定input')
    selftest.add_argument('--recover-surface-role',action='store_true',help='按0.25mm层高、0.42mm壁厚和分件导出复现Surface类型误选')
    f = sub.add_parser("fixtures", help="生成合法的合成航模测试数据")
    f.add_argument("folder", type=Path)
    a = sub.add_parser("analyze", help="网格和截面诊断")
    a.add_argument("input", type=Path); a.add_argument("--report", type=Path)
    for cmd in ("convert", "batch"):
        c=sub.add_parser(cmd)
        c.add_argument("inputs", nargs="+", type=Path)
        c.add_argument("--output", required=True, type=Path)
        c.add_argument("--mode", choices=["regular","even-odd"])
        c.add_argument('--reconstruction',choices=['layered','continuous','manual'],default='layered',help='默认使用原方案逐层轮廓重建')
        c.add_argument('--layer-height',type=float,default=.2,help='逐层重建层高，输出切片必须保持一致')
        c.add_argument("--thickness",type=float,default=.45)
        c.add_argument("--tolerance",type=float,default=1e-6)
        c.add_argument("--format",choices=["stl","3mf"],default="3mf")
        c.add_argument("--roles", type=Path, help='JSON: {"0":"shell", "1":"sheet"}，索引按诊断的零件顺序')
        c.add_argument("--open-role", choices=["shell","sheet"], help="用户指定所有开放分量的含义；混合结构请逐件指定")
        c.add_argument("--no-merge",action="store_true")
        c.add_argument("--no-repair",action="store_true")
        c.add_argument("--reverse-shell-normals",action="store_true",help="反转外壳的加厚方向，需检查预览")
        c.add_argument("--confirm-ambiguous",action="store_true",help="用户允许将包围开放片的闭合表面推断为外壳")
        c.add_argument("--sections",type=int,default=9)
        c.add_argument("--max-faces",type=int,default=750000)
        c.add_argument("--separate",action="store_true")
    g=sub.add_parser("gcode");g.add_argument("input",type=Path);g.add_argument("--reference",type=Path);g.add_argument("--report",type=Path)
    s=sub.add_parser("slice");s.add_argument("input",type=Path);s.add_argument("--exe",required=True);s.add_argument("--output",required=True,type=Path)
    s.add_argument("--settings",action="append",default=[]);s.add_argument("--filament")
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    if args.command in (None,"gui"):
        from .gui import launch
        return launch()
    ctx=Context(progress=lambda v,t: print(f"[{v:3}%] {t}",file=sys.stderr,flush=True))
    try:
        if args.command=="fixtures":
            from .fixtures import generate
            generate(args.folder)
            print(args.folder.resolve());return 0
        if args.command=="self-test":
            from .gui_selftest import run,run_import,run_reuse
            if args.reuse_converted or args.recover_surface_role:
                if not args.input:raise ValueError('--reuse-converted需要指定--input')
                return run_reuse(args.output,args.input,args.recover_surface_role)
            return run_import(args.output,args.input,args.reconstruction) if args.input else run(args.output)
        if args.command=="analyze":
            from .analysis import analyze
            from .fileio import load_model
            result=analyze(load_model(args.input,ctx),ctx=ctx.scaled(10,100))
            if args.report:write_json(args.report,result)
            print(json.dumps({k:result[k] for k in ("component_count","open_edges","nonmanifold_edges")},ensure_ascii=False))
        elif args.command in ("convert","batch"):
            from .batch import process_file,run_batch,unique_folder
            mode=args.mode or ('even-odd' if args.reconstruction=='layered' else 'regular')
            options=Options(mode,args.thickness,args.tolerance,not args.no_merge,not args.no_repair,
                            args.confirm_ambiguous,args.sections,args.max_faces)
            options.reconstruction=args.reconstruction;options.layer_height=args.layer_height
            options.reverse_shell_normals=args.reverse_shell_normals
            roles=json.loads(args.roles.read_text(encoding="utf-8")) if args.roles else None
            files=[]
            for path in args.inputs:
                if path.is_dir():files.extend(sorted(p for p in path.rglob("*") if p.suffix.lower() in (".stl",".3mf")))
                else:files.append(path)
            if not files:raise ValueError("没有输入模型")
            if args.command=="batch":
                result=run_batch(files,args.output,options,args.format,roles,args.open_role,ctx)
                print(json.dumps(result,ensure_ascii=False))
                return 2 if any(e["status"]=="failed" for e in result["entries"]) else 0
            if len(files)!=1:raise ValueError("多文件请使用batch命令")
            folder=unique_folder(args.output)
            result,paths=process_file(files[0],folder,options,args.format,roles,args.open_role,args.separate,ctx)
            print(json.dumps(dict(status=result.report["status"],output=[str(p) for p in paths],report=str(folder/"conversion_report.json")),ensure_ascii=False))
        elif args.command=="gcode":
            from .gcode import parse_gcode,compare_paths
            result=parse_gcode(args.input)
            if args.reference:result["comparison"]=compare_paths(parse_gcode(args.reference),result)
            if args.report:write_json(args.report,result)
            print(json.dumps({k:v for k,v in result.items() if k not in ("segments","layers")},ensure_ascii=False))
        elif args.command=="slice":
            from .slicer import run_slicer
            result=run_slicer(args.exe,args.input,args.output,args.settings,args.filament,ctx)
            print(json.dumps({k:v for k,v in result.items() if k not in ("statistics","capability")},ensure_ascii=False))
            return 0 if result["status"]=="paths_detected" else 2
        return 0
    except KeyboardInterrupt:
        print("已取消；源文件保持不变",file=sys.stderr);return 130
    except Exception as e:
        print(f"{type(e).__name__}: {e}",file=sys.stderr);return 2

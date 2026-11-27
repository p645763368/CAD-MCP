"""Build and install this checkout with uv. Standard library only.

Build artifacts live in a TemporaryDirectory and are removed on exit. The script
does not launch AutoCAD or overwrite any client's config. All argv is passed as
lists (never interpolated into a shell). UV_TOOL_DIR/UV_TOOL_BIN_DIR support an
isolated installation, e.g. for clone validation.
"""
from pathlib import Path
import argparse,json,os,shutil,subprocess,sys,tempfile,zipfile,hashlib

ROOT=Path(__file__).resolve().parent.parent
def run(args,**kwargs):
    return subprocess.run([str(x) for x in args],check=True,**kwargs)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--workspace',action='append',required=True,help='Absolute drawing directory; repeat for several')
    parser.add_argument('--python',default=sys.executable,help='Interpreter/path or uv Python selector')
    parser.add_argument('--backend',choices=['com','ezdxf'],default='com' if os.name=='nt' else 'ezdxf')
    parser.add_argument('--native-root',help='Override ApplicationPlugins root')
    parser.add_argument('--skip-native',action='store_true',help='Headless-only installation')
    parser.add_argument('--dependency-lock',help='Override bundled exact dependency list')
    args=parser.parse_args()
    uv=shutil.which('uv')
    if not uv:raise SystemExit('Install uv first; this script does not download/execute installers')
    for p in args.workspace:
        if not Path(p).is_absolute() or ',' in p:raise SystemExit('Workspaces must be absolute and contain no commas')
    if args.native_root and not Path(args.native_root).is_absolute():raise SystemExit('--native-root must be absolute')
    # Never replace an in-use tool environment. Runtime identity follows source,
    # native payload and dependency lock, not the user's name or checkout path.
    fingerprint=hashlib.sha256()
    for directory in ['latest/python','latest/native']:
        for p in sorted((ROOT/directory).rglob('*')):
            if not p.is_file() or any(x=='__pycache__' or x.endswith('.egg-info') for x in p.parts):continue
            if p.suffix in ['.pyc','.pyo','.bak','.log']:continue
            fingerprint.update(p.relative_to(ROOT).as_posix().encode());fingerprint.update(b'\0');fingerprint.update(p.read_bytes())
    for name in ['pyproject.toml','latest/config/dependencies.lock.txt']:
        fingerprint.update((ROOT/name).read_bytes())
    identity=fingerprint.hexdigest()
    local=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share')))
    runtime=local/'CAD-MCP/runtimes'/identity[:16]
    env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8',UV_LINK_MODE='copy')
    env.setdefault('UV_TOOL_DIR',str(runtime/'tools'))
    env.setdefault('UV_TOOL_BIN_DIR',str(runtime/'bin'))
    receipt=Path(env['UV_TOOL_DIR'])/'.cad-mcp-source.json'
    existing=Path(env['UV_TOOL_DIR'])/'autocad-mcp-pro'
    reuse=False
    if existing.exists():
        if not receipt.is_file() or json.loads(receipt.read_text(encoding='utf-8')).get('source_sha256')!=identity:
            raise SystemExit('Selected runtime already exists without a matching source receipt. Choose a new UV_TOOL_DIR/UV_TOOL_BIN_DIR; refusing to replace an in-use environment.')
        reuse=True
    with tempfile.TemporaryDirectory(prefix='cad-mcp-build-') as t:
        tmp=Path(t);builder=tmp/'builder'
        run([uv,'venv',builder,'--python',args.python],env=env)
        py=builder/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        run([uv,'pip','install','--python',py,'setuptools>=77,<81','wheel'],env=env)
        # Stage only packaging inputs. Do not copy project data/private configs,
        # or generate egg-info/build directories in the user's working checkout.
        staging=tmp/'source';staging.mkdir()
        def copy_file(src,dst):
            dst.parent.mkdir(parents=True,exist_ok=True)
            data=src.read_bytes()
            if data.startswith(b'%TSD-Header-###%'):raise ValueError('Authorized read is encrypted: '+str(src))
            dst.write_bytes(data)
        for name in ['pyproject.toml','MANIFEST.in','README.md','LICENSE','NOTICE.md']:
            copy_file(ROOT/name,staging/name)
        for directory in ['latest/python','latest/native']:
            for p in (ROOT/directory).rglob('*'):
                if not p.is_file() or any(x=='__pycache__' or x.endswith('.egg-info') for x in p.parts):continue
                if p.suffix in ['.pyc','.pyo','.bak','.log']:continue
                copy_file(p,staging/p.relative_to(ROOT))
        dist=tmp/'dist';dist.mkdir()
        build="import sys,setuptools.build_meta as b; print(b.build_wheel(sys.argv[1]))"
        run([py,'-X','utf8','-c',build,dist],cwd=staging,env=env,stdout=sys.stderr)
        wheels=list(dist.glob('*.whl'))
        if len(wheels)!=1:raise RuntimeError('Expected one wheel')
        with zipfile.ZipFile(wheels[0]) as z:
            names=z.namelist()
            if sum(n.endswith('.dll') for n in names)!=4:raise RuntimeError('Wheel native payload incomplete')
            for n in names:
                data=z.read(n)
                if data.startswith(b'%TSD-Header-###%'):raise RuntimeError('Encrypted wheel entry: '+n)
                if n.endswith('.py'):compile(data.decode('utf-8'),n,'exec')
        command=[uv,'tool','install','--python',args.python]
        constraints=Path(args.dependency_lock).resolve() if args.dependency_lock else ROOT/'latest/config/dependencies.lock.txt'
        if not constraints.is_file():raise FileNotFoundError('Dependency lock missing: '+str(constraints))
        # Pass exact requirements, not a space-containing constraints pathname.
        # Some uv tool versions split that pathname internally on Windows.
        locked=[line.strip() for line in constraints.read_text(encoding='utf-8').splitlines() if line.strip() and not line.lstrip().startswith('#')]
        for requirement in locked:
            if requirement.startswith('-') or '==' not in requirement or requirement.endswith('\\'):
                raise ValueError('Expected one exact requirement per lockfile line')
            command.extend(['--with',requirement])
        command.append(wheels[0])
        if not reuse:
            run(command,env=env)
            receipt.write_text(json.dumps({'source_sha256':identity},indent=2),encoding='utf-8')
    bindir=Path(run([uv,'tool','dir','--bin'],env=env,stdout=subprocess.PIPE,text=True,encoding='utf-8').stdout.strip())
    suffix='.exe' if os.name=='nt' else ''
    print('Installed command directory: '+str(bindir),flush=True)
    runtime_python=existing/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    purelib=Path(run([runtime_python,'-c','import sysconfig; print(sysconfig.get_path("purelib"))'],env=env,stdout=subprocess.PIPE,text=True,encoding='utf-8').stdout.strip())
    for p in (ROOT/'latest/python').rglob('*'):
        if not p.is_file() or any(x=='__pycache__' or x.endswith('.egg-info') for x in p.parts):continue
        if p.suffix in ['.pyc','.pyo','.bak','.log']:continue
        target=purelib/p.relative_to(ROOT/'latest/python')
        if not target.is_file() or target.read_bytes()!=p.read_bytes():
            raise RuntimeError('Installed source differs: '+str(target)+'. Choose a new runtime or repair it while stopped.')
    if not args.skip_native:
        install=[bindir/('autocad-mcp-install-native'+suffix)]
        if args.native_root:install.extend(['--destination',args.native_root])
        run(install,env=env)
    run([bindir/('autocad-mcp-doctor'+suffix)]+([] if args.skip_native else ['--require-native']),
        env=dict(env,**({'CAD_MCP_NATIVE_ROOT':args.native_root} if args.native_root else {})))
    config=[bindir/('autocad-mcp-config'+suffix),'--backend',args.backend]
    for p in args.workspace:config.extend(['--workspace',p])
    if args.native_root:config.extend(['--native-root',args.native_root])
    print('\n# Merge the following CAD-only snippet into your client config; no client config was edited.',flush=True)
    run(config,env=env)

if __name__=='__main__':main()

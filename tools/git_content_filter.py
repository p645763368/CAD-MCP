"""Git clean driver: reject encrypted wrappers; never print credentials/logs.

For normal plaintext input, this is a byte-preserving passthrough. If Git sees
a TSD wrapper, read the same worktree file through the user's authorized Python
file access. No encryption service, keys or security settings are changed.
If the authorized read still returns a wrapper, fail rather than commit it.
Configure this driver only locally, with filter.cad-mcp-content.required=true.
"""
from pathlib import Path
import sys

data=sys.stdin.buffer.read()
if data.startswith(b'%TSD-Header-###%'):
    if len(sys.argv)!=2:
        raise SystemExit('Missing worktree path; refusing encrypted Git input')
    root=Path.cwd().resolve()
    path=(root/sys.argv[1]).resolve()
    if not path.is_relative_to(root) or '.git' in path.relative_to(root).parts:
        raise SystemExit('Clean-filter path is outside the worktree')
    data=path.read_bytes()
if data.startswith(b'%TSD-Header-###%'):
    raise SystemExit('Authorized read still returned encrypted data; commit refused')
sys.stdout.buffer.write(data)

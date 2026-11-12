"""Traj Engine platform package.

The repository-level package is intentionally named ``platform``. Python's
stdlib ``platform`` module is not importable under the same name while this
package is importable, and ``uuid`` imports ``platform.system()`` on Linux.
Load the stdlib implementation under a private name and re-export its public
API so code such as ``uuid`` keeps working on every operating system.
"""

import importlib.util
import os
import sysconfig

_stdlib_platform_path = os.path.join(sysconfig.get_path("stdlib"), "platform.py")
_stdlib_platform_spec = importlib.util.spec_from_file_location(
    "_traj_engine_stdlib_platform", _stdlib_platform_path
)
_stdlib_platform = importlib.util.module_from_spec(_stdlib_platform_spec)
_stdlib_platform_spec.loader.exec_module(_stdlib_platform)

for _name in dir(_stdlib_platform):
    if not _name.startswith("_"):
        globals()[_name] = getattr(_stdlib_platform, _name)


"""TT 创作助手：独立的源码开发版。"""
__version__='2.1.0-dev.2'
import os as _os
import sys as _sys
from pathlib import Path as _Path
_deps=_Path(__file__).resolve().parents[1]/'.deps'
if _deps.is_dir(): _sys.path.insert(0,str(_deps))
# Checkpoints are local; never enable framework telemetry from inherited env.
_os.environ['LANGSMITH_TRACING']='false'
_os.environ['LANGCHAIN_TRACING_V2']='false'

# -*- Python -*-

import os
import platform
import shutil
import sys

import lit.formats

# Configuration file for the 'lit' test runner.

# name: The name of this test suite.
config.name = 'mlir-cobol'

# testFormat: The test format to use to interpret tests.
config.test_format = lit.formats.ShTest(True)

# suffixes: A list of file extensions to treat as test files.
config.suffixes = ['.test']

# test_source_root: The root path where tests are located.
config.test_source_root = os.path.dirname(__file__)

# test_exec_root: The root path where tests should be run.
config.test_exec_root = os.path.join(config.test_source_root, 'Output')

# Ensure Output directory exists
os.makedirs(config.test_exec_root, exist_ok=True)

# Project root directory (parent of test directory)
project_root = os.path.dirname(config.test_source_root)
src_dir = os.path.join(project_root, 'src')

# Substitutions
# NOTE: %python must come before %p to prevent %p from matching
# inside %python as a substring.
config.substitutions.append(('%{project_root}', project_root))
config.substitutions.append(('%{src}', src_dir))

# Find Python
python_path = sys.executable
config.substitutions.append(('%python', python_path))

config.substitutions.append(('%S', config.test_source_root))
config.substitutions.append(('%p', config.test_source_root))

# cobol-translate command - use the installed command from venv
# This ensures xdsl and other dependencies are available
cobol_translate_installed = shutil.which('cobol-translate')
if cobol_translate_installed:
    config.substitutions.append(('%cobol-translate', cobol_translate_installed))
else:
    # Fallback to running script directly with PYTHONPATH
    cobol_translate = os.path.join(src_dir, 'cobol_translate.py')
    cobol_translate_cmd = f'PYTHONPATH={src_dir} {python_path} {cobol_translate}'
    config.substitutions.append(('%cobol-translate', cobol_translate_cmd))

# KOOPA_PATH from environment or config
koopa_path = os.environ.get('KOOPA_PATH', getattr(config, 'koopa_path', ''))
if koopa_path:
    config.environment['KOOPA_PATH'] = koopa_path
    config.available_features.add('koopa')

# Platform-specific features
if platform.system() == 'Darwin':
    config.available_features.add('darwin')
elif platform.system() == 'Linux':
    config.available_features.add('linux')

# Find and add FileCheck
filecheck_path = None
for path in ['/usr/local/opt/llvm/bin', '/opt/homebrew/opt/llvm/bin', '/usr/bin']:
    candidate = os.path.join(path, 'FileCheck')
    if os.path.exists(candidate):
        filecheck_path = candidate
        break

if not filecheck_path:
    filecheck_path = shutil.which('FileCheck')

if filecheck_path:
    config.substitutions.append(('FileCheck', filecheck_path))
else:
    # If FileCheck is not found, tests will fail but we'll let lit report it
    config.substitutions.append(('FileCheck', 'FileCheck'))

# Environment variables
config.environment['PYTHONPATH'] = src_dir

# Find mlir-translate: check MLIR_TRANSLATE env var, then common paths, then PATH
mlir_translate_path = os.environ.get('MLIR_TRANSLATE', '')
if not mlir_translate_path:
    for path in ['/opt/homebrew/opt/llvm@21/bin',
                 '/opt/homebrew/opt/llvm/bin',
                 '/usr/local/opt/llvm/bin',
                 '/usr/bin']:
        candidate = os.path.join(path, 'mlir-translate')
        if os.path.exists(candidate):
            mlir_translate_path = candidate
            break
if not mlir_translate_path:
    mlir_translate_path = shutil.which('mlir-translate') or 'mlir-translate'
config.substitutions.append(('%mlir-translate', mlir_translate_path))
if os.path.isfile(mlir_translate_path):
    config.available_features.add('mlir-translate')

# Find clang: check CLANG_PATH env var, then common paths, then PATH
clang_path = os.environ.get('CLANG_PATH', '')
if not clang_path:
    for path in ['/opt/homebrew/opt/llvm@21/bin',
                 '/opt/homebrew/opt/llvm@20/bin',
                 '/opt/homebrew/opt/llvm@19/bin',
                 '/opt/homebrew/opt/llvm/bin',
                 '/usr/local/opt/llvm/bin',
                 '/usr/lib/llvm-19/bin',
                 '/usr/lib/llvm-18/bin',
                 '/usr/lib/llvm-17/bin',
                 '/usr/bin']:
        candidate = os.path.join(path, 'clang')
        if os.path.exists(candidate):
            clang_path = candidate
            break
if not clang_path:
    clang_path = shutil.which('clang') or 'clang'
config.substitutions.append(('%clang', clang_path))
if os.path.isfile(clang_path):
    config.available_features.add('clang')

# Find opt: check OPT_PATH env var, then common paths, then PATH
opt_path = os.environ.get('OPT_PATH', '')
if not opt_path:
    for path in ['/opt/homebrew/opt/llvm@21/bin',
                 '/opt/homebrew/opt/llvm@20/bin',
                 '/opt/homebrew/opt/llvm@19/bin',
                 '/opt/homebrew/opt/llvm/bin',
                 '/usr/local/opt/llvm/bin',
                 '/usr/lib/llvm-19/bin',
                 '/usr/lib/llvm-18/bin',
                 '/usr/lib/llvm-17/bin',
                 '/usr/bin']:
        candidate = os.path.join(path, 'opt')
        if os.path.exists(candidate):
            opt_path = candidate
            break
if not opt_path:
    opt_path = shutil.which('opt') or 'opt'
config.substitutions.append(('%opt', opt_path))
if os.path.isfile(opt_path):
    config.available_features.add('opt')

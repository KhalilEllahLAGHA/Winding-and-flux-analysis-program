"""Run FEMM validation in an isolated, time-limited process.

FEMM 4.2 embeds Lua 4.0, so the launch wrapper deliberately uses its global
``call``, ``openfile`` and ``write`` functions rather than modern Lua APIs.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time


REQUIRED_METRICS = (
    'airgap_br_max_t',
    'airgap_br_avg_excited_t',
    'airgap_flux_max_wb',
    'airgap_flux_avg_excited_wb',
)


def locate_femm_executable():
    """Find the native Windows FEMM installation, honoring ``FEMM_EXE``."""
    candidates = [os.environ.get('FEMM_EXE', '').strip().strip('"'),
                  shutil.which('femm.exe'), r'C:\femm42\bin\femm.exe']
    for variable, default in (('ProgramFiles', r'C:\Program Files'),
                              ('ProgramFiles(x86)', r'C:\Program Files (x86)')):
        candidates.append(str(Path(os.environ.get(variable, default))
                              / 'femm42' / 'bin' / 'femm.exe'))
    if os.environ.get('LOCALAPPDATA'):
        candidates.append(str(Path(os.environ['LOCALAPPDATA'])
                              / 'Programs' / 'femm42' / 'bin' / 'femm.exe'))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    return None


def parse_validation_results(path):
    """Read complete, finite FEMM metrics; never treat missing data as zero."""
    metrics = {}
    for raw_line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            raise ValueError(f'Invalid FEMM result line: {line!r}')
        key, value = (part.strip() for part in line.split('=', 1))
        if not key or key in metrics:
            raise ValueError(f'Invalid or duplicate FEMM result key: {key!r}')
        try:
            parsed = float(value)
        except ValueError:
            parsed = value
        if isinstance(parsed, float) and not math.isfinite(parsed):
            raise ValueError(f'FEMM result {key} is not finite.')
        metrics[key] = parsed
    for key in REQUIRED_METRICS:
        value = metrics.get(key)
        if not isinstance(value, float) or value < 0:
            raise ValueError(f'Missing or invalid FEMM result: {key}')
    return metrics


def _lua_string(value):
    return ('"' + str(value).replace('\\', '/').replace('"', '\\"')
            .replace('\r', '\\r').replace('\n', '\\n') + '"')


def _wrapper_source(lua_path, error_path, *, native, keep_open=False,
                    done_path=None):
    # Literal paths avoid Lua 4's different upvalue/closure syntax.
    source = f'''keep_femm_open = {'1' if keep_open else 'nil'}
function validation_error(message)
    local handle = openfile({_lua_string(error_path)}, "w")
    if handle then
        write(handle, tostring(message), "\\n")
        closefile(handle)
    end
end
_ERRORMESSAGE = validation_error
local ok = call(dofile, {{{_lua_string(lua_path)}}}, "x", validation_error)
if not ok then
    local handle = openfile({_lua_string(error_path)}, "a")
    if handle then
        write(handle, "FEMM could not complete the validation Lua script.\\n")
        closefile(handle)
    end
end
'''
    if keep_open:
        source += f'''if ok then
    local handle = openfile({_lua_string(done_path)}, "w")
    if handle == nil then
        validation_error("Cannot write the FEMM completion marker.")
        quit()
    else
        write(handle, "completed\\n")
        closefile(handle)
    end
else
    quit()
end
'''
    elif native:
        source += 'quit()\n'
    return source


def _windows_job_api():
    """Share the job-limit structure between creation and successful detach."""
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64),
                    ('PerJobUserTimeLimit', ctypes.c_int64),
                    ('LimitFlags', wintypes.DWORD),
                    ('MinimumWorkingSetSize', ctypes.c_size_t),
                    ('MaximumWorkingSetSize', ctypes.c_size_t),
                    ('ActiveProcessLimit', wintypes.DWORD),
                    ('Affinity', ctypes.c_size_t),
                    ('PriorityClass', wintypes.DWORD),
                    ('SchedulingClass', wintypes.DWORD)]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in (
            'ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
            'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [('BasicLimitInformation', BasicLimits),
                    ('IoInfo', IoCounters),
                    ('ProcessMemoryLimit', ctypes.c_size_t),
                    ('JobMemoryLimit', ctypes.c_size_t),
                    ('PeakProcessMemoryUsed', ctypes.c_size_t),
                    ('PeakJobMemoryUsed', ctypes.c_size_t)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                               ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    return kernel, ExtendedLimits


def _windows_job(process):
    """Tie this launch's child processes to its lifetime where supported."""
    if os.name != 'nt':
        return None
    import ctypes

    kernel, ExtendedLimits = _windows_job_api()
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        return None
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
    if (not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits),
                                            ctypes.sizeof(limits))
            or not kernel.AssignProcessToJobObject(job, int(process._handle))):
        kernel.CloseHandle(job)
        return None
    return kernel, job


def _release_windows_job(job):
    """Leave a successful interactive FEMM session alive when its worker exits."""
    if job is None:
        return
    import ctypes

    kernel, handle = job
    _, ExtendedLimits = _windows_job_api()
    limits = ExtendedLimits()  # Clear KILL_ON_JOB_CLOSE before releasing the job.
    if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits),
                                          ctypes.sizeof(limits)):
        raise ctypes.WinError(ctypes.get_last_error())
    kernel.CloseHandle(handle)


def _stop_process_tree(process, job):
    if job is not None:
        kernel, handle = job
        kernel.CloseHandle(handle)
    elif process.poll() is None:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=subprocess.CREATE_NO_WINDOW,
                           check=False, timeout=10)
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    if process.poll() is None:
        process.kill()
    process.communicate(timeout=10)


def run_femm_script(lua_path, results_path, timeout=300, *, keep_open=False):
    """Execute a script and require complete results before reporting success.

    The caller supplies a distinct run directory. Native FEMM is preferred;
    the Python bridge is isolated in a child process when no executable is
    discoverable. With keep_open, return when the script completes and leave
    the displayed solution open. Failed or timed-out runs are still cleaned up.
    Only processes started for this run are terminated.
    """
    lua_path = Path(lua_path).resolve()
    results_path = Path(results_path).resolve()
    if not lua_path.is_file():
        raise FileNotFoundError(f'FEMM validation script not found: {lua_path}')
    if results_path == lua_path:
        raise ValueError('FEMM results must use a different path from the script.')
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('FEMM timeout must be positive and finite.')
    error_path = results_path.with_suffix('.error.txt')
    done_path = results_path.with_suffix('.done.txt')
    results_path.unlink(missing_ok=True)
    error_path.unlink(missing_ok=True)
    done_path.unlink(missing_ok=True)
    executable = locate_femm_executable()
    native = executable is not None
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                     prefix='.run-femm-', suffix='.lua',
                                     dir=lua_path.parent, delete=False) as wrapper:
        wrapper.write(_wrapper_source(lua_path, error_path, native=native,
                                      keep_open=keep_open, done_path=done_path))
        wrapper_path = Path(wrapper.name)
    if native:
        command = [executable, f'-lua-script={wrapper_path}', '-windowhide']
        backend = 'femm-exe'
    else:
        command = [sys.executable, str(Path(__file__).resolve()),
                   '--pyfemm-worker', str(wrapper_path)]
        if keep_open:
            command.append('--keep-open')
        backend = 'python-femm'
    process = None
    job = None
    detached = False
    log = None
    try:
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {
            'start_new_session': True}
        if keep_open:
            log = (lua_path.parent / 'femm_runner.log').open('wb')
        process = subprocess.Popen(command, cwd=lua_path.parent,
                                   stdout=log if keep_open else subprocess.PIPE,
                                   stderr=log if keep_open else subprocess.PIPE,
                                   **options)
        job = _windows_job(process)
        if keep_open:
            deadline = time.monotonic() + timeout
            while True:
                if error_path.exists():
                    # The error marker takes precedence over any partial output.
                    detail = error_path.read_text(encoding='utf-8', errors='replace').strip()
                    raise RuntimeError(f'FEMM Lua error: {detail}')
                if done_path.exists():
                    parse_validation_results(results_path)
                    _release_windows_job(job)
                    job = None
                    detached = True
                    return backend
                if process.poll() is not None:
                    raise RuntimeError('FEMM closed before completing the validation.')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                time.sleep(min(0.05, remaining))
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _stop_process_tree(process, job)
            job = None
            raise subprocess.TimeoutExpired(command, timeout) from None
        if error_path.exists():
            detail = error_path.read_text(encoding='utf-8', errors='replace').strip()
            raise RuntimeError(f'FEMM Lua error: {detail}')
        if process.returncode:
            detail = (stderr or stdout).decode('utf-8', errors='replace').strip()
            raise RuntimeError(f'FEMM exited with code {process.returncode}: {detail}')
        if not results_path.is_file():
            raise RuntimeError('FEMM finished without generating validation results.')
        parse_validation_results(results_path)
        return backend
    finally:
        if job is not None:
            kernel, handle = job
            kernel.CloseHandle(handle)
        if not detached and process is not None and process.poll() is None:
            _stop_process_tree(process, None)
        if log is not None:
            log.close()
        wrapper_path.unlink(missing_ok=True)


def _pyfemm_worker(wrapper_path, *, keep_open=False):
    import femm

    if os.name != 'nt':
        raise RuntimeError('FEMM validation requires an isolated native Windows '
                           'FEMM installation; set FEMM_EXE to femm.exe.')
    # DispatchEx creates this worker's own FEMM instance instead of attaching
    # to a FEMM document the user already has open.
    import win32com.client

    femm.HandleToFEMM = win32com.client.DispatchEx('femm.ActiveFEMM')
    try:
        femm.callfemm(f'dofile({_lua_string(wrapper_path)})')
        if keep_open:
            # Retain the automation reference until the user closes FEMM.
            # The parent returns on the completion marker, not on this loop.
            while True:
                time.sleep(1)
                femm.callfemm('0')
    finally:
        try:
            femm.callfemm('quit()')
        except Exception:
            pass
        femm.closefemm()


if __name__ == '__main__':
    if len(sys.argv) not in (3, 4) or sys.argv[1] != '--pyfemm-worker':
        raise SystemExit('This module is an internal FEMM process worker.')
    _pyfemm_worker(sys.argv[2], keep_open='--keep-open' in sys.argv[3:])

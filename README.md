# CANN Operator Toolbox

English | [简体中文](README.zh-CN.md)

A small desktop toolbox for people using Huawei Ascend C / CANN operator-development utilities, especially the CANN Operator Development Toolchain around `msopgen`, `msopst`, `msprof`, `mskpp`, `msdebug`, and `mssanitizer`.

It is made for developers who are actually using that toolchain with a real Ascend developer kit or board. The goal is not to replace the official tools, but to make the parts we repeatedly need during custom-operator development easier to run, explain, and extend.

The project is intentionally practical: it turns frequently used CANN commands into forms and buttons, keeps generated commands visible, and includes local report scripts for profiling and simulator outputs.

This toolbox exists because the official tools and documents are useful but not always enough for a real board workflow. Some documented features are not supported on every board path, some commands need board-specific values, and some outputs are much easier to understand after extra parsing or plotting. The toolbox records those experiments as clickable workflows, warnings, and small scripts.

It is also designed to be extended. New scripts can be plugged in through JSON manifests, so you can keep improving analysis scripts without rewriting the GUI.

In other words: this is a practical companion for the CANN operator developer toolkit. It includes official-tool command templates, board-tested notes, scripts added during our own exploration, and a plugin format for adding new one-click utilities as the workflow grows.

## What It Does

- Connects to a board over SSH/SFTP.
- Builds common command lines for `msopgen`, `msopst`, `msprof`, `mskpp`, `msdebug`, and `mssanitizer`.
- Provides JSON builders for:
  - `msOpGen` operator description JSON.
  - `msOpST` case JSON.
- Converts selected profiling / simulator outputs into Excel reports or plots.
- Includes notes in the UI for known Atlas 200I DK A2 / Ascend310B caveats.
- Supports plugin-style script integration through `cann_toolbox/plugins/*.json`.

## Current Status

This is a learning/project toolbox, not an official CANN product. It is meant to sit beside the official CANN developer toolkit and make repeated operator-development tasks easier to run and explain.

Known caveats:

- `msDebug` real-time NPU kernel debugging is marked unsupported for our Ascend310B4 path after local experiments.
- `msSanitizer` support is still being explored. The UI provides command templates, but a clean "no error" result does not yet prove the operator is free from memory/race issues unless the kernel was correctly compiled with sanitizer instrumentation.
- Many default paths are examples from our board workflow. Change them in the UI before running commands on your own board.

## Requirements

- Windows with Python 3.10+.
- Python packages:

```powershell
python -m pip install paramiko openpyxl matplotlib numpy
```

`paramiko` is required for SSH/SFTP. The other packages are used by report/plot scripts.

## Start

From the repository root:

```powershell
python .\cann_toolbox\run_toolbox.py
```

If `python` is not on `PATH`, use your Python executable directly:

```powershell
"C:\Path\To\python.exe" .\cann_toolbox\run_toolbox.py
```

## Board Configuration

Default board settings are examples only:

- Host: `192.168.0.2`
- Port: `22`
- User: `HwHiAiUser`
- CANN path: `/usr/local/Ascend/cann-8.5.0`

No password is committed. Enter it in the UI if needed and use "Save config" only for your own local machine.

For USB RNDIS connections, the Windows-side adapter commonly needs:

```text
192.168.0.1 / 255.255.255.0
no gateway
```

## Repository Layout

```text
cann_toolbox/                         GUI application, config, plugins, docs
官方算子开发工具/msProf/.../tools/     local msProf plotting/report scripts
官方算子开发工具/msOpGen/tools/        local trace report script
agent_tools/                          small helper script used by local analysis
```

The Chinese directory names mirror the original learning project because the toolbox currently references these paths with `{workspace}/...` placeholders.

## Adding Your Own Scripts

Most local analysis buttons are plugin entries. To add a script without editing the GUI code:

1. Put the script somewhere inside the repository.
2. Add or edit a JSON manifest under `cann_toolbox/plugins/`.
3. Use `{workspace}/...` or `{toolbox}/...` for script paths instead of absolute local paths.
4. Provide a `command_template`, input/output fields, and dependency hints.

See `cann_toolbox/plugins/PLUGIN_PROTOCOL.md` for the current manifest format.

## Safety Notes

- Do not commit `cann_toolbox/config/toolbox_config.json`; it may contain local board credentials.
- Treat Debug/Sanitizer/bug-injected operator builds as experiments, not release builds.
- Read generated commands before sending them to the board.

## License

MIT

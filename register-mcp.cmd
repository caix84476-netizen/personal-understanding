@echo off
rem personal-understanding: register the local MCP with every AI client detected on this machine (idempotent).
py -3 "%~dp0scripts\install_mcp.py" --auto %*
if errorlevel 1 (
  python "%~dp0scripts\install_mcp.py" --auto %*
)
pause

@echo off
rem Daily scheduled backup wrapper (installed 2026-09-02 after mass-deletion incident)
rem Runs from Task Scheduler "PersonalUnderstanding Daily Backup" at 12:30 daily.
cd /d "C:\Users\Administrator\.codex\skills\personal-understanding"
"C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe" "scripts\backup_archive.py" >> "backups\scheduled-backup.log" 2>&1

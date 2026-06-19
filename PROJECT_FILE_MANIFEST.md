# Project File Manifest

This repository contains the final-year project materials for **CST Health Monitoring Station / Basic Health Monitoring Station**.

## Included

- `main.py`, `config.py`, `core/`, `screens/`, `services/`, `widgets/`, `tests/`: PyQt6 kiosk application source code.
- `assets/`: UI images, icons, fonts, sounds, and visual resources used by the kiosk application.
- `data/config/`: non-sensitive default JSON configuration files.
- `project_documents/final_report/`: final report in PDF and editable Word format.
- `project_documents/manual/`: project manual.
- `project_documents/research/`: journal and IEEE-style research documents.
- `project_documents/compliance/`: plagiarism report PDF.
- `project_documents/presentations/`: editable project presentation.
- `project_documents/media/`: smaller demonstration videos under GitHub's file-size limit.
- `hardware_and_design/arduino/`: Arduino/ESP32 firmware sketch.
- `hardware_and_design/proteus/`: Proteus circuit project files.
- `hardware_and_design/fritzing/`: Fritzing circuit file.
- `hardware_and_design/components/`: component and cost spreadsheets.
- `hardware_and_design/models/`: SketchUp kiosk/mechanical model files.
- `hardware_and_design/datasheets/`: referenced hardware datasheets.
- `hardware_and_design/sample_outputs/`: sample health-rule dataset/output files.

## Intentionally Excluded

The following local files were not uploaded because they are generated, duplicated, too large for normal GitHub, or not suitable for a public source repository:

- Runtime SQLite database files from `data/db/`.
- Runtime logs from `data/logs/`.
- Generated QR/report/export/temp/share/backups from `data/`.
- Python `__pycache__` folders and `.pyc` files.
- Office lock/temp files such as `~$*.docx`, `~$*.xlsx`, and `~$*.pptx`.
- Large root-level videos over GitHub's 100 MB file limit.
- Local software/application folders such as SketchUp installation files.
- Duplicate ZIP archives/backups already represented by the extracted source and documents.

## Security Note

The public repository version uses environment variables for administrator defaults. Before deployment, set:

```powershell
$env:CST_KIOSK_ADMIN_USERNAME = "your-admin-user"
$env:CST_KIOSK_ADMIN_PASSWORD = "your-strong-password"
```

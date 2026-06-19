# Security Notes

- Do not commit real patient or personally identifiable health records.
- Runtime databases, logs, generated reports, QR exports, temporary files, and backups are ignored by Git.
- Set `CST_KIOSK_ADMIN_USERNAME` and `CST_KIOSK_ADMIN_PASSWORD` in the deployment environment instead of hardcoding credentials.
- The included `hardware_and_design/sample_outputs/Health_Data_243.xlsx` is a rule/category dataset for project demonstration, not a patient database.

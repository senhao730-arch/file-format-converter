# Tests

Install the application dependencies and pytest, then run from the repository root:

```powershell
python -m pip install -r requirements.txt
python -m pip install pytest
python -m pytest tests -q
```

The Office integration test is skipped by default. To run it with a locally installed, activated Microsoft Office:

```powershell
$env:RUN_OFFICE_TESTS = "1"
python -m pytest tests -q
```

Tests generate local fixtures and keep original files unchanged. GUI tests require an interactive Windows desktop.

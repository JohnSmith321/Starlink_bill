---
description: how to run Python commands in this project
---

# Always use the venv

All Python commands must use the project's virtual environment.
Since shell activation doesn't persist between terminal calls, always
invoke the venv binaries directly.

## Python / scripts

```powershell
venv\Scripts\python main.py
venv\Scripts\python -m pytest
```

## pip

```powershell
venv\Scripts\pip install <package>
venv\Scripts\pip install -r requirements.txt
```

## Streamlit

```powershell
venv\Scripts\streamlit run app.py
```

// turbo-all

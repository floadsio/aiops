# Publishing aiops-cli to PyPI

This guide explains how to publish the `aiops-cli` package to PyPI (Python Package Index).

## Prerequisites

1. **PyPI Account**: Create an account at [https://pypi.org/account/register/](https://pypi.org/account/register/)
2. **TestPyPI Account** (optional but recommended): Create an account at [https://test.pypi.org/account/register/](https://test.pypi.org/account/register/)
3. **API Tokens**: Generate API tokens for both PyPI and TestPyPI in your account settings

## Setup

### 1. Install Build Tools

```bash
pip install --upgrade pip setuptools wheel twine build
```

### 2. Configure PyPI Credentials

Create or edit `~/.pypirc`:

```ini
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = __token__
password = pypi-AgEIcHlwaS5vcmcC... # Your PyPI API token

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = pypi-AgENdGVzdC5weXBpLm9yZwI... # Your TestPyPI API token
```

**Security Note**: Make sure `.pypirc` has restricted permissions:
```bash
chmod 600 ~/.pypirc
```

## Building the Package

### 1. Clean Previous Builds

```bash
cd cli
rm -rf build/ dist/ *.egg-info/
```

### 2. Build Distribution Files

```bash
python -m build
```

This creates:
- `dist/aiops-cli-0.3.0.tar.gz` - Source distribution
- `dist/aiops_cli-0.3.0-py3-none-any.whl` - Wheel distribution

### 3. Verify the Build

```bash
twine check dist/*
```

Should output: `Checking dist/aiops-cli-0.3.0.tar.gz: PASSED`

## Testing on TestPyPI (Recommended)

Before publishing to the main PyPI, test on TestPyPI:

### 1. Upload to TestPyPI

```bash
twine upload --repository testpypi dist/*
```

### 2. Test Installation

```bash
# Create a test virtual environment
python -m venv test-env
source test-env/bin/activate

# Install from TestPyPI (dependencies come from PyPI)
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ aiops-cli

# Test the CLI
aiops --version
aiops --help

# Cleanup
deactivate
rm -rf test-env
```

## Publishing to PyPI

Once you've verified everything works on TestPyPI:

### 1. Upload to PyPI

```bash
twine upload dist/*
```

You'll see output like:
```
Uploading distributions to https://upload.pypi.org/legacy/
Uploading aiops_cli-0.3.0-py3-none-any.whl
100%|████████████████████████████████████| 50.0k/50.0k [00:01<00:00, 25.0kB/s]
Uploading aiops-cli-0.3.0.tar.gz
100%|████████████████████████████████████| 45.0k/45.0k [00:00<00:00, 50.0kB/s]

View at:
https://pypi.org/project/aiops-cli/0.3.0/
```

### 2. Verify Installation

```bash
pip install aiops-cli
aiops --version
```

### 3. Update README Badge (Optional)

Add a PyPI badge to your README.md:

```markdown
[![PyPI version](https://badge.fury.io/py/aiops-cli.svg)](https://badge.fury.io/py/aiops-cli)
[![Python versions](https://img.shields.io/pypi/pyversions/aiops-cli.svg)](https://pypi.org/project/aiops-cli/)
```

## Updating the Package

When releasing a new version:

### 1. Update Version Number

Edit `cli/setup.py` and increment the version:

```python
version="0.3.1",  # Increment from 0.3.0
```

### 2. Update Changelog

Document changes in `CHANGELOG.md` or `README.md`

### 3. Clean, Build, and Publish

```bash
# Clean
rm -rf build/ dist/ *.egg-info/

# Build
python -m build

# Check
twine check dist/*

# Upload to TestPyPI (optional)
twine upload --repository testpypi dist/*

# Upload to PyPI
twine upload dist/*
```

## Troubleshooting

### "File already exists" Error

PyPI doesn't allow re-uploading the same version. You must increment the version number.

### Authentication Failed

- Verify your API token is correct in `~/.pypirc`
- Make sure you're using `__token__` as the username
- Check that your token hasn't expired

### Missing Files in Distribution

- Verify `MANIFEST.in` includes all necessary files
- Check `include_package_data=True` is in `setup.py`
- Run `tar -tzf dist/aiops-cli-*.tar.gz` to inspect contents

### Import Errors After Installation

- Check `packages=find_packages()` finds all packages
- Verify `entry_points` console_scripts path is correct
- Test in a clean virtual environment

## Automation with GitHub Actions (Optional)

Create `.github/workflows/publish.yml`:

```yaml
name: Publish to PyPI

on:
  release:
    types: [published]

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install build twine
      - name: Build package
        run: |
          cd cli
          python -m build
      - name: Publish to PyPI
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
        run: |
          cd cli
          twine upload dist/*
```

Add your PyPI API token as a GitHub secret named `PYPI_API_TOKEN`.

## Resources

- [PyPI Documentation](https://pypi.org/help/)
- [Python Packaging Guide](https://packaging.python.org/tutorials/packaging-projects/)
- [Twine Documentation](https://twine.readthedocs.io/)
- [Setuptools Documentation](https://setuptools.pypa.io/)

## Quick Reference Commands

```bash
# Full publishing workflow
cd cli
rm -rf build/ dist/ *.egg-info/
python -m build
twine check dist/*
twine upload --repository testpypi dist/*  # Test first
twine upload dist/*  # Publish to PyPI
```

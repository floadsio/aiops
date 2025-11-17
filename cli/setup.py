"""Setup configuration for aiops-cli."""

from setuptools import find_packages, setup

with open("README.md", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="aiops-cli",
    version="0.3.0",
    description="Command-line interface for AIops REST API - manage issues, git operations, and AI workflows",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Floads.io",
    author_email="ivo@floads.io",
    url="https://github.com/floadsio/aiops",
    project_urls={
        "Bug Tracker": "https://github.com/floadsio/aiops/issues",
        "Documentation": "https://github.com/floadsio/aiops#readme",
        "Source Code": "https://github.com/floadsio/aiops",
    },
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "click>=8.1",
        "requests>=2.32",
        "rich>=13.7",
        "pydantic>=2.5",
        "pyyaml>=6.0",
        "python-dateutil>=2.8",
    ],
    entry_points={
        "console_scripts": [
            "aiops=aiops_cli.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: System :: Systems Administration",
        "Topic :: Utilities",
    ],
    keywords="aiops cli devops automation git issues workflow",
    include_package_data=True,
)

from pathlib import Path
from setuptools import setup, find_packages

VERSION = "2022.12.24"

setup(
    name="pyschlage",
    version=VERSION,
    description="Python API for interacting with Schlage WiFi locks.",
    long_description=Path("README.md").read_text(),
    long_description_content_type="text/markdown",
    classifiers=[
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    download_url="https://github.com/dknowles2/pyschlage/tarball/" + VERSION,
    keywords="schlage,api,iot",
    author="David Knowles",
    author_email="dknowles2@gmail.com",
    packages=find_packages(),
    python_requires=">=3.8",
    url="https://github.com/dknowles2/pyschlage",
    license="Apache License 2.0",
    install_requires=[
        "pycognito==2022.11.2",
        "requests==2.28.1",
    ],
    include_package_data=True,
    zip_safe=True,
)

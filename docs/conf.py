# Configuration file for the Sphinx documentation builder.

import datetime
from importlib.metadata import version as _pkg_version
import os
import sys

sys.path.insert(0, os.path.abspath(".."))

project = "pyschlage"
copyright = f"{datetime.datetime.now(tz=datetime.UTC).year}, David Knowles"
author = "David Knowles"
release = _pkg_version("pyschlage")
extensions = ["sphinx.ext.autodoc", "sphinx.ext.autosummary"]
templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
autodoc_member_order = "groupwise"

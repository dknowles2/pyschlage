# Configuration file for the Sphinx documentation builder.

import os
import sys

sys.path.insert(0, os.path.abspath(".."))

project = "pyschlage"
copyright = "2023, David Knowles"
author = "David Knowles"
release = "2023.3.2"
extensions = ["sphinx.ext.autodoc", "sphinx.ext.autosummary"]
templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
autodoc_member_order = "groupwise"

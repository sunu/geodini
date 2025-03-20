from setuptools import find_packages
from setuptools import setup


setup(
    name="geodini",
    install_requires="pluggy>=0.3,<1.0",
    entry_points={"console_scripts": ["geodini=geodini.tools.agents:search_places"]},
    packages=find_packages(),
)

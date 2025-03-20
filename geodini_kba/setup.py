from setuptools import setup


setup(
    name="geodini-kba",
    install_requires="geodini",
    entry_points={"geodini": ["kba = geodini_kba"]},
    py_modules=["geodini_kba"],
)

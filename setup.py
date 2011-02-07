
try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

setup(
        name='ayps',
        version='0.1',
        install_requires=['Twisted'],
        packages=['ayps'],
        scripts=['scripts/ayps']
        )

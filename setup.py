
try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

setup(
        name='ayps',
        version='0.2.4',
        author='Dorian Raymer',
        author_email='deldotdr@gmail.com',
        packages=['ayps'],
        scripts=['scripts/ayps'],
        use_incremental=True,
        setup_requires=['incremental'],
        install_requires=['Twisted', 'incremental'],
        )

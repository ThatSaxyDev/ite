from ite import __version__
print('__version__ from ite module:', __version__)

# Try the package version
try:
    from importlib.metadata import version
    pkg_version = version('ite-agent')
    print('ite-agent package version:', pkg_version)
except Exception as e:
    print('Error getting package version:', e)
"""Content salts shared by nested PDF text-extraction caches.

This module deliberately imports none of ascii.py, tree.py or fonts.py.  All
three need the same salt, and putting it in any one of them creates an import
cycle before the decorators can be built.
"""
import os


# Files whose content decides which Rows pdf_to_ascii returns.
_ASCII_DERIVATION_SOURCES = (
    ('derivation.py',),                    # this manifest/hash algorithm
    ('ascii.py',),                         # grouping, Row, Phrase
    ('tree.py',),                          # glyph geometry/page traversal
    ('fonts.py',),                         # embedded-font decoding
    ('pdf2txt', '__init__.py'),            # text normalisation
    ('unicode_mappings', 'Wingdings.txt'), # reference data read by fonts.py
)

# These libraries participate directly in the derivation but live outside the
# repository, so content hashes are unavailable. Missing metadata raises:
# silently substituting "unknown" would make the component look guarded while
# remaining inert across an upgrade.
_ASCII_DERIVATION_PACKAGES = ('pdfminer.six', 'PyMuPDF', 'fonttools')


def _compute_ascii_derivation_sig(root=None):
    """Hash declared source/data inputs and Python dependency versions.

    ``root`` lets tests perturb copies under ``tmp_path``. Production callers
    use the directory containing this module. Host tools (notably FontForge)
    and the remote Adobe Symbol mapping are not content-addressed here; their
    existing nested caches remain bounded by TTL rather than this generation.
    """
    import hashlib
    import sys
    import unicodedata
    from importlib.metadata import version
    from dslib.cache import _file_content_sig

    d = root or os.path.dirname(os.path.abspath(__file__))
    h = hashlib.sha256()
    for rel in _ASCII_DERIVATION_SOURCES:
        h.update('/'.join(rel).encode())
        h.update(_file_content_sig(os.path.join(d, *rel)).encode())
    for package in _ASCII_DERIVATION_PACKAGES:
        h.update(('%s=%s' % (package, version(package))).encode())
    h.update(('python=%s' % '.'.join(map(str, sys.version_info[:3]))).encode())
    h.update(('unicode=%s' % unicodedata.unidata_version).encode())
    return 'pdf-ascii:' + h.hexdigest()[:16]


# Snapshot the code generation this process actually imported. Computing from
# disk on every call would let an old long-running process observe new files
# and poison the new cache generation with old in-memory code. As with the
# repository's other eager content salts, an edit in the narrow interval
# between this import and a dependency's import remains outside the guarantee;
# closing that needs loader-captured source or startup source quiescence.
_ASCII_DERIVATION_SIG = _compute_ascii_derivation_sig()


def ascii_derivation_salt(root=None):
    if root is None:
        return _ASCII_DERIVATION_SIG
    return _compute_ascii_derivation_sig(root)

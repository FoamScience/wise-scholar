import io

import pytest

pypdf = pytest.importorskip("pypdf")
from pypdf import PdfReader, PdfWriter  # noqa: E402
from pypdf.constants import UserAccessPermissions as Permissions  # noqa: E402

from wise_scholar import book


def test_locked_book_opens_without_a_password_but_allows_printing_only():
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    plain = io.BytesIO()
    writer.write(plain)

    reader = PdfReader(io.BytesIO(book.lock(plain.getvalue())))
    assert reader.is_encrypted and reader.decrypt("") and len(reader.pages) == 1
    granted = reader.user_access_permissions
    assert granted & Permissions.PRINT and granted & Permissions.PRINT_TO_REPRESENTATION
    for denied in (Permissions.EXTRACT, Permissions.EXTRACT_TEXT_AND_GRAPHICS, Permissions.MODIFY,
                   Permissions.ADD_OR_MODIFY, Permissions.FILL_FORM_FIELDS, Permissions.ASSEMBLE_DOC):
        assert not granted & denied
